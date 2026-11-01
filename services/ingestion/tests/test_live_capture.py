"""OMNI-312, 313, 314 and 501: the live capture worker, its reconnection, its
bounded queue, and gating every frame while publishing only the admitted ones.

Driven with a scripted fake stream and a fake clock — no camera, no broker — so
the tests are deterministic. Frames go through the real `process_frame` and
write real files, which is what makes "the same path as a file" a tested claim
rather than an intention. The real stream, the real broker and the real
consumer were exercised live (docs/context/week-03-04.md).

The worker is two threads (capture and processing), so a test that looks at what
was published waits for it (`_until`) or stops the worker first, which drains the
queue.

live_capture.py and pipeline.py are loaded by file path under their own names,
the same way the other ingestion tests do it: ingestion and query both have a
top-level package called `app`.
"""

import importlib.util
import itertools
import logging
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
BIG_QUEUE = 10_000  # functional tests must not drop; the drop tests set their own


_WORKERS: list = []


@pytest.fixture(autouse=True)
def _stop_every_worker_a_test_started():
    """A test that fails before it stops its worker would leave a thread reading
    an endless fake stream, starving every test after it into failing too."""
    yield
    for worker in _WORKERS:
        worker.stop(2.0)
    _WORKERS.clear()


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
    def __init__(self, fail_after=None, fail_events=False, fail_stats=False, block=None, backlog=0):
        self.records = []
        self.events = []  # (status, at, worker_id)
        self.stats = []  # the reports, as dicts
        self.closed = 0
        self.keepalives = 0
        self.backlog_reads = 0
        self.backlog_value = backlog
        self._fail_after = fail_after
        self._fail_events = fail_events
        self._fail_stats = fail_stats
        self._block = block  # an Event: while it is clear, publishing hangs (a stalled broker)

    def publish(self, record):
        if self._block is not None:
            self._block.wait(WAIT_S * 4)
        if self._fail_after is not None and len(self.records) >= self._fail_after:
            raise RuntimeError("broker refused the message")
        self.records.append(record)

    def publish_event(self, camera_id, status, at, worker_id=None):
        if self._fail_events:
            raise RuntimeError("could not publish the event")
        self.events.append((status, at, worker_id))

    def publish_stats(self, report):
        if self._fail_stats:
            raise RuntimeError("could not publish the stats")
        self.stats.append(dict(report))

    def backlog(self):
        self.backlog_reads += 1
        return self.backlog_value

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


def _worker(tmp_path, clock, capture, publisher, *, camera_id=7, make_process=None, **extra):
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

    extra.setdefault("queue_size", BIG_QUEUE)
    worker = live.LiveWorker(
        camera_id,
        open_capture=(lambda: capture) if not callable(getattr(capture, "open", None)) else capture.open,
        make_publisher=lambda: publisher,
        make_process=make_process or real_make_process,
        clock=clock,
        **extra,
    )
    worker.process_makes = process_makes
    _WORKERS.append(worker)
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


def _finish(worker):
    """Wait for both threads of a worker whose stream ends by itself (and which
    then fails or stops), so everything queued has been handled."""
    worker._capture_thread.join(WAIT_S)
    worker._processor_thread.join(WAIT_S)
    assert not worker.alive


# --- what a worker publishes -------------------------------------------------


def test_every_frame_is_gated_and_none_is_skipped_before_the_gate(tmp_path):
    clock = FakeClock()
    capture = FakeCapture(clock, frames=75)  # three seconds of a 25 fps camera
    publisher = FakePublisher()
    worker = _worker(tmp_path, clock, capture, publisher)
    worker._backoff = live.Backoff(60, 60)  # the stream ends; do not retry inside this test

    worker.start(WAIT_S)
    assert _until(lambda: worker.grabbed == 75)
    worker.stop(WAIT_S)

    # Algorithm 1 has no sampling step: what the stream delivered is what the
    # gate was shown, frame for frame.
    assert worker.grabbed == worker.captured == worker.gated == 75
    assert worker.process_makes[0].seen == 75
    assert worker.dropped == 0


