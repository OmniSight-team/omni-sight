"""OMNI-610: the dashboard's rollup and its two endpoints.

Requires Postgres (`docker compose up -d`); runs on the test database (conftest). The
rollup is kept by triggers (D-28), so each test changes `segments` the way the product
does (the consumer's `store_segment`, a re-gate's update, a video's delete) and checks
that the rollup still equals a direct count over the whole table.
"""

import uuid
from datetime import UTC, datetime

import pytest
from app import dashboard as dashboard_module
from app.consumer import Outcome, store_segment
from app.db import SessionLocal
from app.main import app
from app.models import Camera, Segment, User, Video
from app.schemas import CameraLiveOut
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import Domain, Role, SegmentMessage, VideoSource, VideoStatus
from sqlalchemy import text

client = TestClient(app)

NAME_PREFIX = "omni610-"
RUN = "run-610"
TEST_PASSWORD = "Omni610Pass!"
EMAIL = "omni610-analyst@omnisight.local"


@pytest.fixture(scope="module", autouse=True)
def user():
    with SessionLocal() as session:
        session.add(User(email=EMAIL, password_hash=hash_password(TEST_PASSWORD), role=Role.ANALYST, is_active=True))
        session.commit()
    yield
    with SessionLocal() as session:
        session.query(User).filter(User.email == EMAIL).delete(synchronize_session=False)
        session.commit()


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with SessionLocal() as session:
        session.query(Video).filter(Video.filename.like(f"{NAME_PREFIX}%")).delete(synchronize_session=False)
        camera_ids = [c.id for c in session.query(Camera).filter(Camera.name.like(f"{NAME_PREFIX}%"))]
        session.query(Segment).filter(Segment.camera_id.in_(camera_ids)).delete(synchronize_session=False)
        session.query(Camera).filter(Camera.id.in_(camera_ids)).delete(synchronize_session=False)
        session.commit()


def _headers() -> dict[str, str]:
    resp = client.post("/auth/login", json={"email": EMAIL, "password": TEST_PASSWORD})
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _video(*, source=VideoSource.UPLOAD, size_bytes=1000) -> int:
    with SessionLocal() as session:
        video = Video(
            filename=f"{NAME_PREFIX}{uuid.uuid4().hex[:8]}.mp4",
            path="/nonexistent.mp4",
            source=source,
            size_bytes=size_bytes,
            status=VideoStatus.EXTRACTING,
            extraction_id=RUN,
        )
        session.add(video)
        session.commit()
        return video.id


def _camera() -> int:
    with SessionLocal() as session:
        camera = Camera(
            name=f"{NAME_PREFIX}{uuid.uuid4().hex[:8]}",
            rtsp_url="rtsp://example.invalid/x",
            location="lab",
            group_name="g",
            domain=Domain.SURVEILLANCE,
            status="registered",
        )
        session.add(camera)
        session.commit()
        return camera.id


def _store(video_id, index, *, admitted=False, file_bytes=0, camera_id=None) -> Outcome:
    message = SegmentMessage(
        video_id=video_id,
        camera_id=camera_id,
        frame_index=index,
        timestamp_s=index / 30,
        frame_path=f"/data/frames/{index}.jpg" if admitted else None,
        thumb_path=f"/data/thumbs/{index}.jpg" if admitted else None,
        motion_score=2.0,
        admitted=admitted,
        source_type="upload" if camera_id is None else "camera",
        admission_reason="motion" if admitted else None,
        file_bytes=file_bytes,
        extraction_id=RUN if video_id is not None else None,
    )
    return store_segment(message.model_dump_json().encode())


def _rollup_and_direct() -> tuple[tuple, tuple]:
    with SessionLocal() as db:
        rollup = db.execute(
            text(
                "SELECT source_type::text, sum(segments), sum(admitted), sum(file_bytes) "
                "FROM segment_hourly GROUP BY 1 ORDER BY 1"
            )
        ).all()
        direct = db.execute(
            text(
                "SELECT source_type::text, count(*), count(*) FILTER (WHERE admitted), sum(file_bytes) "
                "FROM segments GROUP BY 1 ORDER BY 1"
            )
        ).all()
    # A source whose rows are all gone keeps a rollup row of zeros; a direct count has none.
    return tuple(tuple(r) for r in rollup if r[1]), tuple(tuple(r) for r in direct)


def _totals() -> tuple[int, int, int]:
    with SessionLocal() as db:
        return tuple(
            db.execute(
                text(
                    "SELECT coalesce(sum(segments), 0), coalesce(sum(admitted), 0), "
                    "coalesce(sum(file_bytes), 0) FROM segment_hourly"
                )
            ).one()
        )


def _assert_rollup_exact():
    rollup, direct = _rollup_and_direct()
    assert rollup == direct


def test_a_stored_segment_is_counted_in_the_same_commit_and_a_redelivery_adds_nothing():
    _assert_rollup_exact()
    before = _totals()
    video_id = _video()

    assert _store(video_id, 0) == Outcome.STORED
    assert _store(video_id, 1, admitted=True, file_bytes=5000) == Outcome.STORED
    assert _store(video_id, 1, admitted=True, file_bytes=5000) == Outcome.DUPLICATE

    after = _totals()
    assert (after[0] - before[0], after[1] - before[1], after[2] - before[2]) == (2, 1, 5000)
    _assert_rollup_exact()


