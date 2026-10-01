"""OMNI-503: the preview file a camera wall polls, and how the live worker
keeps it.

The writer is tested on real files; the worker with the same scripted fake
stream and fake clock as test_live_capture.py. Query's side (the token, the
ETag, the 304) is in services/query/tests/test_camera_capture.py.
"""

import importlib.util
import sys
import threading
from pathlib import Path

import cv2
import numpy as np
import pytest

APP = Path(__file__).resolve().parents[1] / "app"
TESTS = Path(__file__).resolve().parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preview = _load("omnisight_ingestion_preview", APP / "preview.py")
live_tests = _load("omnisight_ingestion_live_tests_for_preview", TESTS / "test_live_capture.py")
live = live_tests.live
FakeClock, FakeCapture, FakePublisher = live_tests.FakeClock, live_tests.FakeCapture, live_tests.FakePublisher
WAIT_S = live_tests.WAIT_S


def _frame(height, width):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, : width // 2] = (0, 128, 255)
    return frame


# --- the writer -----------------------------------------------------------------


def test_the_preview_is_a_jpeg_with_its_longest_side_capped(tmp_path):
    writer = preview.PreviewWriter(tmp_path / "camera-7.jpg", max_side_px=640, quality=70)

    writer.write(_frame(720, 1280))

    image = cv2.imread(str(tmp_path / "camera-7.jpg"))
    assert image.shape[:2] == (360, 640)  # 1280x720 scaled to fit 640, proportions kept


def test_a_tall_frame_is_capped_on_its_height(tmp_path):
    writer = preview.PreviewWriter(tmp_path / "camera-7.jpg", max_side_px=640, quality=70)

    writer.write(_frame(1280, 720))

    assert cv2.imread(str(tmp_path / "camera-7.jpg")).shape[:2] == (640, 360)


def test_a_small_frame_is_never_scaled_up(tmp_path):
    writer = preview.PreviewWriter(tmp_path / "camera-7.jpg", max_side_px=640, quality=70)

    writer.write(_frame(240, 320))

    assert cv2.imread(str(tmp_path / "camera-7.jpg")).shape[:2] == (240, 320)


def test_each_write_replaces_the_one_file_and_leaves_nothing_else(tmp_path):
    writer = preview.PreviewWriter(tmp_path / "camera-7.jpg", max_side_px=640, quality=70)

    for _ in range(5):
        writer.write(_frame(240, 320))

    assert [path.name for path in tmp_path.iterdir()] == ["camera-7.jpg"]  # no temp file, no history


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows refuses to rename over a file another handle has open; the "
    "service runs on Linux, where this holds (run it in the ingestion container)",
)
def test_a_reader_never_sees_half_a_file(tmp_path):
    """Replaced by renaming a finished file over the old one, so every read in
    the middle of a stream of writes is a whole, decodable image."""
    writer = preview.PreviewWriter(tmp_path / "camera-7.jpg", max_side_px=640, quality=95)
    writer.write(_frame(720, 1280))
    stop = threading.Event()

    def keep_writing():
        noise = np.random.default_rng(1)
        while not stop.is_set():
            writer.write(noise.integers(0, 255, (720, 1280, 3), dtype=np.uint8))

    thread = threading.Thread(target=keep_writing)
    thread.start()
    try:
        bad = 0
        for _ in range(200):
            data = (tmp_path / "camera-7.jpg").read_bytes()
            image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if image is None or not data.endswith(b"\xff\xd9"):
                bad += 1
    finally:
        stop.set()
        thread.join(WAIT_S)
    assert bad == 0


def test_clear_removes_the_preview(tmp_path):
    writer = preview.PreviewWriter(tmp_path / "camera-7.jpg", max_side_px=640, quality=70)
    writer.write(_frame(240, 320))

    writer.clear()
    writer.clear()  # and clearing twice is harmless

    assert list(tmp_path.iterdir()) == []


def test_the_path_is_one_file_per_camera():
    assert preview.preview_path("/data/previews", 7) == Path("/data/previews/camera-7.jpg")


# --- the worker keeps it ------------------------------------------------------------


class RecordingPreview:
    def __init__(self, fail=False):
        self.writes: list[float] = []  # the fake clock's time at each write
        self.cleared = 0
        self.fail = fail
        self.clock = None

    def write(self, frame):
        if self.fail:
            raise OSError("disk full")
        self.writes.append(self.clock())

    def clear(self):
        self.cleared += 1