def test_only_an_admitted_frame_is_published(tmp_path):
    clock = FakeClock()
    publisher = FakePublisher()
    worker = _worker(tmp_path, clock, FakeCapture(clock, frames=60), publisher)
    worker._backoff = live.Backoff(60, 60)

    worker.start(WAIT_S)
    assert _until(lambda: worker.grabbed == 60)
    worker.stop(WAIT_S)

    # The gate here admits every second frame.
    assert worker.gated == 60 and worker.admitted == 30 and worker.discarded == 30
    assert worker.published == len(publisher.records) == 30
    assert all(record.admitted and record.admission_reason == "motion" for record in publisher.records)
    # A discarded frame leaves nothing behind: no message, and no file either.
    frames = sorted(path.name for path in (tmp_path / "frames").iterdir())
    thumbs = sorted(path.name for path in (tmp_path / "thumbs").iterdir())
    assert frames == thumbs == [f"{record.frame_index:06d}.jpg" for record in publisher.records]


def test_an_admitted_frame_is_an_ordinary_camera_segment_with_its_clip(tmp_path):
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
    # The index counts every gated frame, as a file's does, so the admitted
    # ones (every second frame here) are not consecutive.
    assert [record.frame_index for record in records] == list(range(1, 40, 2))
    # Stamped with the clock's own time, not seconds from some zero.
    assert all(record.timestamp_s > START for record in records)
    for record in records:
        assert Path(record.frame_path).is_file() and Path(record.thumb_path).is_file()
        assert record.clip_start_s < record.clip_end_s == record.timestamp_s


# --- Algorithm 1 on a live stream (OMNI-501) ---------------------------------

STILL_FRAMES = 100  # four seconds of a 25 fps camera with nothing happening
MOVING_FRAMES = 100  # then four seconds with something crossing the picture
STRIDE_S = 0.5
HEARTBEAT_S = 1.0


class StillThenMovingCapture(FakeCapture):
    """A scene that does not change at all for `STILL_FRAMES`, and then has a
    bright block crossing it."""

    def retrieve(self):
        frame = np.full((96, 128, 3), 40, dtype=np.uint8)
        moving = self.delivered - STILL_FRAMES
        if moving > 0:
            left = (moving * 4) % 96
            frame[30:66, left : left + 32] = (0, 200, 255)
        return True, frame


def _algorithm_1_worker(tmp_path, clock, publisher, **extra):
    """A worker with the gate a real camera gets: `MotionGate` inside
    `HeartbeatGate`, the settings' defaults, through the real `process_frame`."""
    frames_dir, thumbs_dir = tmp_path / "frames", tmp_path / "thumbs"

    def make_process():
        gate = pipeline.HeartbeatGate(
            pipeline.MotionGate(
                grid_size=8, cell_threshold=25.0, min_active_cells=3, stride_s=STRIDE_S, blur_kernel=21
            ),
            heartbeat_interval_s=HEARTBEAT_S,
            stride_s=STRIDE_S,
            start_s=clock.now,
        )

        def process(frame, timestamp_s, index):
            return pipeline.process_frame(
                frame,
                pipeline.FrameSource(
                    source_type="camera", frame_index=index, timestamp_s=timestamp_s, camera_id=7
                ),
                gate,
                frames_dir,
                thumbs_dir,
                thumb_width=32,
                frame_quality=80,
                thumb_quality=60,
            )

        return process

    capture = StillThenMovingCapture(clock, frames=STILL_FRAMES + MOVING_FRAMES)
    worker = _worker(tmp_path, clock, capture, publisher, make_process=make_process, **extra)
    worker._backoff = live.Backoff(60, 60)
    return worker


def _run_still_then_moving(tmp_path, **extra):
    clock = FakeClock()
    publisher = FakePublisher()
    worker = _algorithm_1_worker(tmp_path, clock, publisher, **extra)
    worker.start(WAIT_S)
    assert _until(lambda: worker.grabbed == STILL_FRAMES + MOVING_FRAMES)
    worker.stop(WAIT_S)
    moving_from = START + STILL_FRAMES * FRAME_PERIOD_S
    still = [r for r in publisher.records if r.timestamp_s <= moving_from]
    moving = [r for r in publisher.records if r.timestamp_s > moving_from]
    return worker, publisher, still, moving