def test_a_live_frame_is_counted_under_its_own_source():
    camera_id = _camera()
    assert _store(None, 0, admitted=True, file_bytes=700, camera_id=camera_id) == Outcome.STORED
    _assert_rollup_exact()
    with SessionLocal() as db:
        camera_rows = db.execute(
            text("SELECT sum(segments) FROM segment_hourly WHERE source_type = 'camera'")
        ).scalar_one()
    assert camera_rows >= 1


def test_a_stale_message_changes_nothing():
    video_id = _video()
    before = _totals()
    with SessionLocal() as db:
        db.query(Video).filter_by(id=video_id).update({"status": VideoStatus.FAILED})
        db.commit()
    assert _store(video_id, 0) == Outcome.STALE
    assert _totals() == before


def test_a_re_gate_update_moves_the_admitted_count_and_bytes():
    video_id = _video()
    for index in range(4):
        _store(video_id, index)
    before = _totals()

    with SessionLocal() as db:
        rows = db.query(Segment).filter_by(video_id=video_id).order_by(Segment.frame_index).all()
        rows[0].admitted, rows[0].file_bytes = True, 1200
        rows[1].admitted, rows[1].file_bytes = True, 800
        db.commit()

    after = _totals()
    assert (after[0] - before[0], after[1] - before[1], after[2] - before[2]) == (0, 2, 2000)
    _assert_rollup_exact()


def test_deleting_a_video_takes_its_rows_out_of_the_rollup():
    before = _totals()
    video_id = _video()
    for index in range(3):
        _store(video_id, index, admitted=index == 0, file_bytes=900 if index == 0 else 0)

    with SessionLocal() as db:
        # The cascade from videos, as delete_video does it.
        db.query(Video).filter_by(id=video_id).delete(synchronize_session=False)
        db.commit()

    assert _totals() == before
    _assert_rollup_exact()


def test_a_failed_extraction_deleting_its_rows_takes_them_out_too():
    before = _totals()
    video_id = _video()
    for index in range(5):
        _store(video_id, index)
    with SessionLocal() as db:
        db.query(Segment).filter_by(video_id=video_id).delete(synchronize_session=False)
        db.commit()
    assert _totals() == before
    _assert_rollup_exact()


def test_summary_equals_a_direct_count(monkeypatch):
    video_id = _video(size_bytes=2_000_000_000)
    _store(video_id, 0, admitted=True, file_bytes=500_000_000)
    _store(video_id, 1)
    monkeypatch.setattr(
        dashboard_module,
        "live_cameras",
        lambda _db: [
            CameraLiveOut(camera_id=1, name="a", location="l", group_name="g", state="live", last_frame_at=None),
            CameraLiveOut(camera_id=2, name="b", location="l", group_name="g", state="frozen", last_frame_at=None),
            CameraLiveOut(camera_id=3, name="c", location="l", group_name="g", state="stopped", last_frame_at=None),
        ],
    )

    resp = client.get("/dashboard/summary", headers=_headers())

    assert resp.status_code == 200
    body = resp.json()
    with SessionLocal() as db:
        segments, file_bytes = db.execute(text("SELECT count(*), coalesce(sum(file_bytes), 0) FROM segments")).one()
        videos, video_bytes = db.execute(text("SELECT count(*), coalesce(sum(size_bytes), 0) FROM videos")).one()
    assert body["segments"] == segments
    assert body["videos"] == videos
    assert body["storage_gb"] == round(int(video_bytes + file_bytes) / 1e9, 3)
    assert body["cameras_online"] == 1 and body["cameras_total"] == 3
    assert body["alerts_today"] is None
    assert body["retention_days"] == settings.video_retention_days


def test_summary_oldest_recording_ignores_dataset_footage(monkeypatch):
    monkeypatch.setattr(dashboard_module, "live_cameras", lambda _db: [])
    _video(source=VideoSource.DATASET)
    with SessionLocal() as db:
        expected = db.execute(
            text("SELECT min(created_at) FROM videos WHERE source <> 'dataset'")
        ).scalar_one()

    body = client.get("/dashboard/summary", headers=_headers()).json()

    if expected is None:
        assert body["oldest_recording_at"] is None
    else:
        assert datetime.fromisoformat(body["oldest_recording_at"]) == expected


def test_activity_has_one_entry_per_hour_ending_now_with_this_hours_segments():
    with SessionLocal() as db:
        hour_now = db.execute(
            text(
                "SELECT coalesce(sum(segments), 0) FROM segment_hourly "
                "WHERE hour = date_trunc('hour', now(), 'UTC')"
            )
        ).scalar_one()
    video_id = _video()
    for index in range(3):
        _store(video_id, index)

    resp = client.get("/dashboard/activity?hours=24", headers=_headers())

    assert resp.status_code == 200
    hours = resp.json()
    assert len(hours) == 24
    current = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    assert datetime.fromisoformat(hours[-1]["hour"]) == current
    assert hours[-1]["segments"] == hour_now + 3
    assert all(h["alerts"] is None for h in hours)
    starts = [datetime.fromisoformat(h["hour"]) for h in hours]
    assert all((b - a).total_seconds() == 3600 for a, b in zip(starts, starts[1:]))


def test_activity_rejects_an_hours_value_out_of_range():
    assert client.get("/dashboard/activity?hours=0", headers=_headers()).status_code == 422
    assert client.get("/dashboard/activity?hours=169", headers=_headers()).status_code == 422


def test_both_endpoints_need_a_token():
    assert client.get("/dashboard/summary").status_code == 401
    assert client.get("/dashboard/activity").status_code == 401
