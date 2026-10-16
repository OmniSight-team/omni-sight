"""OMNI-303 (reworked): the frame pipeline decodes and gates every frame.

Runs against real video files written with OpenCV, no mocks. pipeline.py is
loaded by file path under its own name: ingestion and query both have a
top-level package called `app`, so a normal `import app.pipeline` would collide
with query's when both suites run in one pytest session. pipeline.py imports
nothing from `app.*` precisely so this works.

The original version of this file tested a sampling step (one frame every
`interval_s`) that no longer exists — Algorithm 1 has no sampling step, and
that step was the actual bug behind every CCD clip producing zero gated
frames (docs/context/week-03-04.md). This rewrite tests the replacement
directly: every decoded frame gets a segment row, and only admitted frames
get a JPEG. Whether a given frame *is* admitted is MotionGate's own logic,
covered in test_motion_gate.py — these tests use a fixed always/never-admit
gate wherever the admission decision itself doesn't matter, and only the
mechanics (file writing, row count, cleanup) do.
"""

import importlib.util
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
WIDTH, HEIGHT = 320, 180


class _AlwaysAdmitGate(pipeline.FrameGate):
    """A stand-in that admits every frame. Used where the test is about the
    pipeline's file-writing mechanics, not about whether a real motion
    decision was correct — that belongs to test_motion_gate.py."""

    def evaluate(self, frame, timestamp_s: float) -> "pipeline.GateDecision":
        return pipeline.GateDecision(
            motion_score=1.0, admitted=True, clip_start_s=max(0.0, timestamp_s - 1.0), clip_end_s=timestamp_s
        )


def _write_clip(path: Path, seconds: float, fps: int) -> int:
    """A clip with a moving square, so frames differ. Returns the frame count."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (WIDTH, HEIGHT))
    assert writer.isOpened()
    frames = round(seconds * fps)
    for i in range(frames):
        image = np.full((HEIGHT, WIDTH, 3), 40, dtype=np.uint8)
        x = (i * 3) % (WIDTH - 40)
        image[70:110, x : x + 40] = (0, 200, 255)
        writer.write(image)
    writer.release()
    return frames


@pytest.fixture(scope="module")
def four_second_30fps_clip(tmp_path_factory) -> tuple[Path, int]:
    """120 frames — used for tests about "every frame gets a row", where the
    exact fps and length don't otherwise matter."""
    path = tmp_path_factory.mktemp("clips") / "four_seconds_30fps.mp4"
    count = _write_clip(path, seconds=4, fps=30)
    return path, count


@pytest.fixture(scope="module")
def ccd_shaped_clip(tmp_path_factory) -> tuple[Path, int]:
    """5 seconds at 10 fps — the exact shape of a CCD clip, and the concrete
    case the rework note names: OMNI-303's acceptance criterion is that this
    yields 50 gated frames, not the 5 the old sampling step produced."""
    path = tmp_path_factory.mktemp("clips") / "ccd_shaped_5s_10fps.mp4"
    count = _write_clip(path, seconds=5, fps=10)
    return path, count


def _extract(clip: Path, out: Path, *, gate=None, video_id: int = 7, **overrides):
    args = {
        "source_type": "upload",
        "video_id": video_id,
        "camera_id": None,
        "frames_dir": out / "frames" / str(video_id),
        "thumbs_dir": out / "thumbs" / str(video_id),
        "gate": gate,
        **SETTINGS,
    }
    args.update(overrides)
    return pipeline.extract_file(str(clip), **args)


def test_every_decoded_frame_gets_exactly_one_segment_row(four_second_30fps_clip, tmp_path):
    clip, frame_count = four_second_30fps_clip

    records = _extract(clip, tmp_path, gate=_AlwaysAdmitGate())

    assert len(records) == frame_count == 120
    assert [r.frame_index for r in records[:3]] == [0, 1, 2]
    assert [round(r.timestamp_s, 3) for r in records[:3]] == [0.0, round(1 / 30, 3), round(2 / 30, 3)]
    assert records[-1].frame_index == frame_count - 1


def test_the_ccd_acceptance_case_50_gated_frames_not_5(ccd_shaped_clip, tmp_path):
    """The literal number from OMNI-303's rework note and acceptance
    criterion. The original, sampling-based implementation produced 5 rows
    for this exact clip shape — none of which ever got scored, because a
    5-sample clip could never fill a 5-frame warm-up buffer."""
    clip, frame_count = ccd_shaped_clip

    records = _extract(clip, tmp_path, gate=_AlwaysAdmitGate())

    assert frame_count == 50
    assert len(records) == 50


def test_only_admitted_frames_get_a_jpeg_written_the_rest_get_no_path_and_no_file(tmp_path):
    class _AdmitEveryOther(pipeline.FrameGate):
        def evaluate(self, frame, timestamp_s):
            admitted = round(timestamp_s * 30) % 2 == 0
            return pipeline.GateDecision(motion_score=0.0, admitted=admitted)

    path = tmp_path / "clip.mp4"
    _write_clip(path, seconds=1, fps=30)  # 30 frames

    records = _extract(path, tmp_path, gate=_AdmitEveryOther())

    assert len(records) == 30
    admitted = [r for r in records if r.admitted]
    discarded = [r for r in records if not r.admitted]
    assert len(admitted) == 15 and len(discarded) == 15

    for record in admitted:
        assert record.frame_path is not None and record.thumb_path is not None
        assert Path(record.frame_path).is_file()
        assert Path(record.thumb_path).is_file()
        # OMNI-610: the bytes the two files take, for the dashboard's storage figure.
        assert record.file_bytes == (
            Path(record.frame_path).stat().st_size + Path(record.thumb_path).stat().st_size
        )

    for record in discarded:
        assert record.frame_path is None
        assert record.thumb_path is None
        assert record.file_bytes == 0

    # exactly one file per admitted frame — nothing extra left on disk
    assert len(list((tmp_path / "frames" / "7").iterdir())) == 15
    assert len(list((tmp_path / "thumbs" / "7").iterdir())) == 15


