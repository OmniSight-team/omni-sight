"""OMNI-303: POST /videos/{id}/extract and the background job behind it.

Requires Postgres to be up with `alembic upgrade head` applied. Ingestion is
faked at the client boundary (`extraction.ingestion_extract_file`) so this
proves query's own logic: the status moves, the rows and files, the failure
paths, the restart sweep. The real decoding is covered by
services/ingestion/tests/test_extraction_pipeline.py, and the whole chain was
run live against the running containers (docs/context/week-03-04.md).

Starlette's TestClient finishes background tasks before `client.post` returns,
so after the POST the job has already run.
"""

from pathlib import Path

import pytest
from app import extraction as extraction_module
from app.db import SessionLocal
from app.ingestion_client import IngestionUnavailableError
from app.main import app
from app.models import Camera, Segment, User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import CameraStatus, Domain, Role, VideoSource, VideoStatus

client = TestClient(app)

TEST_PASSWORD = "Omni303Pass!"
OPERATOR_EMAIL = "omni303-operator@omnisight.local"
NAME_PREFIX = "omni303-"


@pytest.fixture(scope="module", autouse=True)
def omni303_user():
    with SessionLocal() as session:
        session.add(
            User(
                email=OPERATOR_EMAIL,
                password_hash=hash_password(TEST_PASSWORD),
                role=Role.OPERATOR,
                is_active=True,
            )
        )
        session.commit()

    yield

    with SessionLocal() as session:
        session.query(User).filter_by(email=OPERATOR_EMAIL).delete(synchronize_session=False)
        session.commit()


