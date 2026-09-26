"""OMNI-312 and OMNI-313: the live capture worker, and its reconnection.

Driven with a scripted fake stream and a fake clock — no camera, no broker — so
the tests are deterministic. Frames go through the real `process_frame` and
write real files, which is what makes "the same path as a file" a tested claim
rather than an intention. The real stream, the real broker and the real
consumer were exercised live (docs/context/week-03-04.md).

live_capture.py and pipeline.py are loaded by file path under their own names,
the same way the other ingestion tests do it: ingestion and query both have a
top-level package called `app`.
"""

import importlib.util
import itertools
import threading
import time
from pathlib import Path

import numpy as np
import pytest

APP = Path(__file__).resolve().parents[1] / "app"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, APP / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pipeline = _load("omnisight_ingestion_pipeline_for_live", "pipeline.py")
live = _load("omnisight_ingestion_live_capture", "live_capture.py")

FRAME_PERIOD_S = 0.04  # a 25 fps camera
START = 1_790_000_000.0  # a Unix time, as a live stream is stamped with
WAIT_S = 5.0


class FakeClock:
    def __init__(self):
        self.now = START

    def __call__(self) -> float:
        return self.now


class FakeCapture:
    """A stream that delivers a frame every 1/25 s of fake time.

    `frames` limits how many it delivers before it stops (the stream dropping);
    None means it goes on until released. `open_ok=False` is a stream that
    cannot be opened. `pace_s` slows each read in real time so a worker that is
    meant to run "forever" does not spin.
    """

    def __init__(self, clock, *, frames=None, open_ok=True, pace_s=0.0, gate_event=None):
        self._clock = clock
        self._limit = frames
        self._open_ok = open_ok
        self._pace_s = pace_s
        self._gate_event = gate_event
        self.delivered = 0
        self.release_calls = 0

    def isOpened(self):
        return self._open_ok

    def grab(self):
        if self.release_calls:
            return False
        if self._gate_event is not None:
            self._gate_event.wait(WAIT_S)
        if self._limit is not None and self.delivered >= self._limit:
            return False
        if self._pace_s:
            time.sleep(self._pace_s)
        self.delivered += 1
        self._clock.now += FRAME_PERIOD_S
        return True

    def retrieve(self):
        frame = np.full((48, 64, 3), 40, dtype=np.uint8)
        frame[10:20, (self.delivered * 2) % 50 : (self.delivered * 2) % 50 + 10] = (0, 200, 255)
        return True, frame

    def release(self):
        self.release_calls += 1


class Script:
    """The connections a camera offers, one per attempt to open it. The last
    step repeats for ever, so a script ending in a healthy stream stays healthy
    and one ending in a dead camera stays dead."""

    def __init__(self, clock, steps):
        self._clock = clock
        self._steps = list(steps)
        self.opened: list[FakeCapture] = []

    def open(self):
        step = self._steps.pop(0) if len(self._steps) > 1 else self._steps[0]
        capture = FakeCapture(self._clock, **step)
        self.opened.append(capture)
        return capture


class FakePublisher:
    def __init__(self, fail_after=None, fail_events=False):
        self.records = []
        self.events = []  # (status, at, worker_id)
        self.closed = 0
        self.keepalives = 0
        self._fail_after = fail_after
        self._fail_events = fail_events

    def publish(self, record):
        if self._fail_after is not None and len(self.records) >= self._fail_after:
            raise RuntimeError("broker refused the message")
        self.records.append(record)

    def publish_event(self, camera_id, status, at, worker_id=None):
        if self._fail_events:
            raise RuntimeError("could not publish the event")
        self.events.append((status, at, worker_id))

    def keepalive(self):
        self.keepalives += 1

    def close(self):
        self.closed += 1


class _EveryOtherGate(pipeline.FrameGate):
    """Admits every second frame it is shown, so both outcomes occur."""

    def __init__(self):
        self.seen = 0

    def evaluate(self, frame, timestamp_s):
        self.seen += 1
        admitted = self.seen % 2 == 0
        return pipeline.GateDecision(
            motion_score=1.0,
            admitted=admitted,
            clip_start_s=timestamp_s - 1.0 if admitted else None,
            clip_end_s=timestamp_s if admitted else None,
            admission_reason="motion" if admitted else None,
        )


