"""OMNI-203: camera CRUD, admin-only writes.

Requires Postgres to be up (`docker compose up -d`).
"""

import pytest
from app.db import SessionLocal
from app.main import app
from app.models import Camera, User, Video
from app.security import hash_password
from fastapi.testclient import TestClient
from omnisight_common import CameraStatus, Domain, Role, VideoSource, VideoStatus

client = TestClient(app)

TEST_PASSWORD = "Omni203Pass!"
ADMIN_EMAIL = "omni203-admin@omnisight.local"
OPERATOR_EMAIL = "omni203-operator@omnisight.local"

CAMERA_PAYLOAD = {
    "name": "Dock camera",
    "rtsp_url": "rtsp://mediamtx:8554/cam01",
    "location": "North dock",
    "group": "dock",
    "domain": Domain.SURVEILLANCE.value,
}


@pytest.fixture(scope="module", autouse=True)
def omni203_users():
    with SessionLocal() as session:
        session.add_all(
            [
                User(
                    email=ADMIN_EMAIL,
                    password_hash=hash_password(TEST_PASSWORD),
                    role=Role.ADMIN,
                    is_active=True,
                ),
                User(
                    email=OPERATOR_EMAIL,
                    password_hash=hash_password(TEST_PASSWORD),
                    role=Role.OPERATOR,
                    is_active=True,
                ),
            ]
        )
        session.commit()

    yield

    with SessionLocal() as session:
        session.query(User).filter(User.email.in_([ADMIN_EMAIL, OPERATOR_EMAIL])).delete(
            synchronize_session=False
        )
        session.commit()


@pytest.fixture(autouse=True)
def cleanup_cameras():
    yield
    with SessionLocal() as session:
        session.query(Video).delete()
        session.query(Camera).delete()
        session.commit()


@pytest.fixture(scope="module")
def admin_token():
    resp = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture(scope="module")
def operator_token():
    resp = client.post("/auth/login", json={"email": OPERATOR_EMAIL, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Acceptance: an admin can register and remove a camera ---


def test_admin_create_camera_starts_registered(admin_token):
    resp = client.post("/cameras", json=CAMERA_PAYLOAD, headers=_auth(admin_token))
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == CameraStatus.REGISTERED.value

    with SessionLocal() as session:
        camera = session.get(Camera, body["id"])
        # never stored under the reserved word "group"
        assert camera.group_name == "dock"
        assert camera.rtsp_url == CAMERA_PAYLOAD["rtsp_url"]


def test_admin_list_includes_created_camera(admin_token):
    create_resp = client.post("/cameras", json=CAMERA_PAYLOAD, headers=_auth(admin_token))
    camera_id = create_resp.json()["id"]

    resp = client.get("/cameras", headers=_auth(admin_token))
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert camera_id in ids
    listed = next(row for row in resp.json() if row["id"] == camera_id)
    assert listed["group"] == "dock"


def test_admin_patch_camera(admin_token):
    create_resp = client.post("/cameras", json=CAMERA_PAYLOAD, headers=_auth(admin_token))
    camera_id = create_resp.json()["id"]

    resp = client.patch(f"/cameras/{camera_id}", json={"location": "South dock"}, headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()["location"] == "South dock"


def test_admin_hard_deletes_camera_with_no_recordings(admin_token):
    create_resp = client.post("/cameras", json=CAMERA_PAYLOAD, headers=_auth(admin_token))
    camera_id = create_resp.json()["id"]

    resp = client.delete(f"/cameras/{camera_id}", headers=_auth(admin_token))
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    with SessionLocal() as session:
        assert session.get(Camera, camera_id) is None


def test_admin_delete_soft_deletes_camera_referenced_by_a_video(admin_token):
    create_resp = client.post("/cameras", json=CAMERA_PAYLOAD, headers=_auth(admin_token))
    camera_id = create_resp.json()["id"]

    with SessionLocal() as session:
        session.add(
            Video(
                filename="clip.mp4",
                path="/data/videos/clip.mp4",
                camera_id=camera_id,
                source=VideoSource.CAMERA,
                size_bytes=1024,
                status=VideoStatus.READY,
            )
        )
        session.commit()

    resp = client.delete(f"/cameras/{camera_id}", headers=_auth(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["deleted"] is False
    assert body["status"] == CameraStatus.DISABLED.value

    with SessionLocal() as session:
        camera = session.get(Camera, camera_id)
        assert camera is not None
        assert camera.status == CameraStatus.DISABLED


# --- Acceptance: an operator can see them and nothing else, proven by a test ---


def test_operator_list_returns_200(operator_token):
    resp = client.get("/cameras", headers=_auth(operator_token))
    assert resp.status_code == 200


def test_operator_create_returns_403(operator_token):
    resp = client.post("/cameras", json=CAMERA_PAYLOAD, headers=_auth(operator_token))
    assert resp.status_code == 403


def test_operator_patch_returns_403(admin_token, operator_token):
    create_resp = client.post("/cameras", json=CAMERA_PAYLOAD, headers=_auth(admin_token))
    camera_id = create_resp.json()["id"]

    resp = client.patch(f"/cameras/{camera_id}", json={"location": "Elsewhere"}, headers=_auth(operator_token))
    assert resp.status_code == 403


def test_operator_delete_returns_403(admin_token, operator_token):
    create_resp = client.post("/cameras", json=CAMERA_PAYLOAD, headers=_auth(admin_token))
    camera_id = create_resp.json()["id"]

    resp = client.delete(f"/cameras/{camera_id}", headers=_auth(operator_token))
    assert resp.status_code == 403
