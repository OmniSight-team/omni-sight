"""OMNI-507 (K-13): a worker is `receiving` only while frames arrive steadily.

A stalled stream can still hand over a late burst of old frames; the camera
wall must not read that as a live camera. The rule is tested on its own with a
fake clock, then on a worker reading the scripted fake stream.
"""

import importlib.util
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
TESTS = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


live_tests = _load("omnisight_ingestion_live_tests_for_receiving", TESTS / "test_live_capture.py")
live = live_tests.live
FakeClock, FakeCapture, FakePublisher = live_tests.FakeClock, live_tests.FakeCapture, live_tests.FakePublisher
WAIT_S = live_tests.WAIT_S


def _idle_worker(tmp_path, clock, **extra):
    """A worker that is never started: the arrivals are written by the test."""
    return live_tests._worker(tmp_path, clock, FakeCapture(clock), FakePublisher(), **extra)


def _arrive(worker, clock, *offsets):
    for offset in offsets:
        worker._arrivals.append(clock.now + offset)


def test_frames_spread_over_the_window_are_receiving(tmp_path):
    clock = FakeClock()
    worker = _idle_worker(tmp_path, clock)
    _arrive(worker, clock, *[-2.5 + i / 15 for i in range(38)])  # 2.5 s of a 15 fps stream

    assert worker.receiving() is True


def test_a_burst_of_frames_landing_together_is_not(tmp_path):
    clock = FakeClock()
    worker = _idle_worker(tmp_path, clock)
    _arrive(worker, clock, *[-0.05 + i * 0.005 for i in range(9)])  # nine frames within 50 ms

    assert worker.receiving() is False


def test_one_frame_is_not(tmp_path):
    clock = FakeClock()
    worker = _idle_worker(tmp_path, clock)
    _arrive(worker, clock, -0.1)

    assert worker.receiving() is False


def test_two_bursts_further_apart_than_the_window_are_not(tmp_path):
    """What a paused simulator delivered: one frame, then nine, ten seconds apart."""
    clock = FakeClock()
    worker = _idle_worker(tmp_path, clock)
    _arrive(worker, clock, -10.0, *[-0.05 + i * 0.005 for i in range(9)])

    assert worker.receiving() is False


def test_a_slow_camera_still_counts(tmp_path):
    clock = FakeClock()
    worker = _idle_worker(tmp_path, clock)
    _arrive(worker, clock, -2.0, -1.0, 0.0)  # one frame a second

    assert worker.receiving() is True


def test_receiving_ends_once_frames_stop(tmp_path):
    clock = FakeClock()
    worker = _idle_worker(tmp_path, clock)
    _arrive(worker, clock, *[-2.5 + i / 15 for i in range(38)])
    assert worker.receiving() is True

    clock.now += 3.1  # nothing more for longer than the window

    assert worker.receiving() is False


def test_a_reading_worker_on_a_steady_stream_reports_receiving(tmp_path):
    clock = FakeClock()
    capture = FakeCapture(clock, pace_s=0.001)  # 25 fps of fake time
    worker = live_tests._worker(tmp_path, clock, capture, FakePublisher())
    worker.start(WAIT_S)
    try:
        assert live_tests._until(lambda: worker.grabbed > 60)  # more than two seconds of stream
        snapshot = worker.snapshot()
        assert snapshot["status"] == "running" and snapshot["receiving"] is True
    finally:
        worker.stop(WAIT_S)

    assert worker.snapshot()["receiving"] is False  # a stopped worker never is


def test_the_record_of_arrivals_stays_short(tmp_path):
    clock = FakeClock()
    capture = FakeCapture(clock, frames=500)  # 20 s of a 25 fps stream
    worker = live_tests._worker(tmp_path, clock, capture, FakePublisher())
    worker._backoff = live.Backoff(60, 60)
    worker.start(WAIT_S)
    assert live_tests._until(lambda: worker.grabbed == 500)
    worker.stop(WAIT_S)

    # Only the last few seconds are kept, not every frame since the start.
    assert len(worker._arrivals) <= 3.0 * 25 + 1
