"""OMNI-X05: any video's ready folder on Drive, named by its fingerprint, with stand-in encoders.

The gate, the decoding and the clip windows are the real code (`encode_virat_archive`); the
encoders are test_encode_virat_archive's stand-ins.
"""

import hashlib
import json
import shutil

import numpy as np
import pytest
from test_encode_virat_archive import (
    PINS,
    ROOT,
    SETTINGS,
    ClipStandIn,
    FrameStandIn,
    _gate_count,
    _load,
    _video,
    clip_encoder,
    pipeline,
)

uploads = _load("encode_uploads", ROOT / "scripts" / "encode_uploads.py")


def _encode(video, out, tmp_path, *, pins=PINS, settings=SETTINGS, clips=None):
    return uploads.encode_upload(
        video, out, pipeline, settings, pins, FrameStandIn(), clip_encoder, clips or ClipStandIn(), tmp_path / "s"
    )


def test_the_folder_is_named_by_the_sha256_and_holds_the_video_its_vectors_and_what_made_them(tmp_path):
    video = _video(tmp_path / "anything.avi", seconds=2.0)
    out = tmp_path / "ready"

    summary = _encode(video, out, tmp_path)

    key = hashlib.sha256(video.read_bytes()).hexdigest()
    assert summary["fingerprint"] == key and not summary["skipped"]
    assert sorted(p.name for p in out.iterdir()) == [key]
    folder = out / key
    assert sorted(p.name for p in folder.iterdir()) == ["anything.avi", "info.json", "vectors.npz"]
    assert (folder / "anything.avi").read_bytes() == video.read_bytes()
    _, kept = _gate_count(video)
    with np.load(folder / "vectors.npz") as data:
        assert data["frame_index"].tolist() == kept
        assert data["frame_vectors"].shape == (len(kept), 1152)
        assert data["clip_vectors"].shape == (len(kept), 512)
    info = json.loads((folder / "info.json").read_text())
    assert info["file"] == "anything.avi" and info["fingerprint"] == key
    assert info["pins"] == PINS and info["gate"] == SETTINGS
    assert info["admitted"] == len(kept)


def test_a_renamed_copy_has_the_same_fingerprint_and_is_not_encoded_again(tmp_path):
    video = _video(tmp_path / "first.avi", seconds=2.0)
    out = tmp_path / "ready"
    first = _encode(video, out, tmp_path)
    renamed = tmp_path / "renamed.avi"
    shutil.copy(video, renamed)
    clips = ClipStandIn()

    again = _encode(renamed, out, tmp_path, clips=clips)

    assert again["fingerprint"] == first["fingerprint"] and again["skipped"]
    assert clips.clips == []
    assert len(list(out.iterdir())) == 1


def test_a_folder_made_with_other_pins_or_settings_is_refused_not_overwritten(tmp_path):
    video = _video(tmp_path / "v.avi", seconds=2.0)
    out = tmp_path / "ready"
    summary = _encode(video, out, tmp_path)
    vectors = out / summary["fingerprint"] / "vectors.npz"
    before = vectors.read_bytes()

    with pytest.raises(RuntimeError, match="other pins or settings"):
        _encode(video, out, tmp_path, pins={**PINS, "clip": "other"})
    with pytest.raises(RuntimeError, match="other pins or settings"):
        _encode(video, out, tmp_path, settings={**SETTINGS, "frame_jpeg_quality": 90})
    assert vectors.read_bytes() == before


def test_an_unfinished_folder_from_a_lost_session_is_redone(tmp_path):
    video = _video(tmp_path / "v.avi", seconds=2.0)
    out = tmp_path / "ready"
    key = hashlib.sha256(video.read_bytes()).hexdigest()
    (out / key).mkdir(parents=True)
    (out / key / "v.avi").write_bytes(b"half")  # no info.json: never finished

    summary = _encode(video, out, tmp_path)

    assert not summary["skipped"]
    assert (out / key / "info.json").is_file() and (out / key / "v.avi").read_bytes() == video.read_bytes()
    assert not (out / f"{key}.part").exists()


def test_the_fingerprint_is_the_one_query_computes_while_streaming(tmp_path):
    """query hashes the 64-byte header, then 1 MiB chunks; the result is the plain SHA-256."""
    data = np.random.default_rng(0).bytes(3 * (1 << 20) + 123)
    path = tmp_path / "blob.bin"
    path.write_bytes(data)
    streamed = hashlib.sha256(data[:64])
    for start in range(64, len(data), 1 << 20):
        streamed.update(data[start : start + (1 << 20)])

    assert uploads.fingerprint(path) == streamed.hexdigest()
