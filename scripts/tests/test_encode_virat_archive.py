"""OMNI-708: the archive runner, with stand-in encoders (no model, no GPU).

The gate, the decoding and the clip windows are the real code; the encoders are replaced by
stand-ins that check what they are given and return unit vectors of the right size.
"""

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path, package: bool = False):
    kwargs = {"submodule_search_locations": [str(path.parent)]} if package else {}
    spec = importlib.util.spec_from_file_location(name, path, **kwargs)
    module = importlib.util.module_from_spec(spec)
    importlib.sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


archive = _load("encode_virat_archive", ROOT / "scripts" / "encode_virat_archive.py")
_load("omnisight_ai_workers_app", ROOT / "services" / "ai_workers" / "app" / "__init__.py", package=True)
clip_encoder = importlib.import_module("omnisight_ai_workers_app.clip_encoder")
pipeline, SETTINGS = archive.load_gate(ROOT)
PINS = {"frame": "test", "clip": "test"}


def _unit(seed: bytes, dim: int) -> np.ndarray:
    v = np.random.default_rng(int.from_bytes(hashlib.sha256(seed).digest()[:8], "little")).standard_normal(dim)
    return (v / np.linalg.norm(v)).astype(np.float32)


class FrameStandIn:
    def __init__(self):
        self.paths = []

    def encode_images(self, paths):
        self.paths += [str(p) for p in paths]
        return np.stack([_unit(Path(p).read_bytes(), 1152) for p in paths])


class ClipStandIn:
    def __init__(self):
        self.clips = []

    def encode_clips(self, clips):
        for frames in clips:
            assert len(frames) == 8 and all(f.ndim == 3 and f.shape[2] == 3 for f in frames)
        self.clips += [[int(f[0, 0, 0]) for f in frames] for frames in clips]
        return np.stack([_unit(np.stack(frames).tobytes(), 512) for frames in clips])


def _video(path: Path, seconds: float = 4.0, fps: float = 30.0) -> Path:
    """A square that moves for the second half; each frame's top-left pixel is its index
    (mod 256), so a clip's frames can be read back from the stand-in."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (320, 240))
    for i in range(int(seconds * fps)):
        frame = np.full((240, 320, 3), 40, np.uint8)
        x = 20 if i < seconds * fps / 2 else 20 + 6 * (i - int(seconds * fps / 2))
        frame[80:160, x % 240 : x % 240 + 80] = 220
        frame[0:8, 0:8] = i % 256
        writer.write(frame)
    writer.release()
    return path


@pytest.fixture
def video(tmp_path):
    return _video(tmp_path / "VIRAT_TEST_A.avi")


def _gate_count(path: Path):
    """What ingestion's own extraction keeps from the same file."""
    gate = archive.new_gate(pipeline, SETTINGS)
    capture = cv2.VideoCapture(str(path))
    fps, i, kept = capture.get(cv2.CAP_PROP_FPS), -1, []
    while capture.grab():
        i += 1
        _, frame = capture.retrieve()
        if gate.evaluate(frame, i / fps).admitted:
            kept.append(i)
    return i + 1, kept


def test_every_admitted_frame_gets_both_vectors_and_the_same_frames_as_the_gate(video, tmp_path):
    frames, clips = FrameStandIn(), ClipStandIn()

    result = archive.encode_video(video, pipeline, SETTINGS, frames, clip_encoder, clips, tmp_path / "scratch")

    decoded, kept = _gate_count(video)
    assert int(result["frames_decoded"]) == decoded
    assert result["frame_index"].tolist() == kept and len(kept) > 0
    assert set(result["admission_reason"]) <= {"motion", "heartbeat"}
    assert result["frame_vectors"].shape == (len(kept), 1152)
    assert result["clip_vectors"].shape == (len(kept), 512)
    assert len(frames.paths) == len(kept)
    assert not (tmp_path / "scratch").exists()


def test_each_clip_is_eight_frames_of_its_own_window_in_order(video, tmp_path):
    clips = ClipStandIn()

    result = archive.encode_video(video, pipeline, SETTINGS, FrameStandIn(), clip_encoder, clips, tmp_path / "s")

    fps = float(result["fps"])
    for row, read in enumerate(clips.clips):
        first, last = clip_encoder.window_span(result["clip_start_s"][row], result["clip_end_s"][row], fps)
        expected = [i % 256 for i in clip_encoder.uniform_indices(first, last)]
        # MJPG is lossy: the 8 x 8 block's value comes back within a few levels.
        assert np.allclose(read, expected, atol=4), (row, read, expected)
        assert last == result["frame_index"][row]