def _worker(tmp_path, clock, capture, recorder, **extra):
    recorder.clock = clock
    worker = live_tests._worker(
        tmp_path, clock, capture, FakePublisher(), preview=recorder, preview_interval_s=0.5, **extra
    )
    worker._backoff = live.Backoff(60, 60)
    return worker


def test_the_worker_writes_the_preview_at_most_every_interval(tmp_path):
    clock = FakeClock()
    recorder = RecordingPreview()
    # 100 frames of a 25 fps camera: four seconds.
    worker = _worker(tmp_path, clock, FakeCapture(clock, frames=100), recorder)

    worker.start(WAIT_S)
    assert live_tests._until(lambda: worker.grabbed == 100)
    worker.stop(WAIT_S)

    gaps = [later - earlier for earlier, later in zip(recorder.writes, recorder.writes[1:], strict=False)]
    assert all(gap >= 0.5 - 1e-9 for gap in gaps)  # never more often than the interval
    assert 7 <= len(recorder.writes) <= 8  # and as often as it allows: about twice a second
    assert worker.previews_written == len(recorder.writes)


def test_the_preview_shows_frames_the_gate_discards_too(tmp_path):
    """The gate in these tests admits every second frame; the preview does not
    care which, it is the camera's current picture."""
    clock = FakeClock()
    recorder = RecordingPreview()
    worker = _worker(tmp_path, clock, FakeCapture(clock, frames=100), recorder)

    worker.start(WAIT_S)
    assert live_tests._until(lambda: worker.grabbed == 100)
    worker.stop(WAIT_S)

    # Half the frames were discarded, yet the preview kept its own pace: it is
    # written from the capture side, before the gate, not from what is published.
    assert worker.discarded == 50 and worker.published == 50
    assert 7 <= worker.previews_written <= 8


def test_the_preview_is_removed_when_the_worker_stops(tmp_path):
    clock = FakeClock()
    recorder = RecordingPreview()
    worker = _worker(tmp_path, clock, FakeCapture(clock, pace_s=0.001), recorder)
    worker.start(WAIT_S)
    assert live_tests._until(lambda: worker.previews_written > 0)

    worker.stop(WAIT_S)

    assert recorder.cleared == 1  # a stopped camera must not keep showing its last frame


def test_a_worker_that_fails_to_start_leaves_no_preview(tmp_path):
    clock = FakeClock()
    recorder = RecordingPreview()
    worker = _worker(tmp_path, clock, FakeCapture(clock, open_ok=False), recorder)

    assert worker.start(WAIT_S) is live.WorkerState.FAILED
    live_tests._finish(worker)

    assert recorder.writes == [] and recorder.cleared == 1


def test_a_preview_that_cannot_be_written_does_not_stop_the_capture(tmp_path):
    clock = FakeClock()
    recorder = RecordingPreview(fail=True)
    worker = _worker(tmp_path, clock, FakeCapture(clock, frames=100), recorder)

    worker.start(WAIT_S)
    assert live_tests._until(lambda: worker.grabbed == 100)
    worker.stop(WAIT_S)

    assert worker.gated == 100  # every frame still gated
    assert worker.preview_errors > 0 and worker.previews_written == 0
    assert worker.state is live.WorkerState.STOPPED


def test_a_worker_without_a_preview_works_as_before(tmp_path):
    clock = FakeClock()
    worker = live_tests._worker(tmp_path, clock, FakeCapture(clock, frames=30), FakePublisher())
    worker._backoff = live.Backoff(60, 60)

    worker.start(WAIT_S)
    assert live_tests._until(lambda: worker.grabbed == 30)
    worker.stop(WAIT_S)

    assert worker.gated == 30 and worker.previews_written == 0


def test_the_worker_snapshot_says_when_the_preview_was_last_written(tmp_path):
    clock = FakeClock()
    recorder = RecordingPreview()
    worker = _worker(tmp_path, clock, FakeCapture(clock, pace_s=0.001), recorder)
    worker.start(WAIT_S)
    try:
        assert live_tests._until(lambda: worker.previews_written >= 2)
        snapshot = worker.snapshot()
        assert snapshot["previews_written"] >= 2 and snapshot["preview_errors"] == 0
        assert snapshot["last_preview_at"] is not None
    finally:
        worker.stop(WAIT_S)
