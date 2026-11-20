"""OMNI-X05: a video made ready on Colab, added with its vectors (`colab_vectors.add_ready`).

Needs Postgres (`docker compose up -d`); runs on the test database (conftest). Ingestion and
the consumer are faked as in test_video_extract.py (each message handed to the consumer's own
`store_segment`, then to `queue_embedding`); Qdrant is qdrant-client's in-process mode; the
CPU jobs are recorded instead of reaching the broker. The ready folder is written here in the
layout `scripts/encode_uploads.py` writes (that side is tested in scripts/tests).
"""

import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest
from app import colab_vectors
from app import consumer as consumer_module
from app import extraction as extraction_module
from app import videos as videos_module
from app.db import SessionLocal
from app.models import Segment, Video
from app.settings import settings
from omnisight_common import AdmissionReason, SegmentMessage, VideoStatus
from omnisight_common.clip_vectors import CLIP_VECTOR_SIZE
from omnisight_common.frame_vectors import FRAME_VECTOR_SIZE
from qdrant_client import QdrantClient

NAME_PREFIX = "omnix05-"
SETTINGS = {
    "motion_stride_s": 0.5, "motion_grid_size": 8, "motion_cell_threshold": 25.0,
    "motion_min_active_cells": 3, "motion_blur_kernel": 21, "heartbeat_interval_s": 1.0,
    "thumb_width_px": 320, "frame_jpeg_quality": 85, "thumb_jpeg_quality": 70,
}
# Frames 0..9: 0 heartbeat; 3, 6, 9 motion.
FRAMES = 10
ADMITTED = [0, 3, 6, 9]
FPS = 10.0
MP4 = b"\x00\x00\x00\x18ftypmp42"  # enough of a header for the upload's sniffing


def _pins() -> dict:
    return {name: getattr(settings, name) for name in colab_vectors.PIN_NAMES}


def _reason(i: int) -> str:
    return "heartbeat" if i == 0 else "motion"


