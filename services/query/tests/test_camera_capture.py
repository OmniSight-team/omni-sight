"""OMNI-312: starting and stopping a camera's capture, and listing its frames.

Requires Postgres to be up with `alembic upgrade head` applied. Ingestion is
faked at the client boundary (`cameras.ingestion_start_worker` and
`ingestion_stop_worker`), which proves query's own logic: who may start a
camera, what happens to the camera's status, what a refusal looks like, that
disabling or removing a camera stops its worker, and what the frames endpoint
returns. The worker itself is covered by
services/ingestion/tests/test_live_capture.py, and the whole chain ran live
against the simulator (docs/context/week-03-04.md).
"""

import pytest
from app import cameras as cameras_module
from app.db import SessionLocal
from app.ingestion_client import IngestionUnavailableError
from app.main import app
from app.models import Camera, Segment, User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import (
    CameraStatus,
    Domain,
    Role,
    SegmentSourceType,
    VideoSource,
    VideoStatus,
)

client = TestClient(app)

PASSWORD = "Omni312Pass!"
EMAILS = {
    Role.ADMIN: "omni312-admin@omnisight.local",
    Role.OPERATOR: "omni312-operator@omnisight.local",
    Role.ANALYST: "omni312-analyst@omnisight.local",
}
NAME_PREFIX = "omni312-"
RTSP = "rtsp://mediamtx:8554/cam01"


@pytest.fixture(scope="module", autouse=True)
def omni312_users():
    with SessionLocal() as session:
        session.add_all(
            User(email=email, password_hash=hash_password(PASSWORD), role=role, is_active=True)
            for role, email in EMAILS.items()
        )
        session.commit()
    yield
    with SessionLocal() as session:
        session.query(User).filter(User.email.in_(EMAILS.values())).delete(synchronize_session=False)
        session.commit()


