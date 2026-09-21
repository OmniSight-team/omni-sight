"""OMNI-303: the frame pipeline (process_frame and file extraction).

Runs against real video files written with OpenCV, no mocks. pipeline.py is
loaded by file path under its own name: ingestion and query both have a
top-level package called `app`, so a normal `import app.pipeline` would collide
with query's when both suites run in one pytest session. pipeline.py imports
nothing from `app.*` precisely so this works.
"""

import importlib.util
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

_spec = importlib.util.spec_from_file_location(
    "omnisight_ingestion_pipeline",
    Path(__file__).resolve().parents[1] / "app" / "pipeline.py",
)
pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pipeline)

SETTINGS = {"thumb_width": 160, "frame_quality": 85, "thumb_quality": 70}
FPS = 10
WIDTH, HEIGHT = 320, 180


def _write_clip(path: Path, seconds: int, fps: int = FPS) -> int:
    """A clip with a moving square, so frames differ. Returns the frame count."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (WIDTH, HEIGHT))
    assert writer.isOpened()
    frames = seconds * fps
    for i in range(frames):
        image = np.full((HEIGHT, WIDTH, 3), 40, dtype=np.uint8)
        x = (i * 3) % (WIDTH - 40)
        image[70:110, x : x + 40] = (0, 200, 255)
        writer.write(image)
    writer.release()
    return frames


@pytest.fixture(scope="module")
def two_minute_clip(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("clips") / "two_minutes.mp4"
    assert _write_clip(path, 120) == 1200
    return path


def _extract(clip: Path, out: Path, interval_s: float = 1.0, **overrides):
    args = {
        "source_type": "upload",
        "video_id": 7,
        "camera_id": None,
        "interval_s": interval_s,
        "frames_dir": out / "frames" / "7",
        "thumbs_dir": out / "thumbs" / "7",
        **SETTINGS,
    }
    args.update(overrides)
    return pipeline.extract_file(str(clip), **args)


def test_a_two_minute_clip_yields_one_segment_per_second_each_with_a_readable_thumbnail(
    two_minute_clip, tmp_path
):
    records = _extract(two_minute_clip, tmp_path)

    assert len(records) == 120
    assert [r.frame_index for r in records[:3]] == [0, 10, 20]
    assert [r.timestamp_s for r in records[:3]] == [0.0, 1.0, 2.0]
    assert records[-1].timestamp_s == 119.0

    for record in records:
        thumb = cv2.imread(record.thumb_path)
        assert thumb is not None, record.thumb_path
        assert thumb.shape[1] == SETTINGS["thumb_width"]
        frame = cv2.imread(record.frame_path)
        assert frame is not None
        assert frame.shape[:2] == (HEIGHT, WIDTH)

    assert Path(records[0].frame_path).parent == tmp_path / "frames" / "7"
    assert Path(records[0].thumb_path).parent == tmp_path / "thumbs" / "7"
    # thumbnails are what a grid of two hundred loads, so they must be lighter
    assert Path(records[0].thumb_path).stat().st_size < Path(records[0].frame_path).stat().st_size


@pytest.mark.parametrize("interval_s", [0.5, 2.5, 7.0])
def test_the_interval_setting_sets_how_many_segments_come_out(two_minute_clip, tmp_path, interval_s):
    records = _extract(two_minute_clip, tmp_path, interval_s=interval_s)

    step = interval_s * FPS
    assert len(records) == math.ceil(1200 / step)


def test_an_interval_shorter_than_one_frame_still_moves_on(two_minute_clip, tmp_path):
    records = _extract(two_minute_clip, tmp_path, interval_s=0.01)

    assert len(records) == 1200
    assert [r.frame_index for r in records[:3]] == [0, 1, 2]


def test_rerunning_replaces_the_files_instead_of_adding_to_them(two_minute_clip, tmp_path):
    _extract(two_minute_clip, tmp_path, interval_s=1.0)
    second = _extract(two_minute_clip, tmp_path, interval_s=10.0)

    assert len(second) == 12
    assert len(list((tmp_path / "frames" / "7").iterdir())) == 12
    assert len(list((tmp_path / "thumbs" / "7").iterdir())) == 12


def test_process_frame_does_not_care_where_a_frame_came_from(tmp_path):
    """A live frame: a camera, no video, a frame that never came from a file."""
    frame = np.full((360, 640, 3), 90, dtype=np.uint8)
    frames_dir, thumbs_dir = tmp_path / "f", tmp_path / "t"
    frames_dir.mkdir()
    thumbs_dir.mkdir()

    record = pipeline.process_frame(
        frame,
        pipeline.FrameSource(
            source_type="camera", frame_index=42, timestamp_s=4.2, video_id=None, camera_id=3
        ),
        pipeline.FrameGate(),
        frames_dir,
        thumbs_dir,
        **SETTINGS,
    )

    assert (record.source_type, record.video_id, record.camera_id) == ("camera", None, 3)
    assert record.frame_index == 42
    assert Path(record.frame_path).name == "000042.jpg"
    thumb = cv2.imread(record.thumb_path)
    assert thumb.shape[:2] == (90, 160)  # 640x360 scaled to width 160, aspect kept


def test_a_small_frame_is_not_upscaled_for_its_thumbnail(tmp_path):
    frame = np.full((60, 100, 3), 90, dtype=np.uint8)
    (tmp_path / "f").mkdir()
    (tmp_path / "t").mkdir()

    record = pipeline.process_frame(
        frame,
        pipeline.FrameSource(source_type="upload", frame_index=0, timestamp_s=0.0, video_id=1),
        pipeline.FrameGate(),
        tmp_path / "f",
        tmp_path / "t",
        **SETTINGS,
    )

    assert cv2.imread(record.thumb_path).shape[:2] == (60, 100)


def test_until_the_motion_gate_exists_nothing_is_scored_or_admitted(two_minute_clip, tmp_path):
    records = _extract(two_minute_clip, tmp_path, interval_s=30.0)

    assert all(r.motion_score is None and r.admitted is False for r in records)


def test_a_failure_part_way_through_leaves_no_files_and_names_the_reason(two_minute_clip, tmp_path):
    class ExplodingGate(pipeline.FrameGate):
        def __init__(self):
            self.calls = 0

        def evaluate(self, frame):
            self.calls += 1
            if self.calls == 5:
                raise RuntimeError("gate blew up")
            return super().evaluate(frame)

    with pytest.raises(pipeline.ExtractError) as excinfo:
        _extract(two_minute_clip, tmp_path, gate=ExplodingGate())

    assert "gate blew up" in excinfo.value.reason
    assert not (tmp_path / "frames" / "7").exists()
    assert not (tmp_path / "thumbs" / "7").exists()


def test_a_missing_file_is_a_clean_failure(tmp_path):
    with pytest.raises(pipeline.ExtractError) as excinfo:
        _extract(tmp_path / "nope.mp4", tmp_path)

    assert excinfo.value.reason == "file not found"


def test_a_file_that_is_not_a_video_is_a_clean_failure(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"this is not a video" * 100)

    with pytest.raises(pipeline.ExtractError) as excinfo:
        _extract(junk, tmp_path)

    assert excinfo.value.reason == "could not open file"
    assert not (tmp_path / "frames" / "7").exists()
