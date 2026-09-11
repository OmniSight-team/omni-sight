"""OMNI-206: probe an uploaded file with OpenCV.

Requires Postgres to be up (`docker compose up -d`). ingestion_client.probe_file
is monkeypatched here — this file proves the route's own status-transition
logic (ready / failed / left as uploaded when ingestion itself is down), not
the real OpenCV decode. That real behavior — a known-length mp4 probed to
the exact duration, and a truncated file failing cleanly with a reason —
was verified live against the running containers; see docs/context/week-02.md.
"""

import pytest
from app import videos as videos_module
from app.db import SessionLocal
from app.ingestion_client import IngestionUnavailableError
from app.main import app
from app.models import User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import Role, VideoStatus

client = TestClient(app)

TEST_PASSWORD = "Omni206Pass!"
OPERATOR_EMAIL = "omni206-operator@omnisight.local"

MP4_HEADER = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2mp41" + b"\x00" * 12


@pytest.fixture(scope="module", autouse=True)
def omni206_user():
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


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "video_storage_path", str(tmp_path))
    yield
    with SessionLocal() as session:
        session.query(Video).delete()
        session.commit()


def _upload(auth_headers, filename="clip.mp4"):
    resp = client.post(
        "/videos/upload",
        files={"file": (filename, MP4_HEADER, "video/mp4")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    return resp.json()


def test_successful_probe_moves_status_to_ready(auth_headers, monkeypatch):
    monkeypatch.setattr(
        videos_module,
        "ingestion_probe_file",
        lambda path: {"ok": True, "duration_s": 12.5, "fps": 25.0, "width": 1280, "height": 720},
    )

    body = _upload(auth_headers)
    assert body["status"] == VideoStatus.READY.value
    assert body["duration_s"] == 12.5
    assert body["fps"] == 25.0
    assert body["error"] is None

    with SessionLocal() as session:
        row = session.get(Video, body["id"])
        assert row.status == VideoStatus.READY
        assert row.width == 1280
        assert row.height == 720


def test_probe_failure_moves_status_to_failed_with_reason(auth_headers, monkeypatch):
    monkeypatch.setattr(
        videos_module,
        "ingestion_probe_file",
        lambda path: {"ok": False, "error": "could not open file"},
    )

    body = _upload(auth_headers)
    assert body["status"] == VideoStatus.FAILED.value
    assert body["duration_s"] is None
    assert body["error"] == "could not open file"

    with SessionLocal() as session:
        row = session.get(Video, body["id"])
        assert row.status == VideoStatus.FAILED
        # a failed video is never removed and never crashes the request —
        # it stays visible, exactly as a "corrupt file" is supposed to.
        assert row is not None


def test_ingestion_unavailable_leaves_video_uploaded_not_failed(auth_headers, monkeypatch):
    def _raise(path):
        raise IngestionUnavailableError("connection refused")

    monkeypatch.setattr(videos_module, "ingestion_probe_file", _raise)

    body = _upload(auth_headers)
    # an infrastructure hiccup isn't the same claim as "this file is bad" —
    # the video stays uploaded, not failed, so a retry has something to retry.
    assert body["status"] == VideoStatus.UPLOADED.value
    assert body["error"] == "ingestion service unavailable"


def test_get_video_returns_full_record_with_zero_segments(auth_headers, monkeypatch):
    monkeypatch.setattr(
        videos_module,
        "ingestion_probe_file",
        lambda path: {"ok": True, "duration_s": 5.0, "fps": 30.0, "width": 640, "height": 360},
    )
    uploaded = _upload(auth_headers, filename="detail.mp4")

    resp = client.get(f"/videos/{uploaded['id']}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "detail.mp4"
    assert body["status"] == VideoStatus.READY.value
    assert body["duration_s"] == 5.0
    assert body["width"] == 640
    assert body["height"] == 360
    assert body["segments_count"] == 0
    assert body["camera_id"] is None


def test_get_video_missing_returns_404(auth_headers):
    resp = client.get("/videos/999999", headers=auth_headers)
    assert resp.status_code == 404


def test_get_video_requires_auth(auth_headers, monkeypatch):
    monkeypatch.setattr(videos_module, "ingestion_probe_file", lambda path: {"ok": False, "error": "x"})
    uploaded = _upload(auth_headers)

    resp = client.get(f"/videos/{uploaded['id']}")
    assert resp.status_code == 401
