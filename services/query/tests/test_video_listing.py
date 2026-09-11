"""OMNI-207: video listing with server-side filters, and delete.

Requires Postgres to be up (`docker compose up -d`). Filtering and
pagination correctness (right rows, right order, right page size) are
proven here against the real database. That the filtering happens in the
SQL WHERE clause rather than in Python — the acceptance criterion's own
wording — was proven live by compiling the actual statement against a real
camera and real rows spanning different dates; see docs/context/week-02.md.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.db import SessionLocal
from app.main import app
from app.models import Camera, User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import CameraStatus, Domain, Role, VideoSource, VideoStatus

client = TestClient(app)

TEST_PASSWORD = "Omni207Pass!"
OPERATOR_EMAIL = "omni207-operator@omnisight.local"

NOW = datetime.now(UTC)


@pytest.fixture(scope="module", autouse=True)
def omni207_user():
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
def auth_headers():
    resp = client.post("/auth/login", json={"email": OPERATOR_EMAIL, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def seeded_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "video_storage_path", str(tmp_path))

    with SessionLocal() as session:
        camera = Camera(
            name="Listing test cam",
            rtsp_url="rtsp://mediamtx:8554/cam01",
            location="Test",
            group_name="test",
            domain=Domain.SURVEILLANCE,
            status=CameraStatus.REGISTERED,
        )
        session.add(camera)
        session.commit()
        session.refresh(camera)

        rows = {
            "old_upload": Video(
                filename="old_upload.mp4",
                path=str(tmp_path / "old_upload.mp4"),
                camera_id=None,
                source=VideoSource.UPLOAD,
                size_bytes=100,
                status=VideoStatus.READY,
                created_at=NOW - timedelta(days=10),
            ),
            "recent_upload": Video(
                filename="recent_upload.mp4",
                path=str(tmp_path / "recent_upload.mp4"),
                camera_id=None,
                source=VideoSource.UPLOAD,
                size_bytes=200,
                status=VideoStatus.READY,
                created_at=NOW - timedelta(hours=1),
            ),
            "camera_recording": Video(
                filename="camera_recording.mp4",
                path=str(tmp_path / "camera_recording.mp4"),
                camera_id=camera.id,
                source=VideoSource.CAMERA,
                size_bytes=300,
                status=VideoStatus.READY,
                created_at=NOW - timedelta(hours=2),
            ),
        }
        for video in rows.values():
            Path(video.path).write_bytes(b"fake video bytes")
        session.add_all(rows.values())
        session.commit()
        for video in rows.values():
            session.refresh(video)
        ids = {key: video.id for key, video in rows.items()}
        camera_id = camera.id

    yield {"ids": ids, "camera_id": camera_id}

    with SessionLocal() as session:
        session.query(Video).filter(Video.id.in_(ids.values())).delete(synchronize_session=False)
        session.flush()
        session.query(Camera).filter_by(id=camera_id).delete(synchronize_session=False)
        session.commit()


def test_filter_by_camera_id_returns_only_that_cameras_video(auth_headers, seeded_rows):
    resp = client.get("/videos", params={"camera_id": seeded_rows["camera_id"]}, headers=auth_headers)
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == [seeded_rows["ids"]["camera_recording"]]


def test_filter_by_source(auth_headers, seeded_rows):
    resp = client.get("/videos", params={"source": "upload"}, headers=auth_headers)
    assert resp.status_code == 200
    returned_ids = {row["id"] for row in resp.json()}
    assert seeded_rows["ids"]["old_upload"] in returned_ids
    assert seeded_rows["ids"]["recent_upload"] in returned_ids
    assert seeded_rows["ids"]["camera_recording"] not in returned_ids


def test_filter_by_date_range_excludes_older_rows(auth_headers, seeded_rows):
    resp = client.get(
        "/videos",
        params={"from": (NOW - timedelta(hours=4)).isoformat(), "to": NOW.isoformat()},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    returned_ids = {row["id"] for row in resp.json()}
    assert seeded_rows["ids"]["recent_upload"] in returned_ids
    assert seeded_rows["ids"]["camera_recording"] in returned_ids
    assert seeded_rows["ids"]["old_upload"] not in returned_ids


def test_uploads_and_camera_recordings_share_one_list(auth_headers, seeded_rows):
    resp = client.get("/videos", headers=auth_headers)
    returned_ids = {row["id"] for row in resp.json()}
    assert set(seeded_rows["ids"].values()) <= returned_ids


def test_pagination_limits_page_size_and_orders_newest_first(auth_headers, seeded_rows):
    resp = client.get("/videos", params={"limit": 1}, headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == seeded_rows["ids"]["recent_upload"]


def test_delete_removes_row_and_file_together(auth_headers, seeded_rows):
    video_id = seeded_rows["ids"]["recent_upload"]
    with SessionLocal() as session:
        file_path = Path(session.get(Video, video_id).path)
    assert file_path.is_file()

    resp = client.delete(f"/videos/{video_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {"id": video_id, "deleted": True}

    assert not file_path.is_file()
    with SessionLocal() as session:
        assert session.get(Video, video_id) is None


def test_delete_missing_video_returns_404(auth_headers):
    resp = client.delete("/videos/999999", headers=auth_headers)
    assert resp.status_code == 404


def test_list_requires_auth():
    resp = client.get("/videos")
    assert resp.status_code == 401


def test_delete_requires_auth(seeded_rows):
    resp = client.delete(f"/videos/{seeded_rows['ids']['recent_upload']}")
    assert resp.status_code == 401
