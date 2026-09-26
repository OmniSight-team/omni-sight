"""OMNI-312: the live capture worker.

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
    None means it goes on until released. `pace_s` slows each read in real time
    so a worker that is meant to run "forever" does not spin.
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


class FakePublisher:
    def __init__(self, fail_after=None):
        self.records = []
        self.closed = 0
        self._fail_after = fail_after

    def publish(self, record):
        if self._fail_after is not None and len(self.records) >= self._fail_after:
            raise RuntimeError("broker refused the message")
        self.records.append(record)

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


def _worker(tmp_path, clock, capture, publisher, *, camera_id=7, interval=0.19, process=None):
    gate = _EveryOtherGate()
    frames_dir, thumbs_dir = tmp_path / "frames", tmp_path / "thumbs"
    frames_dir.mkdir(exist_ok=True)
    thumbs_dir.mkdir(exist_ok=True)

    def real_process(frame, timestamp_s, index):
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

    return live.LiveWorker(
        camera_id,
        open_capture=lambda: capture,
        make_publisher=lambda: publisher,
        process=process or real_process,
        sample_interval_s=interval,
        clock=clock,
    )


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

    _run_to_the_end(worker)

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

    _run_to_the_end(worker)

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

    _run_to_the_end(worker)

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


def test_a_stream_that_cannot_be_opened_fails_and_releases_what_it_touched(tmp_path):
    clock = FakeClock()
    capture = FakeCapture(clock, open_ok=False)
    publisher = FakePublisher()
    worker = _worker(tmp_path, clock, capture, publisher)

    assert worker.start(WAIT_S) is live.WorkerState.FAILED

    assert worker.error == "could not open the stream"
    assert capture.release_calls == 1
    assert publisher.records == [] and publisher.closed == 0  # never connected


def test_a_stream_that_drops_stops_the_worker_cleanly_and_says_why(tmp_path):
    clock = FakeClock()
    capture = FakeCapture(clock, frames=30)
    publisher = FakePublisher()
    worker = _worker(tmp_path, clock, capture, publisher)

    _run_to_the_end(worker)

    assert worker.state is live.WorkerState.FAILED
    assert "stopped delivering frames" in worker.error
    assert capture.release_calls == 1 and publisher.closed == 1
    assert publisher.records  # what was accepted before the drop was published


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

    def explode(frame, timestamp_s, index):
        raise ValueError("the gate blew up")

    worker = _worker(tmp_path, clock, capture, publisher, process=explode)
    worker.start(WAIT_S)
    worker._thread.join(WAIT_S)

    assert worker.state is live.WorkerState.FAILED
    assert capture.release_calls == 1 and publisher.closed == 1


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