def _unit(rng, n: int, dim: int) -> np.ndarray:
    v = rng.standard_normal((n, dim)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def _write_ready(root: Path, content: bytes, *, name="clip.mp4", frames=ADMITTED, pins=None, gate=None) -> Path:
    fp = hashlib.sha256(content).hexdigest()
    folder = root / fp
    folder.mkdir(parents=True)
    (folder / name).write_bytes(content)
    rng = np.random.default_rng(len(frames))
    np.savez(
        folder / "vectors.npz",
        frame_index=np.array(frames, np.int32),
        timestamp_s=np.array(frames, np.float64) / FPS,
        admission_reason=np.array([_reason(i) for i in frames], dtype="U9"),
        frame_vectors=_unit(rng, len(frames), FRAME_VECTOR_SIZE),
        clip_vectors=_unit(rng, len(frames), CLIP_VECTOR_SIZE),
    )
    (folder / "info.json").write_text(json.dumps({
        "file": name, "fingerprint": fp, "pins": pins or _pins(), "gate": gate or SETTINGS,
        "frames_decoded": FRAMES, "admitted": len(frames), "fps": FPS, "duration_s": FRAMES / FPS,
    }))
    return folder


class _Memory(QdrantClient):
    """In-process Qdrant that survives `close()`, so the test can look afterwards."""

    def close(self, **kwargs):
        pass


@pytest.fixture
def qdrant(monkeypatch):
    memory = _Memory(":memory:")
    monkeypatch.setattr(colab_vectors, "qdrant_client", lambda _s: memory)
    return memory


@pytest.fixture
def cpu_jobs(monkeypatch):
    """The embed jobs queued for the CPU: by the consumer, and by a fallback."""
    jobs = []
    monkeypatch.setattr(consumer_module, "publish_jobs", lambda _c, _q, js: jobs.extend(js))

    def fall_back(video_id, reason):
        jobs.append(("fall_back", video_id, reason))
        with SessionLocal() as db:
            db.query(Video).filter_by(id=video_id).update({"colab_vectors": False})
            db.commit()

    monkeypatch.setattr(colab_vectors, "fall_back", fall_back)
    return jobs


@pytest.fixture(autouse=True)
def stack(tmp_path, monkeypatch):
    for name in ("frames", "thumbs", "videos"):
        (tmp_path / name).mkdir()
    monkeypatch.setattr(settings, "frames_path", str(tmp_path / "frames"))
    monkeypatch.setattr(settings, "thumbs_path", str(tmp_path / "thumbs"))
    monkeypatch.setattr(settings, "video_storage_path", str(tmp_path / "videos"))
    monkeypatch.setattr(colab_vectors, "extraction_settings", lambda: dict(SETTINGS))
    monkeypatch.setattr(extraction_module, "ingestion_publish_extraction", _fake_ingestion)

    def probe(video, db):
        video.status = VideoStatus.READY
        db.commit()

    monkeypatch.setattr(videos_module, "_probe_and_finalize", probe)
    yield tmp_path
    with SessionLocal() as session:
        session.query(Video).filter(Video.filename.like(f"{NAME_PREFIX}%")).delete(synchronize_session=False)
        session.commit()


class _Channel:
    pass


def _fake_ingestion(video_id, path, source_type, camera_id, extraction_id):
    """Ingestion and the consumer together: the frames ADMITTED are admitted, each message
    stored by `store_segment` and then offered to `queue_embedding`, as the consumer does."""
    frames = Path(settings.frames_path) / str(video_id)
    frames.mkdir(parents=True, exist_ok=True)
    for i in range(FRAMES):
        admitted = i in ADMITTED
        frame_path = None
        if admitted:
            frame_path = str(frames / f"{i:06d}.jpg")
            Path(frame_path).write_bytes(b"frame")
        message = SegmentMessage(
            video_id=video_id, camera_id=camera_id, frame_index=i, timestamp_s=i / FPS,
            frame_path=frame_path, thumb_path=None, motion_score=None, admitted=admitted,
            source_type=source_type, extraction_id=extraction_id,
            admission_reason=AdmissionReason(_reason(i)) if admitted else None,
        )
        body = message.model_dump_json().encode()
        consumer_module.store_segment(body)
        consumer_module.queue_embedding(_Channel(), body)
    return {"ok": True, "published": FRAMES, "error": None, "stride_s": 0.5, "grid_size": 8,
            "cell_threshold": 25.0, "min_active_cells": 3}


def _upload(content: bytes, name: str) -> int:
    """A normal upload, then a normal extraction (no ready vectors)."""
    with SessionLocal() as db:
        video, _ = videos_module.store_video(io.BytesIO(content), f"{NAME_PREFIX}{name}", db)
        video_id = video.id
        extraction_id = extraction_module.claim_extraction(db, video_id)
    extraction_module.run_extraction(video_id, extraction_id)
    return video_id


def _admitted_ids(video_id: int) -> set[int]:
    with SessionLocal() as db:
        return {i for (i,) in db.query(Segment.id).filter_by(video_id=video_id, admitted=True)}


def _point_ids(client, collection: str) -> set[int]:
    if not client.collection_exists(collection):
        return set()
    points, _ = client.scroll(collection, limit=1000, with_payload=False, with_vectors=False)
    return {int(p.id) for p in points}


def _videos_with(fingerprint: str) -> list[int]:
    with SessionLocal() as db:
        return [v for (v,) in db.query(Video.id).filter_by(fingerprint=fingerprint)]


CONTENT = MP4 + b"one video's bytes"


# --- the fingerprint -------------------------------------------------------------------------


def test_an_upload_stores_the_sha256_of_its_bytes_whatever_its_name():
    content = MP4 + bytes(range(256)) * 9000  # past one 1 MiB chunk
    with SessionLocal() as db:
        video, _ = videos_module.store_video(io.BytesIO(content), f"{NAME_PREFIX}a.mp4", db)
        renamed, _ = videos_module.store_video(io.BytesIO(content), f"{NAME_PREFIX}renamed.mp4", db)
        assert video.fingerprint == renamed.fingerprint == hashlib.sha256(content).hexdigest()


# --- adding a ready video --------------------------------------------------------------------


def test_a_new_video_is_stored_extracted_and_gets_both_vectors_by_frame_with_no_cpu_job(stack, qdrant, cpu_jobs):
    folder = _write_ready(stack / "ready", CONTENT, name=f"{NAME_PREFIX}clip.mp4")

    result = colab_vectors.add_ready(folder)

    video_id = result["video_id"]
    assert result["result"] == "added" and result["problem"] is None
    assert (result["admitted"], result["frame_vectors"], result["clip_vectors"]) == (4, 4, 4)
    admitted = _admitted_ids(video_id)
    assert _point_ids(qdrant, settings.frame_collection) == admitted
    assert _point_ids(qdrant, settings.clip_collection) == admitted
    assert cpu_jobs == []
    with SessionLocal() as db:
        video = db.get(Video, video_id)
        assert video.colab_vectors and video.filename == f"{NAME_PREFIX}clip.mp4"
        assert Path(video.path).read_bytes() == CONTENT
        seg6 = db.query(Segment.id).filter_by(video_id=video_id, frame_index=6).scalar()
    # Each point holds its own frame's vector: frame 6 is row 2.
    ready = colab_vectors.read_ready(folder)
    [point] = qdrant.retrieve(settings.clip_collection, [seg6], with_vectors=True)
    assert np.allclose(point.vector, ready.clip_vectors[2], atol=1e-6)
    assert point.payload["model"] == settings.clip_model_id


def test_adding_the_same_video_twice_changes_nothing(stack, qdrant, cpu_jobs):
    folder = _write_ready(stack / "ready", CONTENT, name=f"{NAME_PREFIX}clip.mp4")
    first = colab_vectors.add_ready(folder)
    before = qdrant.retrieve(settings.frame_collection, sorted(_admitted_ids(first["video_id"])), with_vectors=True)

    again = colab_vectors.add_ready(folder)

    assert again["result"] == "existing" and again["video_id"] == first["video_id"]
    assert _videos_with(colab_vectors.read_ready(folder).fingerprint) == [first["video_id"]]
    after = qdrant.retrieve(settings.frame_collection, sorted(_admitted_ids(first["video_id"])), with_vectors=True)
    assert [(p.id, p.vector) for p in after] == [(p.id, p.vector) for p in before]


def test_the_same_file_uploaded_normally_under_another_name_gets_the_drive_vectors(stack, qdrant, cpu_jobs):
    video_id = _upload(CONTENT, "renamed.mp4")
    assert len(cpu_jobs) == 4  # a normal upload: on the CPU, as today
    folder = _write_ready(stack / "ready", CONTENT, name="original.mp4")

    result = colab_vectors.add_ready(folder)

    assert result["result"] == "existing" and result["video_id"] == video_id
    assert (result["frame_vectors"], result["clip_vectors"]) == (4, 4)
    assert _videos_with(folder.name) == [video_id]


def test_a_video_not_on_drive_is_encoded_on_the_cpu_as_before(qdrant, cpu_jobs):
    video_id = _upload(MP4 + b"not on drive", "plain.mp4")

    assert sorted(job.segment_id for job in cpu_jobs) == sorted(_admitted_ids(video_id))
    with SessionLocal() as db:
        assert not db.get(Video, video_id).colab_vectors


def test_a_folder_made_with_other_pins_is_refused_and_the_cpu_encodes(stack, qdrant, cpu_jobs):
    folder = _write_ready(stack / "ready", CONTENT, name=f"{NAME_PREFIX}clip.mp4",
                          pins={**_pins(), "clip_model_revision": "other"})

    result = colab_vectors.add_ready(folder)

    assert result["result"] == "refused" and result["clip_vectors"] == 0
    assert len(cpu_jobs) == 4


def test_a_folder_made_with_other_settings_is_refused_for_a_video_already_in(stack, qdrant, cpu_jobs):
    _upload(CONTENT, "clip.mp4")
    folder = _write_ready(stack / "ready", CONTENT, gate={**SETTINGS, "frame_jpeg_quality": 90})

    result = colab_vectors.add_ready(folder)

    assert result["result"] == "refused" and "frame_jpeg_quality" in result["problem"]
    assert result["clip_vectors"] == 0


def test_if_any_frame_does_not_match_nothing_is_imported_and_the_cpu_encodes(stack, qdrant, cpu_jobs):
    folder = _write_ready(stack / "ready", CONTENT, name=f"{NAME_PREFIX}clip.mp4", frames=[0, 3, 7])

    result = colab_vectors.add_ready(folder)

    assert result["result"] == "refused"
    assert _point_ids(qdrant, settings.frame_collection) == set()
    assert _point_ids(qdrant, settings.clip_collection) == set()
    [(kind, video_id, reason)] = cpu_jobs
    assert (kind, video_id) == ("fall_back", result["video_id"])
    assert reason.startswith("3 frames do not match")  # 6 and 9 missing, 7 extra


def test_a_video_file_that_is_not_the_one_encoded_is_refused(stack, qdrant, cpu_jobs):
    folder = _write_ready(stack / "ready", CONTENT, name=f"{NAME_PREFIX}clip.mp4")
    (folder / f"{NAME_PREFIX}clip.mp4").write_bytes(MP4 + b"another file")

    result = colab_vectors.add_ready(folder)

    assert result["result"] == "refused" and "not the one" in result["problem"]
    assert _videos_with(folder.name) == []


def test_status_says_which_ready_videos_are_in_and_with_what(stack, qdrant, cpu_jobs):
    added = colab_vectors.add_ready(_write_ready(stack / "ready", CONTENT, name=f"{NAME_PREFIX}clip.mp4"))
    uploaded = _upload(MP4 + b"cpu only", "cpu.mp4")
    absent = "0" * 64

    states = colab_vectors.status([
        hashlib.sha256(CONTENT).hexdigest(), hashlib.sha256(MP4 + b"cpu only").hexdigest(), absent,
    ])

    assert list(states.values()) == [
        {"video_id": added["video_id"], "status": "ready", "admitted": 4, "frame_vectors": 4, "clip_vectors": 4},
        {"video_id": uploaded, "status": "ready", "admitted": 4, "frame_vectors": 0, "clip_vectors": 0},
        {"video_id": None},
    ]


# --- the checks on their own -----------------------------------------------------------------


def test_match_counts_each_missing_or_disagreeing_frame_once(stack):
    ready = colab_vectors.read_ready(_write_ready(stack / "ready", CONTENT, frames=[0, 3, 6]))
    segments = [
        (1, 0, 0.0, "heartbeat"),   # matches
        (2, 3, 0.3, "heartbeat"),   # reason differs
        (3, 6, 0.61, "motion"),     # time differs
        (4, 9, 0.9, "motion"),      # not in the file
    ]
    assert colab_vectors.match(ready, segments) == ({1: 0}, 3)


def test_an_extra_row_in_the_file_is_a_mismatch(stack):
    ready = colab_vectors.read_ready(_write_ready(stack / "ready", CONTENT, frames=[0, 3]))
    assert colab_vectors.match(ready, [(1, 0, 0.0, "heartbeat")]) == ({1: 0}, 1)


def test_a_video_regated_with_other_parameters_is_refused(stack):
    ready = colab_vectors.read_ready(_write_ready(stack / "ready", CONTENT))
    video = Video(gate_stride_s=0.5, gate_grid_size=8, gate_cell_threshold=30.0, gate_min_active_cells=3)
    problem = colab_vectors.usable(ready, colab_vectors.video_settings(video, SETTINGS))
    assert problem and "motion_cell_threshold" in problem