def test_a_still_then_moving_stream_publishes_only_the_frames_the_gate_admits(tmp_path):
    worker, publisher, still, moving = _run_still_then_moving(tmp_path)

    assert worker.gated == STILL_FRAMES + MOVING_FRAMES  # every frame was gated
    assert all(record.admitted for record in publisher.records)  # and only admitted ones went out
    assert len(publisher.records) < worker.gated

    # Nothing moves: the only frames kept are the heartbeat's, one a second.
    assert {record.admission_reason for record in still} == {"heartbeat"}
    assert 3 <= len(still) <= 4
    gaps = [later.timestamp_s - earlier.timestamp_s for earlier, later in itertools.pairwise(still)]
    assert all(gap >= HEARTBEAT_S - 1e-6 for gap in gaps)
    assert all(record.motion_score == 0.0 for record in still)  # scored, and found still

    # Something moves: frames are admitted for the motion itself.
    motion = [record for record in moving if record.admission_reason == "motion"]
    assert len(motion) > MOVING_FRAMES // 2
    assert all(record.motion_score >= 3 for record in motion)


def test_each_admitted_live_frame_carries_its_causal_clip(tmp_path):
    _, publisher, still, moving = _run_still_then_moving(tmp_path)

    assert still and moving  # heartbeat admissions and motion admissions alike
    for record in publisher.records:
        # Pseudocode lines 7-8: W = Buffer.window([t - 2Δ, t]); forward(f_t, W).
        assert record.clip_end_s == record.timestamp_s
        assert record.clip_start_s == pytest.approx(record.timestamp_s - 2 * STRIDE_S)


def test_the_gate_counters_balance_exactly(tmp_path):
    worker, publisher, _still, _moving = _run_still_then_moving(tmp_path)

    assert worker.captured == worker.gated + worker.dropped
    assert worker.gated == worker.admitted + worker.discarded
    assert worker.admitted == worker.admitted_motion + worker.admitted_heartbeat
    by_reason = [record.admission_reason for record in publisher.records]
    assert worker.admitted_motion == by_reason.count("motion") > 0
    assert worker.admitted_heartbeat == by_reason.count("heartbeat") > 0
    assert worker.discarded == worker.gated - len(publisher.records) > 0
    assert worker.published == len(publisher.records)


def test_the_counters_still_balance_when_frames_are_dropped(tmp_path):
    # A queue of two on a stream delivered as fast as it can be read: most
    # frames never reach the gate.
    worker, publisher, _still, _moving = _run_still_then_moving(tmp_path, queue_size=2)

    assert worker.dropped > 0
    assert worker.captured == STILL_FRAMES + MOVING_FRAMES == worker.gated + worker.dropped
    assert worker.gated == worker.admitted + worker.discarded
    assert worker.published == worker.admitted == len(publisher.records)


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


def test_stopping_releases_the_stream_the_broker_connection_and_both_threads(tmp_path):
    clock = FakeClock()
    capture = FakeCapture(clock, pace_s=0.001)
    publisher = FakePublisher()
    worker = _worker(tmp_path, clock, capture, publisher)
    worker.start(WAIT_S)
    assert _until(lambda: worker.published > 0)

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
    _finish(worker)
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
    _finish(worker)

    assert worker.state is live.WorkerState.FAILED
    assert "broker refused" in worker.error
    assert capture.release_calls == 1 and publisher.closed == 1


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
    _finish(worker)

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
    assert _until(lambda: worker.reconnects == 1 and len(publisher.records) > 20 and len(publisher.events) == 2)

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
    assert worker.gated == worker.captured == worker.grabbed  # and every one was gated
    # One count across the gap: it carries on, it does not start again from zero
    # (the gate here admits every second frame, so not every index is stored).
    indexes = [record.frame_index for record in publisher.records]
    assert indexes == sorted(set(indexes))
    assert max(indexes) >= 25  # frames from after the gap are numbered on from before it


def test_a_stop_right_after_a_reconnection_opens_still_counts_the_frame_read_to_prove_it(tmp_path):
    """K-14, made deterministic: the worker is stopped in the instant between
    `_open_stream` reading its proving frame and the read loop taking it. That
    frame was delivered, so it is counted, decoded and gated like any other."""
    clock = FakeClock()
    publisher = FakePublisher()
    worker = None
    opened: list[FakeCapture] = []

    class StopsTheWorkerOnItsFirstFrame(FakeCapture):
        def grab(self):
            delivered = super().grab()
            worker._stop.set()  # what `stop()` does first, at this exact instant
            return delivered

    def open_capture():
        first = not opened
        capture = (FakeCapture(clock, frames=10) if first
                   else StopsTheWorkerOnItsFirstFrame(clock, frames=10))
        opened.append(capture)
        return capture

    worker = _worker(
        tmp_path, clock, type("Opener", (), {"open": staticmethod(open_capture)})(), publisher,
        backoff=live.Backoff(1.0, 30.0, jitter=0.0), wait=_fast_wait(clock),
    )

    worker.start(WAIT_S)
    assert _until(lambda: len(opened) == 2 and worker._capture_done.is_set())
    worker.stop(WAIT_S)

    assert [capture.delivered for capture in opened] == [10, 1]
    assert worker.grabbed == 11
    assert worker.gated == worker.captured == worker.grabbed


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