def test_a_row_is_still_written_for_a_discarded_frame_with_its_score(tmp_path):
    class _NeverAdmit(pipeline.FrameGate):
        def evaluate(self, frame, timestamp_s):
            return pipeline.GateDecision(motion_score=0.0, admitted=False)

    path = tmp_path / "clip.mp4"
    _write_clip(path, seconds=0.5, fps=10)  # 5 frames

    records = _extract(path, tmp_path, gate=_NeverAdmit())

    assert len(records) == 5
    assert all(r.admitted is False for r in records)
    assert all(r.motion_score == 0.0 for r in records)  # stored, not dropped
    assert all(r.frame_path is None and r.thumb_path is None for r in records)
    assert not (tmp_path / "frames" / "7").exists() or not list((tmp_path / "frames" / "7").iterdir())


def test_with_no_gate_given_every_frame_is_unscored_and_none_are_admitted(tmp_path):
    """extract_file's own default (FrameGate, the placeholder) when no real
    gate is passed — still a real code path, exercised directly rather than
    only ever through MotionGate."""
    path = tmp_path / "clip.mp4"
    _write_clip(path, seconds=0.5, fps=10)

    records = _extract(path, tmp_path)  # gate=None

    assert len(records) == 5
    assert all(r.motion_score is None and r.admitted is False for r in records)
    assert all(r.frame_path is None for r in records)


def test_an_admitted_thumbnail_is_readable_scaled_and_lighter_than_the_frame(tmp_path):
    path = tmp_path / "clip.mp4"
    _write_clip(path, seconds=0.2, fps=10)  # 2 frames

    records = _extract(path, tmp_path, gate=_AlwaysAdmitGate())

    for record in records:
        thumb = cv2.imread(record.thumb_path)
        assert thumb is not None
        assert thumb.shape[1] == SETTINGS["thumb_width"]
        frame = cv2.imread(record.frame_path)
        assert frame is not None
        assert frame.shape[:2] == (HEIGHT, WIDTH)
        assert Path(record.thumb_path).stat().st_size < Path(record.frame_path).stat().st_size


def test_a_small_frame_is_not_upscaled_for_its_thumbnail(tmp_path):
    frames_dir, thumbs_dir = tmp_path / "f", tmp_path / "t"
    frames_dir.mkdir()
    thumbs_dir.mkdir()
    frame = np.full((60, 100, 3), 90, dtype=np.uint8)

    record = pipeline.process_frame(
        frame,
        pipeline.FrameSource(source_type="upload", frame_index=0, timestamp_s=0.0, video_id=1),
        _AlwaysAdmitGate(),
        frames_dir,
        thumbs_dir,
        **SETTINGS,
    )

    assert cv2.imread(record.thumb_path).shape[:2] == (60, 100)


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
        _AlwaysAdmitGate(),
        frames_dir,
        thumbs_dir,
        **SETTINGS,
    )

    assert (record.source_type, record.video_id, record.camera_id) == ("camera", None, 3)
    assert record.frame_index == 42
    assert Path(record.frame_path).name == "000042.jpg"


def test_rerunning_replaces_rows_and_admitted_files_instead_of_adding_to_them(tmp_path):
    path = tmp_path / "clip.mp4"
    _write_clip(path, seconds=1, fps=10)  # 10 frames

    _extract(path, tmp_path, gate=_AlwaysAdmitGate())
    assert len(list((tmp_path / "frames" / "7").iterdir())) == 10

    class _AdmitNone(pipeline.FrameGate):
        def evaluate(self, frame, timestamp_s):
            return pipeline.GateDecision(motion_score=0.0, admitted=False)

    second = _extract(path, tmp_path, gate=_AdmitNone())

    assert len(second) == 10  # still one row per decoded frame
    assert all(r.frame_path is None for r in second)
    assert list((tmp_path / "frames" / "7").iterdir()) == []  # the old JPEGs are gone
    assert list((tmp_path / "thumbs" / "7").iterdir()) == []


def test_a_failure_part_way_through_leaves_no_files_and_names_the_reason(tmp_path):
    class _ExplodingGate(pipeline.FrameGate):
        def __init__(self):
            self.calls = 0

        def evaluate(self, frame, timestamp_s):
            self.calls += 1
            if self.calls == 5:
                raise RuntimeError("gate blew up")
            return pipeline.GateDecision(motion_score=1.0, admitted=True, clip_start_s=0.0, clip_end_s=timestamp_s)

    path = tmp_path / "clip.mp4"
    _write_clip(path, seconds=2, fps=10)  # 20 frames, plenty past call 5

    with pytest.raises(pipeline.ExtractError) as excinfo:
        _extract(path, tmp_path, gate=_ExplodingGate())

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
