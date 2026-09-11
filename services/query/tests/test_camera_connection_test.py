"""OMNI-204: /cameras/{id}/test updates status and last_seen_at from
ingestion's result.

ingestion_client.probe_stream is monkeypatched here — this file proves the
route's own status-transition logic, not the real RTSP handshake. That real
behavior (unreachable, authentication failed, timeout, a genuine simulator
feed) was verified live against the running containers; see
docs/context/week-02.md.

Requires Postgres to be up (`docker compose up -d`).
"""

import pytest
from app import cameras as cameras_module
from app.db import SessionLocal
from app.ingestion_client import IngestionUnavailableError
from app.main import app
from app.models import Camera, User
from app.security import hash_password
from fastapi.testclient import TestClient
from omnisight_common import CameraStatus, Domain, Role

client = TestClient(app)

TEST_PASSWORD = "Omni204Pass!"
ADMIN_EMAIL = "omni204-admin@omnisight.local"

CAMERA_PAYLOAD = {
    "name": "Connection test cam",
    "rtsp_url": "rtsp://mediamtx:8554/cam05",
    "location": "Test bench",
    "group": "bench",
    "domain": Domain.SURVEILLANCE.value,
}


@pytest.fixture(scope="module", autouse=True)
def omni204_admin():
    with SessionLocal() as session:
        session.add(
            User(
                email=ADMIN_EMAIL,
                password_hash=hash_password(TEST_PASSWORD),
                role=Role.ADMIN,
                is_active=True,
            )
        )
        session.commit()

    yield

    with SessionLocal() as session:
        session.query(User).filter_by(email=ADMIN_EMAIL).delete(synchronize_session=False)
        session.commit()


@pytest.fixture
def admin_token():
    resp = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture
def camera(admin_token):
    resp = client.post("/cameras", json=CAMERA_PAYLOAD, headers={"Authorization": f"Bearer {admin_token}"})
    camera_id = resp.json()["id"]
    yield camera_id
    with SessionLocal() as session:
        session.query(Camera).filter_by(id=camera_id).delete(synchronize_session=False)
        session.commit()


def test_reachable_flips_camera_to_connected(admin_token, camera, monkeypatch):
    monkeypatch.setattr(
        cameras_module,
        "ingestion_probe_stream",
        lambda rtsp_url: {"reachable": True, "resolution": "640x360", "fps": 15.0, "error": None},
    )

    resp = client.post(f"/cameras/{camera}/test", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"reachable": True, "resolution": "640x360", "fps": 15.0, "error": None}

    with SessionLocal() as session:
        row = session.get(Camera, camera)
        assert row.status == CameraStatus.CONNECTED
        assert row.last_seen_at is not None


def test_unreachable_flips_camera_to_unreachable_without_last_seen(admin_token, camera, monkeypatch):
    monkeypatch.setattr(
        cameras_module,
        "ingestion_probe_stream",
        lambda rtsp_url: {"reachable": False, "resolution": None, "fps": None, "error": "unreachable"},
    )

    resp = client.post(f"/cameras/{camera}/test", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 200
    assert resp.json()["error"] == "unreachable"

    with SessionLocal() as session:
        row = session.get(Camera, camera)
        assert row.status == CameraStatus.UNREACHABLE
        assert row.last_seen_at is None


@pytest.mark.parametrize("reason", ["unreachable", "authentication failed", "timeout"])
def test_each_failure_reason_is_returned_verbatim(admin_token, camera, monkeypatch, reason):
    monkeypatch.setattr(
        cameras_module,
        "ingestion_probe_stream",
        lambda rtsp_url: {"reachable": False, "resolution": None, "fps": None, "error": reason},
    )

    resp = client.post(f"/cameras/{camera}/test", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.json()["error"] == reason


def test_missing_camera_returns_404(admin_token):
    resp = client.post("/cameras/999999/test", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 404


def test_ingestion_unavailable_returns_502(admin_token, camera, monkeypatch):
    def _raise(rtsp_url):
        raise IngestionUnavailableError("connection refused")

    monkeypatch.setattr(cameras_module, "ingestion_probe_stream", _raise)

    resp = client.post(f"/cameras/{camera}/test", headers={"Authorization": f"Bearer {admin_token}"})
    assert resp.status_code == 502