def test_the_broker_connection_is_kept_alive_while_the_worker_is_idle(tmp_path):
    clock = FakeClock()
    script = Script(clock, [{"frames": 10}, {"open_ok": False}])
    publisher = FakePublisher()
    worker = _worker(
        tmp_path, clock, script, publisher, backoff=live.Backoff(60.0, 60.0, jitter=0.0)
    )

    worker.start(WAIT_S)
    assert _until(lambda: worker.state is live.WorkerState.RECONNECTING)
    keepalives_at_the_drop = publisher.keepalives
    # A long backoff with nothing to publish: without this the broker would close
    # the connection on a worker that was merely waiting.
    assert _until(lambda: publisher.keepalives >= keepalives_at_the_drop + 3, timeout=3.0)
    worker.stop(WAIT_S)


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


# --- the bounded queue and dropped frames (OMNI-314) ------------------------------


def _flood(tmp_path, clock, publisher, *, queue_size, **extra):
    """A worker on a stream that goes on for ever and delivers far faster than
    a camera, so the processing side is easily outrun."""
    capture = FakeCapture(clock, pace_s=0.0005)
    return _worker(
        tmp_path, clock, capture, publisher, queue_size=queue_size, **extra
    )


def test_when_processing_stalls_frames_are_dropped_not_queued_without_limit(tmp_path):
    clock = FakeClock()
    stalled = threading.Event()  # the broker has stopped answering
    publisher = FakePublisher(block=stalled)
    worker = _flood(tmp_path, clock, publisher, queue_size=3)
    worker.start(WAIT_S)
    try:
        assert _until(lambda: worker.dropped >= 50)
        deepest = 0
        for _ in range(200):
            deepest = max(deepest, worker.snapshot()["queue_depth"])
            time.sleep(0.001)

        assert deepest <= 3  # the queue never grew past its bound...
        assert worker.dropped >= 50  # ...because the surplus was dropped...
        assert worker.published == 0  # ...while nothing could be published at all
    finally:
        stalled.set()
        worker.stop(WAIT_S)


def test_the_stream_keeps_being_read_while_processing_is_stuck(tmp_path):
    clock = FakeClock()
    stalled = threading.Event()
    worker = _flood(tmp_path, clock, FakePublisher(block=stalled), queue_size=2)
    worker.start(WAIT_S)
    try:
        assert _until(lambda: worker.grabbed >= 20)
        before = worker.grabbed
        time.sleep(0.2)
        # A capture that waited for the pipeline would have stopped here, and a
        # real stream would have started to lag behind real time.
        assert worker.grabbed > before + 20
    finally:
        stalled.set()
        worker.stop(WAIT_S)


def test_every_captured_frame_is_accounted_for_as_gated_or_dropped(tmp_path):
    clock = FakeClock()
    stalled = threading.Event()
    publisher = FakePublisher(block=stalled)
    worker = _flood(tmp_path, clock, publisher, queue_size=3)
    worker.start(WAIT_S)
    assert _until(lambda: worker.dropped >= 30)
    stalled.set()  # the broker comes back
    time.sleep(0.1)
    worker.stop(WAIT_S)

    # Nothing vanished without being counted.
    assert worker.captured == worker.gated + worker.dropped
    assert worker.gated == worker.admitted + worker.discarded
    assert worker.published == worker.admitted == len(publisher.records) > 0
    assert worker.dropped >= 30


def test_a_dropped_frame_does_not_disturb_the_frame_numbering(tmp_path):
    clock = FakeClock()
    stalled = threading.Event()
    publisher = FakePublisher(block=stalled)
    worker = _flood(tmp_path, clock, publisher, queue_size=3)
    worker.start(WAIT_S)
    assert _until(lambda: worker.dropped >= 30)
    stalled.set()
    time.sleep(0.1)
    worker.stop(WAIT_S)

    # A dropped frame takes no index: the gated frames are numbered 0, 1, 2...
    # with nothing missing, so the gate here (every second frame) admits exactly
    # the odd ones. Files are named by the index, so no two frames may share one.
    indexes = [record.frame_index for record in publisher.records]
    assert indexes == list(range(1, 2 * len(indexes), 2))
    assert all(Path(record.frame_path).is_file() for record in publisher.records)