class RecordingBackoff(live.Backoff):
    """A backoff that remembers what it told the worker to wait."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.delays: list[float] = []

    def next(self):
        delay = super().next()
        self.delays.append(delay)
        return delay


def _worker(tmp_path, clock, capture, publisher, *, camera_id=7, interval=0.19, make_process=None, **extra):
    """A worker over one capture (or a `Script.open`), processing frames through
    the real `process_frame`."""
    frames_dir, thumbs_dir = tmp_path / "frames", tmp_path / "thumbs"
    frames_dir.mkdir(exist_ok=True)
    thumbs_dir.mkdir(exist_ok=True)
    process_makes = []

    def real_make_process():
        gate = _EveryOtherGate()
        process_makes.append(gate)

        def process(frame, timestamp_s, index):
            return pipeline.process_frame(
                frame,
                pipeline.FrameSource(
                    source_type="camera",
                    frame_index=index,
                    timestamp_s=timestamp_s,
                    video_id=None,
                    camera_id=camera_id,
                ),
                gate,
                frames_dir,
                thumbs_dir,
                thumb_width=32,
                frame_quality=80,
                thumb_quality=60,
            )

        return process

    worker = live.LiveWorker(
        camera_id,
        open_capture=(lambda: capture) if not callable(getattr(capture, "open", None)) else capture.open,
        make_publisher=lambda: publisher,
        make_process=make_process or real_make_process,
        sample_interval_s=interval,
        clock=clock,
        **extra,
    )
    worker.process_makes = process_makes
    return worker


def _fast_wait(clock, seen=None):
    """A wait that returns at once (moving fake time on), so a test can run
    through minutes of backoff in milliseconds."""

    def wait(seconds):
        if seen is not None:
            seen.append(seconds)
        clock.now += seconds
        return False

    return wait


def _until(predicate, timeout=WAIT_S):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _run_to_the_end(worker):
    """Start a worker on a stream that ends by itself, and wait for its thread."""
    worker.start(WAIT_S)
    worker._thread.join(WAIT_S)
    assert not worker.alive


# --- what a worker publishes -------------------------------------------------


def test_it_samples_the_stream_instead_of_processing_every_frame(tmp_path):
    clock = FakeClock()
    capture = FakeCapture(clock, frames=75)  # three seconds of a 25 fps camera
    publisher = FakePublisher()
    worker = _worker(tmp_path, clock, capture, publisher)
    worker._backoff = live.Backoff(60, 60)  # the stream ends; do not retry inside this test

    worker.start(WAIT_S)
    assert _until(lambda: worker.grabbed == 75)
    worker.stop(WAIT_S)

    assert worker.grabbed == 75  # every frame was read...
    # ...but only one in five was processed: a 0.19 s interval lands on every
    # fifth 0.04 s frame (0.24 s is the first at or past 0.04 + 0.19).
    assert worker.published == len(publisher.records) == 15
    times = [record.timestamp_s for record in publisher.records]
    assert all(later - earlier >= 0.19 for earlier, later in itertools.pairwise(times))


def test_a_sampled_frame_is_an_ordinary_camera_segment(tmp_path):
    clock = FakeClock()
    publisher = FakePublisher()
    worker = _worker(tmp_path, clock, FakeCapture(clock, frames=40), publisher, camera_id=7)
    worker._backoff = live.Backoff(60, 60)

    worker.start(WAIT_S)
    assert _until(lambda: worker.grabbed == 40)
    worker.stop(WAIT_S)

    records = publisher.records
    assert records
    assert {record.source_type for record in records} == {"camera"}
    assert {record.camera_id for record in records} == {7}
    assert {record.video_id for record in records} == {None}
    assert [record.frame_index for record in records] == list(range(len(records)))
    # Stamped with the clock's own time, not seconds from some zero.
    assert all(record.timestamp_s > START for record in records)


def test_only_an_admitted_frame_gets_files_exactly_as_for_a_file(tmp_path):
    clock = FakeClock()
    publisher = FakePublisher()
    worker = _worker(tmp_path, clock, FakeCapture(clock, frames=60), publisher)
    worker._backoff = live.Backoff(60, 60)

    worker.start(WAIT_S)
    assert _until(lambda: worker.grabbed == 60)
    worker.stop(WAIT_S)

    admitted = [r for r in publisher.records if r.admitted]
    discarded = [r for r in publisher.records if not r.admitted]
    assert admitted and discarded
    for record in admitted:
        assert Path(record.frame_path).is_file() and Path(record.thumb_path).is_file()
        assert record.clip_end_s == record.timestamp_s
    for record in discarded:
        assert record.frame_path is None and record.thumb_path is None
        assert record.motion_score == 1.0  # still scored, still stored


# --- lifecycle ---------------------------------------------------------------


def test_it_is_running_once_the_first_frame_arrives(tmp_path):
    clock = FakeClock()
    capture = FakeCapture(clock, pace_s=0.001)
    worker = _worker(tmp_path, clock, capture, FakePublisher())
    try:
        assert worker.state is live.WorkerState.STARTING
        assert worker.start(WAIT_S) is live.WorkerState.RUNNING
    finally:
        worker.stop(WAIT_S)


def test_stopping_releases_the_stream_the_broker_connection_and_the_thread(tmp_path):
    clock = FakeClock()
    capture = FakeCapture(clock, pace_s=0.001)
    publisher = FakePublisher()
    worker = _worker(tmp_path, clock, capture, publisher)
    worker.start(WAIT_S)
    time.sleep(0.2)
    assert worker.published > 0

    assert worker.stop(WAIT_S) is True

    assert not worker.alive  # no orphan thread
    assert capture.release_calls == 1  # no open stream
    assert publisher.closed == 1  # no open broker connection
    assert worker.state is live.WorkerState.STOPPED
    after = len(publisher.records)
    time.sleep(0.2)
    assert len(publisher.records) == after  # and nothing more is published


def test_a_stream_that_cannot_be_opened_at_the_start_fails_at_once_and_is_not_retried(tmp_path):
    clock = FakeClock()
    script = Script(clock, [{"open_ok": False}])
    publisher = FakePublisher()
    worker = _worker(tmp_path, clock, script, publisher, wait=_fast_wait(clock))

    assert worker.start(WAIT_S) is live.WorkerState.FAILED

    assert worker.error == "could not open the stream"
    assert len(script.opened) == 1  # a start that cannot deliver says so; it does not loop
    assert script.opened[0].release_calls == 1
    assert publisher.records == [] and publisher.events == []
    worker._thread.join(WAIT_S)
    assert publisher.closed == 1


def test_a_stream_that_opens_but_never_delivers_a_frame_fails_the_start(tmp_path):
    clock = FakeClock()
    script = Script(clock, [{"frames": 0}])
    worker = _worker(tmp_path, clock, script, FakePublisher(), wait=_fast_wait(clock))

    assert worker.start(WAIT_S) is live.WorkerState.FAILED
    assert worker.error == "the stream opened but delivered no frame"
    assert script.opened[0].release_calls == 1


def test_a_broker_that_refuses_a_message_stops_the_worker_and_says_why(tmp_path):
    clock = FakeClock()
    capture = FakeCapture(clock, pace_s=0.001)
    publisher = FakePublisher(fail_after=2)
    worker = _worker(tmp_path, clock, capture, publisher)

    worker.start(WAIT_S)
    worker._thread.join(WAIT_S)

    assert worker.state is live.WorkerState.FAILED
    assert "broker refused" in worker.error
    assert capture.release_calls == 1 and publisher.closed == 1
    assert not worker.alive


def test_a_failure_while_processing_a_frame_stops_the_worker_and_releases_everything(tmp_path):
    clock = FakeClock()
    capture = FakeCapture(clock, pace_s=0.001)
    publisher = FakePublisher()

    def make_exploding_process():
        def explode(frame, timestamp_s, index):
            raise ValueError("the gate blew up")

        return explode

    worker = _worker(tmp_path, clock, capture, publisher, make_process=make_exploding_process)
    worker.start(WAIT_S)
    worker._thread.join(WAIT_S)

    assert worker.state is live.WorkerState.FAILED
    assert capture.release_calls == 1 and publisher.closed == 1


# --- the backoff -------------------------------------------------------------


def test_the_backoff_doubles_up_to_its_cap_and_stays_there():
    backoff = live.Backoff(1.0, 30.0, jitter=0.0)

    assert [backoff.next() for _ in range(8)] == [1, 2, 4, 8, 16, 30, 30, 30]


def test_the_backoff_starts_again_from_the_beginning_after_a_reset():
    backoff = live.Backoff(1.0, 30.0, jitter=0.0)
    for _ in range(4):
        backoff.next()

    backoff.reset()

    assert [backoff.next() for _ in range(3)] == [1, 2, 4]


def test_jitter_moves_each_delay_a_little_either_way_but_never_past_the_cap():
    low = live.Backoff(10.0, 30.0, jitter=0.2, rng=lambda: 0.0)
    high = live.Backoff(10.0, 30.0, jitter=0.2, rng=lambda: 1.0)

    assert low.next() == pytest.approx(8.0)  # 10 s less 20%
    assert high.next() == pytest.approx(12.0)  # 10 s plus 20%
    for _ in range(6):
        assert high.next() <= 30.0


# --- reconnection ------------------------------------------------------------


def test_a_dropped_stream_is_reported_unreachable_then_resumes_by_itself(tmp_path):
    clock = FakeClock()
    script = Script(clock, [{"frames": 30}, {}])  # drops after 30 frames, then comes back
    publisher = FakePublisher()
    states = []
    worker = _worker(tmp_path, clock, script, publisher, backoff=live.Backoff(1.0, 30.0, jitter=0.0))
    worker._wait = lambda seconds: (states.append(worker.state), setattr(clock, "now", clock.now + seconds), False)[2]

    worker.start(WAIT_S)
    assert _until(lambda: worker.reconnects == 1 and len(publisher.records) > 20)

    assert [status for status, _, _ in publisher.events] == ["unreachable", "connected"]
    assert all(worker_id == worker.worker_id for _, _, worker_id in publisher.events)
    unreachable_at, connected_at = publisher.events[0][1], publisher.events[1][1]
    assert START < unreachable_at < connected_at  # in the order it happened
    assert set(states) == {live.WorkerState.RECONNECTING}  # it was waiting to retry while it waited
    assert worker.state is live.WorkerState.RUNNING
    # Capture resumed: frames from after the drop were stored.
    assert max(r.timestamp_s for r in publisher.records) > connected_at
    worker.stop(WAIT_S)


def test_the_wait_between_attempts_grows_while_the_camera_stays_dead(tmp_path):
    clock = FakeClock()
    # Works, drops, then four attempts fail before the fifth succeeds.
    script = Script(clock, [{"frames": 10}, {"open_ok": False}] + [{"open_ok": False}] * 3 + [{}])
    backoff = RecordingBackoff(1.0, 30.0, jitter=0.0)
    publisher = FakePublisher()
    worker = _worker(tmp_path, clock, script, publisher, backoff=backoff, wait=_fast_wait(clock))

    worker.start(WAIT_S)
    assert _until(lambda: worker.reconnects == 1)
    worker.stop(WAIT_S)

    assert backoff.delays == [1, 2, 4, 8, 16]  # never every 100 ms
    assert worker.failed_attempts == 4
    assert len(script.opened) == 1 + 4 + 1


def test_it_keeps_trying_for_as_long_as_the_camera_is_dead(tmp_path):
    clock = FakeClock()
    script = Script(clock, [{"frames": 10}] + [{"open_ok": False}] * 40 + [{}])
    publisher = FakePublisher()
    worker = _worker(
        tmp_path, clock, script, publisher,
        backoff=live.Backoff(1.0, 30.0, jitter=0.0), wait=_fast_wait(clock),
    )

    worker.start(WAIT_S)
    assert _until(lambda: worker.reconnects == 1)
    worker.stop(WAIT_S)

    assert worker.failed_attempts == 40  # it did not give up and did not fail
    assert worker.state is not live.WorkerState.FAILED


def test_a_camera_that_flaps_does_not_earn_a_fresh_backoff_each_time_it_comes_back(tmp_path):
    clock = FakeClock()
    # Three connections that last three frames (0.12 s) each, then one that
    # lasts 12 s of stream time — past the 10 s that counts as stable.
    script = Script(clock, [{"frames": 3}] * 3 + [{"frames": 300}] + [{"frames": 3}, {}])
    backoff = RecordingBackoff(1.0, 30.0, jitter=0.0)
    worker = _worker(
        tmp_path, clock, script, FakePublisher(), backoff=backoff,
        stable_after_s=10.0, wait=_fast_wait(clock),
    )

    worker.start(WAIT_S)
    assert _until(lambda: len(backoff.delays) >= 5)
    worker.stop(WAIT_S)

    # Short-lived connections keep the backoff growing; the long one, once it
    # drops, starts it again from the shortest wait.
    assert backoff.delays[:5] == [1, 2, 4, 1, 2]


def test_every_connection_gets_a_fresh_gate(tmp_path):
    clock = FakeClock()
    script = Script(clock, [{"frames": 20}, {"frames": 20}, {}])
    worker = _worker(
        tmp_path, clock, script, FakePublisher(),
        backoff=live.Backoff(1.0, 30.0, jitter=0.0), wait=_fast_wait(clock),
    )

    worker.start(WAIT_S)
    assert _until(lambda: worker.reconnects == 2)
    worker.stop(WAIT_S)

    # A gate that survived the gap would compare the first frame back with
    # frames from before it, and read the difference as motion.
    assert len(worker.process_makes) == 3
    assert len({id(gate) for gate in worker.process_makes}) == 3


def test_no_frame_is_lost_or_counted_twice_across_a_reconnection(tmp_path):
    clock = FakeClock()
    script = Script(clock, [{"frames": 25}, {"frames": 25}])
    publisher = FakePublisher()
    worker = _worker(
        tmp_path, clock, script, publisher,
        backoff=live.Backoff(1.0, 30.0, jitter=0.0), wait=_fast_wait(clock),
    )

    worker.start(WAIT_S)
    assert _until(lambda: worker.reconnects >= 1 and worker.grabbed >= 50)
    worker.stop(WAIT_S)

    # The frame read to prove a reconnection works is used, not thrown away and
    # not read again: what was grabbed is exactly what the captures delivered.
    assert worker.grabbed == sum(capture.delivered for capture in script.opened)
    indexes = [record.frame_index for record in publisher.records]
    assert indexes == list(range(len(indexes)))  # one unbroken count across the gap


def test_every_stream_it_opened_is_released(tmp_path):
    clock = FakeClock()
    script = Script(clock, [{"frames": 10}, {"open_ok": False}, {"frames": 10}, {}])
    worker = _worker(
        tmp_path, clock, script, FakePublisher(),
        backoff=live.Backoff(1.0, 30.0, jitter=0.0), wait=_fast_wait(clock),
    )

    worker.start(WAIT_S)
    assert _until(lambda: worker.reconnects == 2)
    worker.stop(WAIT_S)

    assert len(script.opened) >= 4
    assert all(capture.release_calls == 1 for capture in script.opened)


def test_stopping_while_it_waits_to_retry_ends_at_once_and_releases_everything(tmp_path):
    clock = FakeClock()
    script = Script(clock, [{"frames": 10}, {"open_ok": False}])
    publisher = FakePublisher()
    # A 60 s wait, with the real, interruptible wait.
    worker = _worker(tmp_path, clock, script, publisher, backoff=live.Backoff(60.0, 60.0, jitter=0.0))
    worker.start(WAIT_S)
    assert _until(lambda: worker.state is live.WorkerState.RECONNECTING)

    began = time.monotonic()
    assert worker.stop(WAIT_S) is True

    assert time.monotonic() - began < 2.0  # not a minute
    assert not worker.alive
    assert publisher.closed == 1
    assert all(capture.release_calls == 1 for capture in script.opened)
    assert len(script.opened) == 1  # and it never tried again


def test_the_broker_connection_is_kept_alive_while_it_waits(tmp_path):
    clock = FakeClock()
    script = Script(clock, [{"frames": 10}, {}])
    publisher = FakePublisher()
    worker = _worker(
        tmp_path, clock, script, publisher,
        backoff=live.Backoff(2.0, 30.0, jitter=0.0), wait=_fast_wait(clock),
    )

    worker.start(WAIT_S)
    assert _until(lambda: worker.reconnects == 1)
    worker.stop(WAIT_S)

    # A 2 s wait is four half-second steps; each one lets the connection answer
    # the broker, or a 30 s wait would have it closed on the worker.
    assert publisher.keepalives >= 4


def test_failing_to_report_a_status_change_does_not_stop_the_capture(tmp_path):
    clock = FakeClock()
    script = Script(clock, [{"frames": 10}, {}])
    publisher = FakePublisher(fail_events=True)
    worker = _worker(
        tmp_path, clock, script, publisher,
        backoff=live.Backoff(1.0, 30.0, jitter=0.0), wait=_fast_wait(clock),
    )

    worker.start(WAIT_S)
    assert _until(lambda: worker.reconnects == 1 and len(publisher.records) > 10)
    worker.stop(WAIT_S)

    assert publisher.events == []  # nothing got through...
    assert worker.state is not live.WorkerState.FAILED  # ...and capture carried on regardless


def test_a_worker_waiting_to_reconnect_reports_what_it_is_doing(tmp_path):
    clock = FakeClock()
    script = Script(clock, [{"frames": 10}, {"open_ok": False}])
    worker = _worker(tmp_path, clock, script, FakePublisher(), backoff=live.Backoff(60.0, 60.0, jitter=0.0))
    worker.start(WAIT_S)
    try:
        assert _until(lambda: worker.state is live.WorkerState.RECONNECTING)
        snapshot = worker.snapshot()
        assert snapshot["status"] == "reconnecting"
        assert snapshot["error"] == "the stream stopped delivering frames"
        assert snapshot["last_frame_at"] is not None
    finally:
        worker.stop(WAIT_S)


# --- one worker per camera ---------------------------------------------------


def _registry_factory(tmp_path, clock, camera_id, **capture_kwargs):
    return lambda: _worker(
        tmp_path, clock, FakeCapture(clock, pace_s=0.001, **capture_kwargs), FakePublisher(),
        camera_id=camera_id,
    )


def test_a_camera_has_at_most_one_worker(tmp_path):
    registry = live.WorkerRegistry()
    clock = FakeClock()
    first = registry.start(7, _registry_factory(tmp_path, clock, 7), WAIT_S)
    try:
        with pytest.raises(live.AlreadyRunning) as raised:
            registry.start(7, _registry_factory(tmp_path, clock, 7), WAIT_S)
        assert raised.value.worker is first
        assert len(registry.snapshots()) == 1
    finally:
        registry.stop_all(WAIT_S)


def test_a_second_start_while_the_first_is_still_waiting_for_its_stream_is_refused(tmp_path):
    registry = live.WorkerRegistry()
    clock = FakeClock()
    hold = threading.Event()  # the stream has not delivered its first frame yet
    started = []

    def slow_start():
        started.append(
            registry.start(
                7, _registry_factory(tmp_path, clock, 7, gate_event=hold), WAIT_S
            )
        )

    thread = threading.Thread(target=slow_start)
    thread.start()
    try:
        deadline = time.monotonic() + WAIT_S
        while registry.get(7) is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert registry.get(7).state is live.WorkerState.STARTING
        with pytest.raises(live.AlreadyRunning):
            registry.start(7, _registry_factory(tmp_path, clock, 7), WAIT_S)
    finally:
        hold.set()
        thread.join(WAIT_S)
        registry.stop_all(WAIT_S)
    assert len(started) == 1


def test_a_camera_whose_worker_is_waiting_to_reconnect_still_has_a_worker(tmp_path):
    registry = live.WorkerRegistry()
    clock = FakeClock()
    script = Script(clock, [{"frames": 10}, {"open_ok": False}])

    def factory():
        return _worker(tmp_path, clock, script, FakePublisher(), camera_id=7,
                       backoff=live.Backoff(60.0, 60.0, jitter=0.0))

    worker = registry.start(7, factory, WAIT_S)
    try:
        assert _until(lambda: worker.state is live.WorkerState.RECONNECTING)
        with pytest.raises(live.AlreadyRunning):
            registry.start(7, factory, WAIT_S)  # not a second worker on a camera that is coming back
    finally:
        registry.stop_all(WAIT_S)
    assert not worker.alive


def test_stopping_a_camera_removes_its_worker_and_leaves_the_others(tmp_path):
    registry = live.WorkerRegistry()
    clock = FakeClock()
    registry.start(1, _registry_factory(tmp_path, clock, 1), WAIT_S)
    registry.start(2, _registry_factory(tmp_path, clock, 2), WAIT_S)
    try:
        assert registry.stop(1, WAIT_S) is True
        assert registry.get(1) is None
        assert registry.get(2).state is live.WorkerState.RUNNING
        assert registry.stop(1, WAIT_S) is False  # stopping again is harmless
        assert registry.stop(99, WAIT_S) is False  # so is stopping a camera that never ran
    finally:
        registry.stop_all(WAIT_S)
    assert registry.snapshots() == []


def test_a_camera_whose_worker_failed_can_be_started_again(tmp_path):
    registry = live.WorkerRegistry()
    clock = FakeClock()
    failed = registry.start(7, _registry_factory(tmp_path, clock, 7, open_ok=False), WAIT_S)
    assert failed.state is live.WorkerState.FAILED

    again = registry.start(7, _registry_factory(tmp_path, clock, 7), WAIT_S)
    try:
        assert again.state is live.WorkerState.RUNNING
        assert again.worker_id != failed.worker_id
    finally:
        registry.stop_all(WAIT_S)
