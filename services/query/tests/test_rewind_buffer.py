"""OMNI-505: a camera's rewind buffer, which is its stored admitted frames, and
the full frame behind each one.

Requires Postgres with `alembic upgrade head`. The frames are rows written here,
with real files for the image route; the whole thing ran against a live camera
on the real stack (docs/context/week-05.md, OMNI-505).
"""

import time
from pathlib import Path

import pytest
from app.db import SessionLocal
from app.main import app
from app.models import Camera, Segment, User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import (
    AdmissionReason,
    CameraStatus,
    Domain,
    Role,
    SegmentSourceType,
    VideoSource,
    VideoStatus,
)

client = TestClient(app)

PASSWORD = "Omni505Pass!"
EMAILS = {
    Role.ADMIN: "omni505-admin@omnisight.local",
    Role.OPERATOR: "omni505-operator@omnisight.local",
    Role.ANALYST: "omni505-analyst@omnisight.local",
}
NAME_PREFIX = "omni505-"


@pytest.fixture(scope="module", autouse=True)
def omni505_users():
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


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with SessionLocal() as session:
        ids = [c.id for c in session.query(Camera).filter(Camera.name.like(f"{NAME_PREFIX}%"))]
        session.query(Segment).filter(Segment.camera_id.in_(ids)).delete(synchronize_session=False)
        session.query(Video).filter(Video.camera_id.in_(ids)).delete(synchronize_session=False)
        session.query(Camera).filter(Camera.id.in_(ids)).delete(synchronize_session=False)
        session.commit()