def test_dropping_is_logged_once_per_stretch_and_summarised_not_once_per_frame(tmp_path, caplog):
    clock = FakeClock()
    stalled = threading.Event()
    worker = _flood(tmp_path, clock, FakePublisher(block=stalled), queue_size=1, drop_log_interval_s=1e9)
    with caplog.at_level(logging.WARNING, logger="app.live_capture"):
        worker.start(WAIT_S)
        try:
            assert _until(lambda: worker.dropped >= 100)
            lines = [r for r in caplog.records if r.message == "dropping frames: the pipeline is not keeping up"]
            # Hundreds of frames were dropped and it said so, but only once.
            assert len(lines) == 1
            fields = lines[0].extra_fields
            assert fields["camera_id"] == 7
            assert fields["reasons"] == {"processing": 1}
            assert lines[0].levelno == logging.WARNING
        finally:
            stalled.set()
            worker.stop(WAIT_S)


def test_a_continuing_stretch_of_drops_is_summarised_again_after_the_interval(tmp_path, caplog):
    clock = FakeClock()
    stalled = threading.Event()
    worker = _flood(tmp_path, clock, FakePublisher(block=stalled), queue_size=1, drop_log_interval_s=5.0)
    with caplog.at_level(logging.WARNING, logger="app.live_capture"):
        worker.start(WAIT_S)
        try:
            assert _until(lambda: worker.dropped >= 20)
            clock.now += 6.0  # the stretch has run on for longer than the interval
            before = worker.dropped
            assert _until(lambda: worker.dropped > before + 5)
            lines = [r for r in caplog.records if r.message == "dropping frames: the pipeline is not keeping up"]
            assert len(lines) >= 2
            assert lines[-1].extra_fields["dropped_since_last_report"] > 1
            assert lines[-1].extra_fields["dropped_total"] >= lines[0].extra_fields["dropped_total"]
        finally:
            stalled.set()
            worker.stop(WAIT_S)


def test_a_healthy_pipeline_drops_nothing_and_logs_nothing(tmp_path, caplog):
    clock = FakeClock()
    publisher = FakePublisher()
    # A stream paced in real time, so processing (which is quick) keeps up. An
    # instant fake stream would outrun it and drop frames, which is correct.
    capture = FakeCapture(clock, frames=200, pace_s=0.01)
    worker = _worker(tmp_path, clock, capture, publisher, queue_size=10)
    worker._backoff = live.Backoff(60, 60)
    with caplog.at_level(logging.WARNING, logger="app.live_capture"):
        worker.start(WAIT_S)
        assert _until(lambda: worker.grabbed == 200)
        worker.stop(WAIT_S)

    assert worker.dropped == 0
    assert worker.captured == worker.gated == 200
    assert not [r for r in caplog.records if "dropping" in r.message]


# --- the backlog limit ---------------------------------------------------------


def test_frames_are_dropped_rather_than_added_to_a_queue_that_is_already_too_deep(tmp_path):
    clock = FakeClock()
    publisher = FakePublisher(backlog=500)  # the consumer has fallen far behind
    worker = _worker(
        tmp_path, clock, FakeCapture(clock, frames=100), publisher,
        max_backlog=100, backlog_check_interval_s=0.0,
    )
    worker._backoff = live.Backoff(60, 60)

    worker.start(WAIT_S)
    assert _until(lambda: worker.grabbed == 100)
    worker.stop(WAIT_S)

    assert publisher.records == []  # nothing was added to the backlog
    assert worker.dropped == worker.dropped_backlog == worker.captured > 0


def test_publishing_resumes_once_the_backlog_has_drained(tmp_path):
    clock = FakeClock()
    publisher = FakePublisher(backlog=500)
    capture = FakeCapture(clock, pace_s=0.001)
    worker = _worker(
        tmp_path, clock, capture, publisher,
        max_backlog=100, backlog_check_interval_s=0.0,
    )
    worker.start(WAIT_S)
    try:
        assert _until(lambda: worker.dropped_backlog >= 10)
        assert publisher.records == []

        publisher.backlog_value = 10  # the consumer has caught up

        assert _until(lambda: len(publisher.records) >= 10)
    finally:
        worker.stop(WAIT_S)