@pytest.fixture
def headers():
    resp = client.post("/auth/login", json={"email": OPERATOR_EMAIL, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture(autouse=True)
def isolated_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "frames_path", str(tmp_path / "frames"))
    monkeypatch.setattr(settings, "thumbs_path", str(tmp_path / "thumbs"))
    yield
    with SessionLocal() as session:
        # deleting a video cascades to its segment rows in the database
        session.query(Video).filter(Video.filename.like(f"{NAME_PREFIX}%")).delete(
            synchronize_session=False
        )
        session.query(Camera).filter(Camera.name.like(f"{NAME_PREFIX}%")).delete(
            synchronize_session=False
        )
        session.commit()


def _make_video(tmp_path, name="clip", status=VideoStatus.READY, source=VideoSource.UPLOAD, camera_id=None):
    path = tmp_path / f"{NAME_PREFIX}{name}.mp4"
    path.write_bytes(b"video bytes")
    with SessionLocal() as session:
        video = Video(
            filename=path.name,
            path=str(path),
            source=source,
            camera_id=camera_id,
            size_bytes=path.stat().st_size,
            status=status,
        )
        session.add(video)
        session.commit()
        return video.id


def _fake_ingestion(segment_count, seen=None):
    """A stand-in for ingestion that writes real frame and thumbnail files."""

    def fake(video_id, path, source_type, camera_id):
        if seen is not None:
            with SessionLocal() as session:
                seen["status_during"] = session.get(Video, video_id).status
            seen["args"] = (video_id, path, source_type, camera_id)
        frames = Path(settings.frames_path) / str(video_id)
        thumbs = Path(settings.thumbs_path) / str(video_id)
        frames.mkdir(parents=True, exist_ok=True)
        thumbs.mkdir(parents=True, exist_ok=True)
        segments = []
        for i in range(segment_count):
            (frames / f"{i:06d}.jpg").write_bytes(b"frame")
            (thumbs / f"{i:06d}.jpg").write_bytes(b"thumb")
            segments.append(
                {
                    "video_id": video_id,
                    "camera_id": camera_id,
                    "frame_index": i * 10,
                    "timestamp_s": float(i),
                    "frame_path": str(frames / f"{i:06d}.jpg"),
                    "thumb_path": str(thumbs / f"{i:06d}.jpg"),
                    "motion_score": None,
                    "admitted": False,
                    "source_type": source_type,
                }
            )
        return {"ok": True, "segments": segments, "error": None}

    return fake


def _detail(headers, video_id):
    resp = client.get(f"/videos/{video_id}", headers=headers)
    assert resp.status_code == 200
    return resp.json()


def _segment_count(video_id):
    with SessionLocal() as session:
        return session.query(Segment).filter_by(video_id=video_id).count()


def test_extract_returns_at_once_and_the_video_moves_extracting_to_ready(tmp_path, headers, monkeypatch):
    video_id = _make_video(tmp_path)
    seen = {}
    monkeypatch.setattr(extraction_module, "ingestion_extract_file", _fake_ingestion(5, seen))

    resp = client.post(f"/videos/{video_id}/extract", headers=headers)

    assert resp.status_code == 202
    assert resp.json() == {"video_id": video_id, "status": "extracting"}
    assert seen["status_during"] == VideoStatus.EXTRACTING  # it really was extracting while the job ran
    detail = _detail(headers, video_id)
    assert detail["status"] == "ready"
    assert detail["error"] is None
    assert detail["segments_count"] == 5
    assert _segment_count(video_id) == 5


def test_a_failure_reported_by_ingestion_leaves_failed_with_the_reason(tmp_path, headers, monkeypatch):
    video_id = _make_video(tmp_path)
    monkeypatch.setattr(
        extraction_module,
        "ingestion_extract_file",
        lambda *a: {"ok": False, "segments": [], "error": "could not decode frame 40"},
    )

    client.post(f"/videos/{video_id}/extract", headers=headers)

    detail = _detail(headers, video_id)
    assert detail["status"] == "failed"
    assert detail["error"] == "could not decode frame 40"
    assert detail["segments_count"] == 0


def test_ingestion_being_down_leaves_failed_with_the_reason(tmp_path, headers, monkeypatch):
    video_id = _make_video(tmp_path)

    def down(*args):
        raise IngestionUnavailableError("connection refused")

    monkeypatch.setattr(extraction_module, "ingestion_extract_file", down)

    client.post(f"/videos/{video_id}/extract", headers=headers)

    detail = _detail(headers, video_id)
    assert detail["status"] == "failed"
    assert detail["error"] == "ingestion service unavailable"


def test_a_crash_inside_the_job_still_leaves_failed_not_extracting(tmp_path, headers, monkeypatch):
    video_id = _make_video(tmp_path)

    def crash(*args):
        raise RuntimeError("something unexpected")

    monkeypatch.setattr(extraction_module, "ingestion_extract_file", crash)

    client.post(f"/videos/{video_id}/extract", headers=headers)

    detail = _detail(headers, video_id)
    assert detail["status"] == "failed"
    assert "something unexpected" in detail["error"]


def test_a_malformed_ingestion_response_leaves_failed_and_no_rows_or_files(tmp_path, headers, monkeypatch):
    video_id = _make_video(tmp_path)
    good = _fake_ingestion(3)

    def malformed(video_id, path, source_type, camera_id):
        result = good(video_id, path, source_type, camera_id)
        del result["segments"][1]["frame_path"]  # files are on disk; one row cannot be built
        return result

    monkeypatch.setattr(extraction_module, "ingestion_extract_file", malformed)

    client.post(f"/videos/{video_id}/extract", headers=headers)

    assert _detail(headers, video_id)["status"] == "failed"
    assert _segment_count(video_id) == 0  # all or nothing
    assert not (tmp_path / "frames" / str(video_id)).exists()
    assert not (tmp_path / "thumbs" / str(video_id)).exists()


def test_rerunning_replaces_the_segments_and_their_files(tmp_path, headers, monkeypatch):
    video_id = _make_video(tmp_path)
    monkeypatch.setattr(extraction_module, "ingestion_extract_file", _fake_ingestion(5))
    client.post(f"/videos/{video_id}/extract", headers=headers)
    assert _segment_count(video_id) == 5

    monkeypatch.setattr(extraction_module, "ingestion_extract_file", _fake_ingestion(2))
    client.post(f"/videos/{video_id}/extract", headers=headers)

    assert _segment_count(video_id) == 2
    assert len(list((tmp_path / "frames" / str(video_id)).iterdir())) == 2
    assert len(list((tmp_path / "thumbs" / str(video_id)).iterdir())) == 2
    assert _detail(headers, video_id)["status"] == "ready"


def test_a_failed_video_can_be_extracted_again(tmp_path, headers, monkeypatch):
    video_id = _make_video(tmp_path, status=VideoStatus.FAILED)
    monkeypatch.setattr(extraction_module, "ingestion_extract_file", _fake_ingestion(3))

    resp = client.post(f"/videos/{video_id}/extract", headers=headers)

    assert resp.status_code == 202
    detail = _detail(headers, video_id)
    assert detail["status"] == "ready"
    assert detail["error"] is None


def test_a_second_extract_while_one_is_running_is_refused(tmp_path, headers):
    video_id = _make_video(tmp_path, status=VideoStatus.EXTRACTING)

    resp = client.post(f"/videos/{video_id}/extract", headers=headers)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "an extraction is already running for this video"
    assert _detail(headers, video_id)["status"] == "extracting"


def test_a_video_that_has_not_been_probed_yet_cannot_be_extracted(tmp_path, headers):
    video_id = _make_video(tmp_path, status=VideoStatus.UPLOADED)

    resp = client.post(f"/videos/{video_id}/extract", headers=headers)

    assert resp.status_code == 409
    assert "uploaded" in resp.json()["detail"]
    assert _detail(headers, video_id)["status"] == "uploaded"


def test_extracting_a_missing_video_is_a_404(headers):
    assert client.post("/videos/99999999/extract", headers=headers).status_code == 404


def test_extract_requires_auth(tmp_path):
    video_id = _make_video(tmp_path)

    assert client.post(f"/videos/{video_id}/extract").status_code == 401


def test_a_camera_recording_is_labelled_as_camera_footage(tmp_path, headers, monkeypatch):
    with SessionLocal() as session:
        camera = Camera(
            name=f"{NAME_PREFIX}cam",
            rtsp_url="rtsp://example.invalid/x",
            location="test",
            group_name="test",
            domain=Domain.SURVEILLANCE,
            status=CameraStatus.REGISTERED,
        )
        session.add(camera)
        session.commit()
        camera_id = camera.id
    video_id = _make_video(tmp_path, source=VideoSource.CAMERA, camera_id=camera_id)
    seen = {}
    monkeypatch.setattr(extraction_module, "ingestion_extract_file", _fake_ingestion(2, seen))

    client.post(f"/videos/{video_id}/extract", headers=headers)

    assert seen["args"][2:] == ("camera", camera_id)
    with SessionLocal() as session:
        rows = session.query(Segment).filter_by(video_id=video_id).all()
        assert {(r.source_type.value, r.camera_id) for r in rows} == {("camera", camera_id)}


def test_after_a_restart_a_video_left_extracting_is_marked_failed(tmp_path, headers):
    stuck = _make_video(tmp_path, "stuck", status=VideoStatus.EXTRACTING)
    fine = _make_video(tmp_path, "fine", status=VideoStatus.READY)

    assert extraction_module.mark_interrupted_extractions() >= 1

    stuck_detail = _detail(headers, stuck)
    assert stuck_detail["status"] == "failed"
    assert stuck_detail["error"] == extraction_module.INTERRUPTED_MESSAGE
    assert _detail(headers, fine)["status"] == "ready"


def test_deleting_a_video_removes_its_frame_and_thumbnail_folders(tmp_path, headers, monkeypatch):
    video_id = _make_video(tmp_path)
    monkeypatch.setattr(extraction_module, "ingestion_extract_file", _fake_ingestion(4))
    client.post(f"/videos/{video_id}/extract", headers=headers)
    assert (tmp_path / "frames" / str(video_id)).is_dir()

    resp = client.delete(f"/videos/{video_id}", headers=headers)

    assert resp.status_code == 200
    assert not (tmp_path / "frames" / str(video_id)).exists()
    assert not (tmp_path / "thumbs" / str(video_id)).exists()
    assert _segment_count(video_id) == 0


def test_a_video_cannot_be_deleted_while_it_is_being_extracted(tmp_path, headers):
    video_id = _make_video(tmp_path, status=VideoStatus.EXTRACTING)

    resp = client.delete(f"/videos/{video_id}", headers=headers)

    assert resp.status_code == 409
    assert _detail(headers, video_id)["status"] == "extracting"


def test_the_video_list_reports_each_videos_real_segment_count(tmp_path, headers, monkeypatch):
    many = _make_video(tmp_path, "many")
    few = _make_video(tmp_path, "few")
    none = _make_video(tmp_path, "none")
    monkeypatch.setattr(extraction_module, "ingestion_extract_file", _fake_ingestion(6))
    client.post(f"/videos/{many}/extract", headers=headers)
    monkeypatch.setattr(extraction_module, "ingestion_extract_file", _fake_ingestion(2))
    client.post(f"/videos/{few}/extract", headers=headers)

    resp = client.get("/videos?limit=200", headers=headers)

    counts = {v["id"]: v["segments_count"] for v in resp.json() if v["id"] in (many, few, none)}
    assert counts == {many: 6, few: 2, none: 0}