def _headers(role):
    resp = client.post("/auth/login", json={"email": EMAILS[role], "password": PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def operator():
    return _headers(Role.OPERATOR)


@pytest.fixture
def frames(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "frames_path", str(tmp_path))
    return tmp_path


def _camera(name="cam") -> int:
    with SessionLocal() as session:
        camera = Camera(
            name=f"{NAME_PREFIX}{name}", rtsp_url="rtsp://mediamtx:8554/cam05", location="test",
            group_name="test", domain=Domain.SURVEILLANCE, status=CameraStatus.CONNECTED,
        )
        session.add(camera)
        session.commit()
        return camera.id


_index = iter(range(10**6))


def _frame(camera_id, ago_s, *, reason=AdmissionReason.MOTION, admitted=True, video_id=None, write_file=None) -> int:
    """A stored live frame captured `ago_s` seconds ago. `write_file` (a folder)
    also writes its JPEG there."""
    timestamp_s = time.time() - ago_s
    index = next(_index)
    frame_path = thumb_path = None
    if admitted:
        root = write_file or settings.frames_path
        frame_path = f"{root}/camera-{camera_id}/1/{index:06d}.jpg"
        thumb_path = f"{settings.thumbs_path}/camera-{camera_id}/1/{index:06d}.jpg"
        if write_file is not None:
            Path(frame_path).parent.mkdir(parents=True, exist_ok=True)
            Path(frame_path).write_bytes(b"\xff\xd8 frame %d \xff\xd9" % index)
    with SessionLocal() as session:
        segment = Segment(
            camera_id=camera_id, video_id=video_id, frame_index=index, timestamp_s=timestamp_s,
            frame_path=frame_path, thumb_path=thumb_path, motion_score=5.0 if reason == AdmissionReason.MOTION else 0.0,
            admitted=admitted, admission_reason=reason if admitted else None, source_type=SegmentSourceType.CAMERA,
            clip_start_s=timestamp_s - 1.0 if admitted else None, clip_end_s=timestamp_s if admitted else None,
        )
        session.add(segment)
        session.commit()
        return segment.id


# --- the window ---------------------------------------------------------------------


def test_the_buffer_is_the_last_five_minutes_of_admitted_frames_oldest_first(operator):
    camera_id = _camera()
    inside = [_frame(camera_id, ago) for ago in (290, 200, 100, 10, 1)]
    _frame(camera_id, 310)  # before the window
    _frame(camera_id, 900)

    resp = client.get(f"/cameras/{camera_id}/buffer", headers=operator)

    assert resp.status_code == 200
    body = resp.json()
    assert [f["segment_id"] for f in body] == inside  # oldest first, nothing older than 5 minutes
    times = [f["timestamp_s"] for f in body]
    assert times == sorted(times)
    assert all(time.time() - t <= 300 for t in times)


def test_minutes_sets_the_window(operator):
    camera_id = _camera()
    recent = _frame(camera_id, 30)
    older = _frame(camera_id, 90)
    oldest = _frame(camera_id, 500)

    one = [f["segment_id"] for f in client.get(f"/cameras/{camera_id}/buffer?minutes=1", headers=operator).json()]
    ten = [f["segment_id"] for f in client.get(f"/cameras/{camera_id}/buffer?minutes=10", headers=operator).json()]

    assert one == [recent]
    assert ten == [oldest, older, recent]


def test_minutes_is_limited_to_one_to_ten(operator):
    camera_id = _camera()

    for bad in ("0", "11", "-1", "five"):
        assert client.get(f"/cameras/{camera_id}/buffer?minutes={bad}", headers=operator).status_code == 422
    for good in ("1", "10"):
        assert client.get(f"/cameras/{camera_id}/buffer?minutes={good}", headers=operator).status_code == 200


def test_only_admitted_live_frames_of_this_camera_are_in_it(operator):
    camera_id = _camera()
    other = _camera("other")
    mine = _frame(camera_id, 20)
    _frame(camera_id, 15, admitted=False)  # a discarded row (none are stored live since OMNI-501)
    _frame(other, 10)
    with SessionLocal() as session:
        video = Video(filename=f"{NAME_PREFIX}rec.mp4", path="/x.mp4", source=VideoSource.UPLOAD, size_bytes=1,
                      status=VideoStatus.READY, camera_id=camera_id)
        session.add(video)
        session.commit()
        video_id = video.id
    _frame(camera_id, 5, video_id=video_id)  # a recording made from this camera, not its live buffer

    body = client.get(f"/cameras/{camera_id}/buffer", headers=operator).json()

    assert [f["segment_id"] for f in body] == [mine]


def test_each_frame_says_why_it_was_kept_and_where_its_images_are(operator):
    camera_id = _camera()
    motion = _frame(camera_id, 20, reason=AdmissionReason.MOTION)
    heartbeat = _frame(camera_id, 10, reason=AdmissionReason.HEARTBEAT)

    body = client.get(f"/cameras/{camera_id}/buffer", headers=operator).json()

    assert [(f["segment_id"], f["reason"]) for f in body] == [(motion, "motion"), (heartbeat, "heartbeat")]
    first = body[0]
    assert set(first) == {"segment_id", "timestamp_s", "reason", "thumb_url", "frame_url"}
    assert first["thumb_url"].startswith(f"{settings.thumb_url_prefix}/camera-{camera_id}/")
    assert first["frame_url"] == f"/cameras/{camera_id}/frames/{motion}/image"


def test_an_empty_buffer_is_an_empty_list(operator):
    camera_id = _camera()

    assert client.get(f"/cameras/{camera_id}/buffer", headers=operator).json() == []


def test_the_buffer_of_a_missing_camera_is_a_404(operator):
    assert client.get("/cameras/2000000000/buffer", headers=operator).status_code == 404


def test_the_buffer_is_for_operators_and_admins():
    camera_id = _camera()

    assert client.get(f"/cameras/{camera_id}/buffer").status_code == 401
    assert client.get(f"/cameras/{camera_id}/buffer", headers=_headers(Role.ANALYST)).status_code == 403
    assert client.get(f"/cameras/{camera_id}/buffer", headers=_headers(Role.ADMIN)).status_code == 200


# --- the full frame -----------------------------------------------------------------


def test_frame_url_serves_the_full_frame_with_the_token(operator, frames):
    camera_id = _camera()
    segment_id = _frame(camera_id, 10, write_file=frames)
    frame_url = client.get(f"/cameras/{camera_id}/buffer", headers=operator).json()[0]["frame_url"]

    resp = client.get(frame_url, headers=operator)

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content.startswith(b"\xff\xd8") and resp.content.endswith(b"\xff\xd9")
    assert client.get(frame_url).status_code == 401
    assert client.get(frame_url, headers=_headers(Role.ANALYST)).status_code == 403
    assert segment_id in [int(part) for part in frame_url.split("/") if part.isdigit()]


def test_a_frame_of_another_camera_or_without_a_file_is_a_404(operator, frames):
    camera_id = _camera()
    other = _camera("other2")
    theirs = _frame(other, 10, write_file=frames)
    missing_file = _frame(camera_id, 5)  # a row whose file is not on disk

    assert client.get(f"/cameras/{camera_id}/frames/{theirs}/image", headers=operator).status_code == 404
    assert client.get(f"/cameras/{camera_id}/frames/{missing_file}/image", headers=operator).status_code == 404
    assert client.get(f"/cameras/{camera_id}/frames/2000000000/image", headers=operator).status_code == 404


def test_a_frame_path_outside_the_frames_folder_is_never_served(operator, frames, tmp_path_factory):
    camera_id = _camera()
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    segment_id = _frame(camera_id, 5, write_file=elsewhere)  # a file that exists, but not under frames_path

    assert client.get(f"/cameras/{camera_id}/frames/{segment_id}/image", headers=operator).status_code == 404
