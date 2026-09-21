"""OMNI-302: segments and camera_stats tables.

Requires Postgres to be up (`docker compose up -d`) with `alembic upgrade head`
applied. Files are created under a pytest tmp_path — this suite proves the
delete logic (rows gone, files gone, neighbours untouched), not the volume
mount. Cleanup is targeted at the rows each test creates, so it never touches
other tests' data.
"""

from pathlib import Path

import pytest
from app.db import SessionLocal
from app.main import app
from app.models import Camera, CameraStats, Segment, User, Video
from app.security import hash_password
from fastapi.testclient import TestClient
from omnisight_common import (
    CameraStatus,
    Domain,
    Role,
    SegmentSourceType,
    VideoSource,
    VideoStatus,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

client = TestClient(app)

TEST_PASSWORD = "Omni302Pass!"
ADMIN_EMAIL = "omni302-admin@omnisight.local"
OPERATOR_EMAIL = "omni302-operator@omnisight.local"
NAME_PREFIX = "omni302-"


@pytest.fixture(scope="module", autouse=True)
def omni302_users():
    with SessionLocal() as session:
        for email, role in ((ADMIN_EMAIL, Role.ADMIN), (OPERATOR_EMAIL, Role.OPERATOR)):
            session.add(
                User(email=email, password_hash=hash_password(TEST_PASSWORD), role=role, is_active=True)
            )
        session.commit()

    yield

    with SessionLocal() as session:
        session.query(User).filter(User.email.in_([ADMIN_EMAIL, OPERATOR_EMAIL])).delete(
            synchronize_session=False
        )
        session.commit()


@pytest.fixture(autouse=True)
def clean_up_rows():
    yield
    with SessionLocal() as session:
        video_ids = [v.id for v in session.query(Video.id).filter(Video.filename.like(f"{NAME_PREFIX}%"))]
        camera_ids = [c.id for c in session.query(Camera.id).filter(Camera.name.like(f"{NAME_PREFIX}%"))]
        session.query(Segment).filter(
            Segment.video_id.in_(video_ids) | Segment.camera_id.in_(camera_ids)
        ).delete(synchronize_session=False)
        session.query(CameraStats).filter(CameraStats.camera_id.in_(camera_ids)).delete(
            synchronize_session=False
        )
        session.query(Video).filter(Video.id.in_(video_ids)).delete(synchronize_session=False)
        session.query(Camera).filter(Camera.id.in_(camera_ids)).delete(synchronize_session=False)
        session.commit()


def _headers(email: str) -> dict[str, str]:
    resp = client.post("/auth/login", json={"email": email, "password": TEST_PASSWORD})
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _make_camera(session, name: str = "cam") -> Camera:
    camera = Camera(
        name=f"{NAME_PREFIX}{name}",
        rtsp_url="rtsp://example.invalid/stream",
        location="test",
        group_name="test",
        domain=Domain.SURVEILLANCE,
        status=CameraStatus.REGISTERED,
    )
    session.add(camera)
    session.commit()
    return camera


def _make_video(session, directory: Path, name: str = "clip") -> Video:
    path = directory / f"{NAME_PREFIX}{name}.mp4"
    path.write_bytes(b"video bytes")
    video = Video(
        filename=f"{NAME_PREFIX}{name}.mp4",
        path=str(path),
        source=VideoSource.UPLOAD,
        size_bytes=path.stat().st_size,
        status=VideoStatus.READY,
    )
    session.add(video)
    session.commit()
    return video


def _make_segment(session, directory: Path, index: int, *, video_id=None, camera_id=None, source_type=None):
    frame = directory / f"frame_{video_id}_{camera_id}_{index}.jpg"
    thumb = directory / f"thumb_{video_id}_{camera_id}_{index}.jpg"
    frame.write_bytes(b"frame")
    thumb.write_bytes(b"thumb")
    segment = Segment(
        video_id=video_id,
        camera_id=camera_id,
        frame_index=index,
        timestamp_s=float(index),
        frame_path=str(frame),
        thumb_path=str(thumb),
        source_type=source_type or (SegmentSourceType.UPLOAD if video_id else SegmentSourceType.CAMERA),
    )
    session.add(segment)
    session.commit()
    return segment


def test_admitted_defaults_to_false_in_the_database(tmp_path):
    with SessionLocal() as session:
        video = _make_video(session, tmp_path)
        # A raw INSERT that never mentions `admitted`, so the default that
        # applies is the database's, not the ORM's.
        session.execute(
            text(
                "INSERT INTO segments (video_id, frame_index, timestamp_s, frame_path, thumb_path, source_type) "
                "VALUES (:v, 0, 0.0, 'f', 't', 'upload')"
            ),
            {"v": video.id},
        )
        session.commit()
        admitted = session.query(Segment.admitted).filter_by(video_id=video.id).scalar()
        assert admitted is False


def test_an_upload_segment_needs_no_camera_and_a_live_segment_needs_no_video(tmp_path):
    with SessionLocal() as session:
        video = _make_video(session, tmp_path)
        camera = _make_camera(session)

        upload = _make_segment(session, tmp_path, 0, video_id=video.id)
        live = _make_segment(session, tmp_path, 1, camera_id=camera.id)

        assert upload.camera_id is None
        assert upload.source_type == SegmentSourceType.UPLOAD
        assert live.video_id is None
        assert live.source_type == SegmentSourceType.CAMERA


def test_a_segment_with_neither_a_video_nor_a_camera_is_rejected(tmp_path):
    with SessionLocal() as session:
        session.add(
            Segment(
                frame_index=0,
                timestamp_s=0.0,
                frame_path="f",
                thumb_path="t",
                source_type=SegmentSourceType.UPLOAD,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_deleting_a_video_deletes_its_segments_and_their_files_and_nothing_else(tmp_path):
    with SessionLocal() as session:
        doomed = _make_video(session, tmp_path, "doomed")
        neighbour = _make_video(session, tmp_path, "neighbour")
        doomed_segments = [_make_segment(session, tmp_path, i, video_id=doomed.id) for i in range(3)]
        neighbour_segments = [_make_segment(session, tmp_path, i, video_id=neighbour.id) for i in range(2)]

        doomed_id = doomed.id
        neighbour_id = neighbour.id
        doomed_files = [Path(doomed.path)] + [
            Path(p) for s in doomed_segments for p in (s.frame_path, s.thumb_path)
        ]
        neighbour_files = [Path(neighbour.path)] + [
            Path(p) for s in neighbour_segments for p in (s.frame_path, s.thumb_path)
        ]

    resp = client.delete(f"/videos/{doomed_id}", headers=_headers(OPERATOR_EMAIL))
    assert resp.status_code == 200

    with SessionLocal() as session:
        assert session.get(Video, doomed_id) is None
        assert session.query(Segment).filter_by(video_id=doomed_id).count() == 0
        # the neighbour's rows are untouched
        assert session.query(Segment).filter_by(video_id=neighbour_id).count() == 2

    assert len(doomed_files) == 7
    assert [p for p in doomed_files if p.exists()] == []
    assert all(p.exists() for p in neighbour_files)


def test_deleting_a_video_still_succeeds_when_a_segment_file_is_already_gone(tmp_path):
    with SessionLocal() as session:
        video = _make_video(session, tmp_path)
        segment = _make_segment(session, tmp_path, 0, video_id=video.id)
        video_id = video.id
        Path(segment.thumb_path).unlink()

    resp = client.delete(f"/videos/{video_id}", headers=_headers(OPERATOR_EMAIL))
    assert resp.status_code == 200

    with SessionLocal() as session:
        assert session.query(Segment).filter_by(video_id=video_id).count() == 0


def test_a_camera_with_only_live_segments_is_disabled_not_deleted(tmp_path):
    with SessionLocal() as session:
        camera = _make_camera(session)
        _make_segment(session, tmp_path, 0, camera_id=camera.id)
        camera_id = camera.id

    resp = client.delete(f"/cameras/{camera_id}", headers=_headers(ADMIN_EMAIL))
    assert resp.status_code == 200
    assert resp.json()["deleted"] is False

    with SessionLocal() as session:
        assert session.get(Camera, camera_id).status == CameraStatus.DISABLED
        assert session.query(Segment).filter_by(camera_id=camera_id).count() == 1


def test_camera_stats_counters_start_at_zero(tmp_path):
    with SessionLocal() as session:
        camera = _make_camera(session)
        session.add(CameraStats(camera_id=camera.id))
        session.commit()

        stats = session.get(CameraStats, camera.id)
        assert stats.captured == 0
        assert stats.dropped == 0
        assert stats.last_frame_at is None


def test_camera_stats_row_is_deleted_with_its_camera(tmp_path):
    with SessionLocal() as session:
        camera = _make_camera(session)
        session.add(CameraStats(camera_id=camera.id, captured=5, dropped=1))
        session.commit()
        camera_id = camera.id

    resp = client.delete(f"/cameras/{camera_id}", headers=_headers(ADMIN_EMAIL))
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True

    with SessionLocal() as session:
        assert session.get(CameraStats, camera_id) is None