def test_a_rerun_skips_finished_videos_and_redoes_none(tmp_path):
    videos = tmp_path / "videos"
    videos.mkdir()
    keys = ["V1", "V2", "V3"]
    for k in keys:
        _video(videos / f"{k}.mp4", seconds=2.0)
    out = tmp_path / "out"

    archive.run(keys[:2], videos, out, pipeline, SETTINGS, PINS, FrameStandIn(), clip_encoder, ClipStandIn(), tmp_path / "s", session="one")
    first = (out / "V1.npz").stat().st_mtime_ns
    clips = ClipStandIn()
    archive.run(keys, videos, out, pipeline, SETTINGS, PINS, FrameStandIn(), clip_encoder, clips, tmp_path / "s", session="two")

    manifest = json.loads((out / "manifest.json").read_text())
    assert [manifest["videos"][k]["session"] for k in keys] == ["one", "one", "two"]
    assert (out / "V1.npz").stat().st_mtime_ns == first
    assert len(clips.clips) == manifest["videos"]["V3"]["admitted"]
    report = archive.check(keys, out)
    assert report["videos"] == 3 and not report["missing"] and not report["problems"] and not report["failed"]


def test_a_video_whose_file_was_lost_is_redone(tmp_path):
    videos = tmp_path / "videos"
    videos.mkdir()
    _video(videos / "V1.mp4", seconds=2.0)
    out = tmp_path / "out"
    archive.run(["V1"], videos, out, pipeline, SETTINGS, PINS, FrameStandIn(), clip_encoder, ClipStandIn(), tmp_path / "s", session="one")
    (out / "V1.npz").unlink()

    archive.run(["V1"], videos, out, pipeline, SETTINGS, PINS, FrameStandIn(), clip_encoder, ClipStandIn(), tmp_path / "s", session="two")

    assert json.loads((out / "manifest.json").read_text())["videos"]["V1"]["session"] == "two"


def test_a_failed_video_is_recorded_and_the_run_goes_on(tmp_path):
    videos = tmp_path / "videos"
    videos.mkdir()
    _video(videos / "V2.mp4", seconds=2.0)
    (videos / "V1.mp4").write_bytes(b"not a video")

    manifest = archive.run(["V1", "V2"], videos, tmp_path / "out", pipeline, SETTINGS, PINS, FrameStandIn(), clip_encoder, ClipStandIn(), tmp_path / "s")

    assert "V1" in manifest["failed"] and "V2" in manifest["videos"]
    assert archive.check(["V1", "V2"], tmp_path / "out")["missing"] == ["V1"]


def test_an_archive_is_never_mixed_with_other_settings(tmp_path):
    videos = tmp_path / "videos"
    videos.mkdir()
    _video(videos / "V1.mp4", seconds=2.0)
    out = tmp_path / "out"
    archive.run(["V1"], videos, out, pipeline, SETTINGS, PINS, FrameStandIn(), clip_encoder, ClipStandIn(), tmp_path / "s")

    with pytest.raises(RuntimeError, match="never mixed"):
        archive.run(["V1"], videos, out, pipeline, {**SETTINGS, "motion_cell_threshold": 30.0}, PINS, FrameStandIn(), clip_encoder, ClipStandIn(), tmp_path / "s")


def test_product_segments_are_matched_by_frame_and_every_mismatch_is_reported(tmp_path):
    archive_dir = tmp_path / "virat"
    archive_dir.mkdir()
    fv = np.eye(4, 1152, dtype=np.float32)
    np.savez(
        archive_dir / "VA.npz",
        frame_index=np.array([10, 40, 70], np.int32),
        timestamp_s=np.array([10, 40, 70]) / 30,
        admission_reason=np.array(["heartbeat", "motion", "heartbeat"]),
        frame_vectors=fv[:3],
        clip_vectors=np.eye(3, 512, dtype=np.float32),
    )
    segments = [
        {"segment_id": 501, "video_id": 7, "clip_key": "VA", "frame_index": 40, "timestamp_s": 40 / 30, "admission_reason": "motion",
         "laptop_frame_vector": fv[1].tolist()},
        {"segment_id": 502, "video_id": 7, "clip_key": "VA", "frame_index": 70, "timestamp_s": 70 / 30, "admission_reason": "heartbeat"},
        {"segment_id": 503, "video_id": 7, "clip_key": "VA", "frame_index": 55, "timestamp_s": 55 / 30, "admission_reason": "motion"},
    ]
    (tmp_path / "segments.json").write_text(json.dumps({"segments": segments}))

    report = archive.match_product(tmp_path / "segments.json", archive_dir, tmp_path / "product")

    assert report["videos"][7]["matched"] == 2
    assert report["unmatched"] == [{"segment_id": 503, "clip_key": "VA", "frame_index": 55}]
    assert report["agreement"][0]["cosine"] == pytest.approx(1.0)
    with np.load(tmp_path / "product" / "7.npz") as data:
        assert data["segment_id"].tolist() == [501, 502]
        assert np.array_equal(data["frame_vectors"], fv[1:3])
        assert np.array_equal(data["clip_vectors"][1], np.eye(3, 512, dtype=np.float32)[2])