def _headers(role):
    resp = client.post("/auth/login", json={"email": EMAILS[role], "password": PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def operator():
    return _headers(Role.OPERATOR)


@pytest.fixture
def admin():
    return _headers(Role.ADMIN)


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with SessionLocal() as session:
        ids = [c.id for c in session.query(Camera).filter(Camera.name.like(f"{NAME_PREFIX}%"))]
        session.query(Segment).filter(Segment.camera_id.in_(ids)).delete(synchronize_session=False)
        session.query(Video).filter(Video.camera_id.in_(ids)).delete(synchronize_session=False)
        session.query(Camera).filter(Camera.id.in_(ids)).delete(synchronize_session=False)
        session.commit()


class FakeIngestion:
    """Records what query asked ingestion to do, and answers as scripted."""

    def __init__(self, monkeypatch, start=None, stop=None, down=False):
        self.started, self.stopped = [], []
        self._start = start or {
            "ok": True, "worker_id": "worker-1", "status": "running",
            "error": None, "already_running": False,
        }
        self._stop = stop or {"ok": True, "status": "stopped", "was_running": True}
        self._down = down
        monkeypatch.setattr(cameras_module, "ingestion_start_worker", self.start)
        monkeypatch.setattr(cameras_module, "ingestion_stop_worker", self.stop)

    def start(self, camera_id, rtsp_url):
        if self._down:
            raise IngestionUnavailableError("connection refused")
        self.started.append((camera_id, rtsp_url))
        return self._start

    def stop(self, camera_id):
        self.stopped.append(camera_id)
        if self._down:
            raise IngestionUnavailableError("connection refused")
        return self._stop


def _camera(name="cam", status=CameraStatus.CONNECTED) -> int:
    with SessionLocal() as session:
        camera = Camera(
            name=f"{NAME_PREFIX}{name}", rtsp_url=RTSP, location="test", group_name="test",
            domain=Domain.SURVEILLANCE, status=status,
        )
        session.add(camera)
        session.commit()
        return camera.id


def _camera_row(camera_id) -> Camera:
    with SessionLocal() as session:
        return session.get(Camera, camera_id)


# --- start -------------------------------------------------------------------


def test_starting_a_camera_returns_its_worker_and_marks_it_connected(operator, monkeypatch):
    fake = FakeIngestion(monkeypatch)
    camera_id = _camera(status=CameraStatus.REGISTERED)

    resp = client.post(f"/cameras/{camera_id}/start", headers=operator)

    assert resp.status_code == 200
    assert resp.json() == {"worker_id": "worker-1", "status": "running"}
    assert fake.started == [(camera_id, RTSP)]  # ingestion gets the camera's own stream address
    row = _camera_row(camera_id)
    assert row.status == CameraStatus.CONNECTED and row.last_seen_at is not None


def test_a_camera_that_cannot_be_reached_is_refused_with_the_reason_and_flagged(operator, monkeypatch):
    FakeIngestion(monkeypatch, start={
        "ok": False, "worker_id": None, "status": None,
        "error": "authentication failed", "already_running": False,
    })
    camera_id = _camera()

    resp = client.post(f"/cameras/{camera_id}/start", headers=operator)

    assert resp.status_code == 502
    assert resp.json()["detail"] == "could not start capture: authentication failed"
    assert _camera_row(camera_id).status == CameraStatus.UNREACHABLE


def test_a_camera_already_being_captured_is_a_conflict(operator, monkeypatch):
    FakeIngestion(monkeypatch, start={
        "ok": False, "worker_id": "worker-1", "status": "running",
        "error": "camera is already being captured", "already_running": True,
    })
    camera_id = _camera()

    resp = client.post(f"/cameras/{camera_id}/start", headers=operator)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "camera is already being captured"
    assert _camera_row(camera_id).status == CameraStatus.CONNECTED  # a healthy camera is not flagged


def test_a_disabled_camera_is_never_started(operator, monkeypatch):
    fake = FakeIngestion(monkeypatch)
    camera_id = _camera(status=CameraStatus.DISABLED)

    resp = client.post(f"/cameras/{camera_id}/start", headers=operator)

    assert resp.status_code == 409
    assert resp.json()["detail"] == "camera is disabled"
    assert fake.started == []


def test_ingestion_being_down_is_a_502_and_leaves_the_camera_alone(operator, monkeypatch):
    FakeIngestion(monkeypatch, down=True)
    camera_id = _camera(status=CameraStatus.REGISTERED)

    resp = client.post(f"/cameras/{camera_id}/start", headers=operator)

    assert resp.status_code == 502
    assert resp.json()["detail"] == "ingestion service unavailable"
    assert _camera_row(camera_id).status == CameraStatus.REGISTERED


def test_starting_a_missing_camera_is_a_404(operator, monkeypatch):
    FakeIngestion(monkeypatch)
    assert client.post("/cameras/2000000000/start", headers=operator).status_code == 404


@pytest.mark.parametrize("path", ["start", "stop"])
def test_starting_and_stopping_need_a_sign_in_and_an_operator_or_admin(path, monkeypatch):
    FakeIngestion(monkeypatch)
    camera_id = _camera()

    assert client.post(f"/cameras/{camera_id}/{path}").status_code == 401
    assert client.post(f"/cameras/{camera_id}/{path}", headers=_headers(Role.ANALYST)).status_code == 403
    assert client.post(f"/cameras/{camera_id}/{path}", headers=_headers(Role.OPERATOR)).status_code == 200
    assert client.post(f"/cameras/{camera_id}/{path}", headers=_headers(Role.ADMIN)).status_code == 200


# --- stop --------------------------------------------------------------------


def test_stopping_a_camera_asks_ingestion_to_stop_its_worker(operator, monkeypatch):
    fake = FakeIngestion(monkeypatch)
    camera_id = _camera()

    resp = client.post(f"/cameras/{camera_id}/stop", headers=operator)

    assert resp.status_code == 200
    assert resp.json() == {"status": "stopped"}
    assert fake.stopped == [camera_id]


def test_stopping_a_camera_that_is_not_being_captured_is_not_an_error(operator, monkeypatch):
    FakeIngestion(monkeypatch, stop={"ok": True, "status": "stopped", "was_running": False})
    camera_id = _camera()

    resp = client.post(f"/cameras/{camera_id}/stop", headers=operator)

    assert resp.status_code == 200 and resp.json() == {"status": "stopped"}


def test_a_stop_that_cannot_reach_ingestion_says_so_rather_than_claiming_it_stopped(operator, monkeypatch):
    FakeIngestion(monkeypatch, down=True)
    camera_id = _camera()

    assert client.post(f"/cameras/{camera_id}/stop", headers=operator).status_code == 502


def test_stopping_a_missing_camera_is_a_404(operator, monkeypatch):
    FakeIngestion(monkeypatch)
    assert client.post("/cameras/2000000000/stop", headers=operator).status_code == 404


# --- disabling or removing a camera ends its capture ----------------------------


def test_disabling_a_camera_stops_its_worker(admin, monkeypatch):
    fake = FakeIngestion(monkeypatch)
    camera_id = _camera()

    resp = client.patch(f"/cameras/{camera_id}", json={"status": "disabled"}, headers=admin)

    assert resp.status_code == 200
    assert fake.stopped == [camera_id]


def test_editing_a_camera_without_disabling_it_leaves_its_worker_running(admin, monkeypatch):
    fake = FakeIngestion(monkeypatch)
    camera_id = _camera()

    client.patch(f"/cameras/{camera_id}", json={"location": "elsewhere"}, headers=admin)

    assert fake.stopped == []


def test_removing_a_camera_stops_its_worker_first(admin, monkeypatch):
    fake = FakeIngestion(monkeypatch)
    camera_id = _camera()

    resp = client.delete(f"/cameras/{camera_id}", headers=admin)

    assert resp.status_code == 200 and resp.json()["deleted"] is True
    assert fake.stopped == [camera_id]


def test_removing_a_camera_still_works_when_ingestion_cannot_be_reached(admin, monkeypatch):
    FakeIngestion(monkeypatch, down=True)
    camera_id = _camera()

    resp = client.delete(f"/cameras/{camera_id}", headers=admin)

    assert resp.status_code == 200 and resp.json()["deleted"] is True


# --- frames --------------------------------------------------------------------


def _segment(camera_id, timestamp_s, *, admitted=True, thumb=True, video_id=None, session_dir="1790"):
    with SessionLocal() as session:
        session.add(
            Segment(
                camera_id=camera_id,
                video_id=video_id,
                frame_index=int(timestamp_s) % 100000,
                timestamp_s=timestamp_s,
                frame_path=f"/data/frames/camera-{camera_id}/{session_dir}/{int(timestamp_s):06d}.jpg" if thumb else None,
                thumb_path=f"{settings.thumbs_path}/camera-{camera_id}/{session_dir}/{int(timestamp_s):06d}.jpg" if thumb else None,
                motion_score=1.0,
                admitted=admitted,
                source_type=SegmentSourceType.CAMERA,
            )
        )
        session.commit()


def test_frames_after_a_timestamp_come_back_oldest_first(operator):
    camera_id = _camera()
    for t in (1000.5, 1001.5, 1002.5, 1003.5):
        _segment(camera_id, t)

    resp = client.get(f"/cameras/{camera_id}/frames?since=1001.5", headers=operator)

    assert resp.status_code == 200
    assert [f["timestamp_s"] for f in resp.json()] == [1002.5, 1003.5]  # strictly after, ascending


def test_without_since_the_newest_frames_come_back_in_order(operator):
    camera_id = _camera()
    for t in (1000.5, 1001.5, 1002.5, 1003.5):
        _segment(camera_id, t)

    resp = client.get(f"/cameras/{camera_id}/frames?limit=2", headers=operator)

    assert [f["timestamp_s"] for f in resp.json()] == [1002.5, 1003.5]  # the newest two, oldest first


def test_a_client_that_keeps_the_last_timestamp_sees_each_frame_once(operator):
    camera_id = _camera()
    for t in (1000.5, 1001.5, 1002.5):
        _segment(camera_id, t)

    first = client.get(f"/cameras/{camera_id}/frames", headers=operator).json()
    _segment(camera_id, 1003.5)
    second = client.get(f"/cameras/{camera_id}/frames?since={first[-1]['timestamp_s']}", headers=operator).json()
    third = client.get(f"/cameras/{camera_id}/frames?since={second[-1]['timestamp_s']}", headers=operator).json()

    assert [f["timestamp_s"] for f in first] == [1000.5, 1001.5, 1002.5]
    assert [f["timestamp_s"] for f in second] == [1003.5]
    assert third == []


def test_a_frame_lists_its_segment_id_and_a_thumbnail_url_nginx_can_serve(operator):
    camera_id = _camera()
    _segment(camera_id, 1000.5, session_dir="1790")

    (frame,) = client.get(f"/cameras/{camera_id}/frames", headers=operator).json()

    assert set(frame) == {"segment_id", "timestamp_s", "thumb_url"}
    assert frame["thumb_url"] == f"/thumbs/camera-{camera_id}/1790/001000.jpg"
    with SessionLocal() as session:
        assert session.get(Segment, frame["segment_id"]).camera_id == camera_id


def test_only_this_cameras_live_admitted_frames_are_listed(operator):
    camera_id, other = _camera("a"), _camera("b")
    _segment(camera_id, 1000.5)  # the one that counts
    _segment(camera_id, 1001.5, admitted=False, thumb=False)  # discarded: no thumbnail
    _segment(other, 1002.5)  # someone else's
    with SessionLocal() as session:  # a recording made from this camera is a video, not live
        video = Video(
            filename=f"{NAME_PREFIX}rec.mp4", path="/x.mp4", source=VideoSource.CAMERA,
            camera_id=camera_id, size_bytes=1, status=VideoStatus.READY,
        )
        session.add(video)
        session.commit()
        video_id = video.id
    _segment(camera_id, 1003.5, video_id=video_id)

    frames = client.get(f"/cameras/{camera_id}/frames", headers=operator).json()

    assert [f["timestamp_s"] for f in frames] == [1000.5]


def test_frames_of_a_missing_camera_are_a_404_and_bad_parameters_a_422(operator):
    assert client.get("/cameras/2000000000/frames", headers=operator).status_code == 404
    camera_id = _camera()
    assert client.get(f"/cameras/{camera_id}/frames?since=-1", headers=operator).status_code == 422
    assert client.get(f"/cameras/{camera_id}/frames?limit=0", headers=operator).status_code == 422
    assert client.get(f"/cameras/{camera_id}/frames?limit=501", headers=operator).status_code == 422


def test_frames_need_a_sign_in_and_an_operator_or_admin():
    camera_id = _camera()

    assert client.get(f"/cameras/{camera_id}/frames").status_code == 401
    assert client.get(f"/cameras/{camera_id}/frames", headers=_headers(Role.ANALYST)).status_code == 403
    assert client.get(f"/cameras/{camera_id}/frames", headers=_headers(Role.OPERATOR)).status_code == 200