def test_the_backlog_is_not_asked_for_on_every_frame(tmp_path):
    clock = FakeClock()
    publisher = FakePublisher(backlog=0)
    worker = _worker(
        tmp_path, clock, FakeCapture(clock, frames=200), publisher,
        max_backlog=100, backlog_check_interval_s=5.0,
    )
    worker._backoff = live.Backoff(60, 60)

    worker.start(WAIT_S)
    assert _until(lambda: worker.grabbed == 200)
    worker.stop(WAIT_S)

    assert worker.gated == 200 and len(publisher.records) == 100
    assert publisher.backlog_reads < 5  # a round trip per second at most, not one per frame


def test_without_a_limit_the_backlog_is_never_read(tmp_path):
    clock = FakeClock()
    publisher = FakePublisher(backlog=10**9)
    worker = _worker(tmp_path, clock, FakeCapture(clock, frames=50), publisher)
    worker._backoff = live.Backoff(60, 60)

    worker.start(WAIT_S)
    assert _until(lambda: worker.grabbed == 50)
    worker.stop(WAIT_S)

    assert publisher.backlog_reads == 0 and len(publisher.records) > 0


# --- stats reports and the effective rate -----------------------------------------


def test_running_totals_are_reported_periodically_and_are_cumulative(tmp_path):
    clock = FakeClock()
    publisher = FakePublisher()
    capture = FakeCapture(clock, pace_s=0.001)
    worker = _worker(tmp_path, clock, capture, publisher, stats_interval_s=0.05)
    worker.start(WAIT_S)
    try:
        assert _until(lambda: len(publisher.stats) >= 3)
        reports = list(publisher.stats)
    finally:
        worker.stop(WAIT_S)

    first = reports[0]
    assert first["camera_id"] == 7 and first["worker_id"] == worker.worker_id
    assert first["running"] is True and first["started_at"] == worker.started_at
    # Totals, not increments: each report can only be at or above the last.
    counters = ("captured", "dropped", "gated", "admitted_motion", "admitted_heartbeat", "discarded")
    for earlier, later in itertools.pairwise(reports):
        assert all(later[counter] >= earlier[counter] for counter in counters)
    assert reports[-1]["captured"] > reports[0]["captured"]
    assert reports[-1]["gated"] > reports[0]["gated"]
    # The gate's counters balance in every report, not only in the last one.
    for report in reports:
        assert report["gated"] == report["admitted_motion"] + report["admitted_heartbeat"] + report["discarded"]


def test_the_first_report_goes_out_at_once_not_after_a_full_interval(tmp_path):
    clock = FakeClock()
    publisher = FakePublisher()
    worker = _worker(
        tmp_path, clock, FakeCapture(clock, pace_s=0.001), publisher, stats_interval_s=1e9
    )
    worker.start(WAIT_S)
    try:
        # The interval is effectively infinite, so this can only be the first report.
        assert _until(lambda: len(publisher.stats) >= 1)
        assert publisher.stats[0]["running"] is True
        assert publisher.stats[0]["started_at"] == worker.started_at
    finally:
        worker.stop(WAIT_S)


def test_a_final_report_says_the_worker_stopped_and_carries_its_last_totals(tmp_path):
    clock = FakeClock()
    publisher = FakePublisher()
    worker = _worker(tmp_path, clock, FakeCapture(clock, pace_s=0.001), publisher, stats_interval_s=1e9)
    worker.start(WAIT_S)
    assert _until(lambda: worker.published > 5)

    worker.stop(WAIT_S)

    final = publisher.stats[-1]
    assert final["running"] is False
    assert final["captured"] == worker.captured
    assert final["dropped"] == worker.dropped
    # Sent after the queue was drained, so nothing is in flight and both hold exactly.
    assert final["captured"] == final["gated"] + final["dropped"]
    assert final["gated"] == final["admitted_motion"] + final["admitted_heartbeat"] + final["discarded"]
    assert (final["admitted_motion"], final["discarded"]) == (worker.admitted_motion, worker.discarded)


def test_the_final_report_carries_the_drops_too(tmp_path):
    clock = FakeClock()
    stalled = threading.Event()
    publisher = FakePublisher(block=stalled)
    worker = _flood(tmp_path, clock, publisher, queue_size=2, stats_interval_s=1e9)
    worker.start(WAIT_S)
    assert _until(lambda: worker.dropped >= 25)
    stalled.set()
    worker.stop(WAIT_S)

    final = publisher.stats[-1]
    assert final["running"] is False
    assert final["dropped"] == worker.dropped >= 25  # every drop reached `camera_stats`


def test_failing_to_report_stats_does_not_stop_the_capture(tmp_path):
    clock = FakeClock()
    publisher = FakePublisher(fail_stats=True)
    worker = _worker(tmp_path, clock, FakeCapture(clock, pace_s=0.001), publisher, stats_interval_s=0.02)
    worker.start(WAIT_S)
    try:
        assert _until(lambda: worker.published > 10)
        assert worker.state is live.WorkerState.RUNNING
    finally:
        worker.stop(WAIT_S)


def test_the_effective_rate_is_the_frames_actually_gated_per_second(tmp_path):
    clock = FakeClock()
    publisher = FakePublisher()
    # 250 frames of 25 fps is 10 s of stream, all of it inside the window. Every
    # frame is gated, so the rate is the stream's own: 25 a second, although
    # only half of them are admitted and published.
    worker = _worker(
        tmp_path, clock, FakeCapture(clock, frames=250, pace_s=0.002), publisher,
        fps_window_s=10.0,
    )
    worker._backoff = live.Backoff(60, 60)
    worker.start(WAIT_S)
    assert _until(lambda: worker.grabbed == 250 and worker.gated == 250)

    assert worker.published == 125
    assert worker.fps_effective() == pytest.approx(25.0, abs=0.5)
    worker.stop(WAIT_S)


def test_the_effective_rate_falls_when_frames_are_dropped(tmp_path):
    clock = FakeClock()
    stalled = threading.Event()
    worker = _flood(tmp_path, clock, FakePublisher(block=stalled), queue_size=2)
    worker.start(WAIT_S)
    try:
        assert _until(lambda: worker.dropped >= 20)
        clock.now += 30.0  # long enough for the window to hold nothing
        assert worker.fps_effective() == 0.0  # captured plenty, gated nothing recently
    finally:
        stalled.set()
        worker.stop(WAIT_S)


def test_uptime_runs_while_the_worker_lives_and_is_zero_once_it_has_stopped(tmp_path):
    clock = FakeClock()
    worker = _worker(tmp_path, clock, FakeCapture(clock, pace_s=0.001), FakePublisher())
    worker.start(WAIT_S)
    assert _until(lambda: worker.uptime_s() > 0.5)  # the fake clock moves with the frames

    worker.stop(WAIT_S)

    assert worker.uptime_s() == 0.0


def test_a_snapshot_carries_the_counters(tmp_path):
    clock = FakeClock()
    stalled = threading.Event()
    worker = _flood(tmp_path, clock, FakePublisher(block=stalled), queue_size=2)
    worker.start(WAIT_S)
    try:
        assert _until(lambda: worker.dropped >= 5)
        snapshot = worker.snapshot()
        assert snapshot["dropped"] >= 5 and snapshot["captured"] >= snapshot["dropped"]
        assert snapshot["queue_size"] == 2 and snapshot["queue_depth"] <= 2
        assert {"fps_effective", "uptime_s", "dropped_backlog", "published"} <= set(snapshot)
        assert {"gated", "admitted", "admitted_motion", "admitted_heartbeat", "discarded"} <= set(snapshot)
    finally:
        stalled.set()
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


def test_a_stream_that_drops_the_moment_after_its_first_frame_is_still_a_started_worker(tmp_path):
    registry = live.WorkerRegistry()
    clock = FakeClock()
    script = Script(clock, [{"frames": 1}, {"open_ok": False}])  # one frame, then nothing

    def factory():
        return _worker(tmp_path, clock, script, FakePublisher(), camera_id=7,
                       backoff=live.Backoff(60.0, 60.0, jitter=0.0))

    worker = registry.start(7, factory, WAIT_S)

    # Not mistaken for a start that failed, and stopped: it worked, and it is
    # now waiting to reconnect, which is what it should do.
    assert registry.get(7) is worker
    assert worker.alive
    assert worker.state in (live.WorkerState.RUNNING, live.WorkerState.RECONNECTING)
    registry.stop_all(WAIT_S)


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
