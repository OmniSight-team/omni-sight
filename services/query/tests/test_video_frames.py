"""OMNI-307: GET /videos/{id}/frames.

Requires Postgres to be up with `alembic upgrade head` applied. No ingestion
involved at all — this endpoint only ever reads rows a prior extraction or
re-gate already wrote, so segments are seeded directly, the same way
test_segments.py (OMNI-302) does.
"""

from pathlib import Path

import pytest
from app.db import SessionLocal
from app.main import app
from app.models import Segment, User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import AdmissionReason, Role, SegmentSourceType, VideoSource, VideoStatus

client = TestClient(app)

TEST_PASSWORD = "Omni307Pass!"
OPERATOR_EMAIL = "omni307-operator@omnisight.local"
NAME_PREFIX = "omni307-"


@pytest.fixture(scope="module", autouse=True)
def omni307_user():
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
def cleanup():
    yield
    with SessionLocal() as session:
        # deleting a video cascades to its segment rows
        session.query(Video).filter(Video.filename.like(f"{NAME_PREFIX}%")).delete(
            synchronize_session=False
        )
        session.commit()


def _make_video(tmp_path) -> int:
    path = tmp_path / f"{NAME_PREFIX}clip.mp4"
    path.write_bytes(b"video bytes")
    with SessionLocal() as session:
        video = Video(
            filename=path.name,
            path=str(path),
            source=VideoSource.UPLOAD,
            size_bytes=path.stat().st_size,
            status=VideoStatus.READY,
        )
        session.add(video)
        session.commit()
        return video.id


def _add_segment(video_id, frame_index, *, admitted=False, motion_score=0.0, with_thumb=False):
    with SessionLocal() as session:
        session.add(
            Segment(
                video_id=video_id,
                frame_index=frame_index,
                timestamp_s=float(frame_index),
                motion_score=motion_score,
                admitted=admitted,
                source_type=SegmentSourceType.UPLOAD,
                thumb_path=f"{settings.thumbs_path}/{video_id}/{frame_index:06d}.jpg" if with_thumb else None,
                frame_path=f"{settings.frames_path}/{video_id}/{frame_index:06d}.jpg" if with_thumb else None,
                admission_reason=AdmissionReason.MOTION if admitted else None,
            )
        )
        session.commit()


def _frames(headers, video_id, **params):
    resp = client.get(f"/videos/{video_id}/frames", params=params, headers=headers)
    assert resp.status_code == 200
    return resp.json()


def test_frames_come_back_ordered_by_timestamp(tmp_path, headers):
    video_id = _make_video(tmp_path)
    for i in (4, 1, 3, 0, 2):  # inserted out of order
        _add_segment(video_id, i)

    frames = _frames(headers, video_id)

    assert [f["timestamp_s"] for f in frames] == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_admitted_true_false_all_filter_correctly(tmp_path, headers):
    video_id = _make_video(tmp_path)
    for i in range(6):
        _add_segment(video_id, i, admitted=(i % 2 == 0))

    all_frames = _frames(headers, video_id, admitted="all")
    admitted_frames = _frames(headers, video_id, admitted="true")
    discarded_frames = _frames(headers, video_id, admitted="false")

    assert len(all_frames) == 6
    assert len(admitted_frames) == 3 and all(f["admitted"] for f in admitted_frames)
    assert len(discarded_frames) == 3 and not any(f["admitted"] for f in discarded_frames)


def test_the_admitted_filter_is_in_the_sql_the_route_itself_sends_not_applied_in_python(
    tmp_path, headers, monkeypatch
):
    """A passing response above can't tell "filtered by the database" apart
    from "fetched everything, then filtered in Python" — both look identical
    from the outside. This intercepts sqlalchemy.orm.Query.all() itself, so
    it captures the *exact* query object the route's own code builds, not a
    parallel one written to match it — a route that switched to filtering
    after `.all()` would still pass every other test in this file but fail
    this one, because the captured SQL would have no WHERE on `admitted`."""
    from sqlalchemy.orm import Query

    video_id = _make_video(tmp_path)
    _add_segment(video_id, 0, admitted=True)
    _add_segment(video_id, 1, admitted=False)

    captured: list[str] = []
    original_all = Query.all

    def spying_all(self):
        try:
            captured.append(str(self.statement.compile(compile_kwargs={"literal_binds": True})))
        except Exception:
            pass
        return original_all(self)

    monkeypatch.setattr(Query, "all", spying_all)

    _frames(headers, video_id, admitted="true")

    segment_queries = [sql for sql in captured if "segments" in sql.lower()]
    assert segment_queries, "the route must run a query against segments"
    assert "admitted = true" in segment_queries[-1].lower()


def test_pagination_limit_and_offset(tmp_path, headers):
    video_id = _make_video(tmp_path)
    for i in range(10):
        _add_segment(video_id, i)

    first_page = _frames(headers, video_id, limit=4, offset=0)
    second_page = _frames(headers, video_id, limit=4, offset=4)

    assert [f["frame_index"] for f in first_page] == [0, 1, 2, 3]
    assert [f["frame_index"] for f in second_page] == [4, 5, 6, 7]


def test_pagination_defaults_and_cap(tmp_path, headers):
    video_id = _make_video(tmp_path)
    for i in range(60):
        _add_segment(video_id, i)

    default_page = _frames(headers, video_id)
    assert len(default_page) == 50  # matches GET /videos's own default (OMNI-207)

    assert client.get(f"/videos/{video_id}/frames", params={"limit": 201}, headers=headers).status_code == 422


def test_thumb_url_is_built_from_the_stored_path_and_none_without_a_file(tmp_path, headers, monkeypatch):
    monkeypatch.setattr(settings, "thumbs_path", "/data/thumbs")
    monkeypatch.setattr(settings, "thumb_url_prefix", "/thumbs")
    video_id = _make_video(tmp_path)
    _add_segment(video_id, 0, admitted=True, with_thumb=True)
    _add_segment(video_id, 1, admitted=False, with_thumb=False)

    frames = {f["frame_index"]: f for f in _frames(headers, video_id)}

    assert frames[0]["thumb_url"] == f"/thumbs/{video_id}/000000.jpg"
    assert frames[1]["thumb_url"] is None


def test_admission_reason_and_motion_score_and_segment_id_are_returned(tmp_path, headers):
    video_id = _make_video(tmp_path)
    _add_segment(video_id, 0, admitted=True, motion_score=7.0)

    frame = _frames(headers, video_id)[0]

    with SessionLocal() as session:
        real_id = session.query(Segment.id).filter_by(video_id=video_id, frame_index=0).scalar()
    assert frame["segment_id"] == real_id  # not the video's id
    assert frame["motion_score"] == 7.0
    assert frame["admission_reason"] == "motion"


def test_a_discarded_frame_has_no_admission_reason(tmp_path, headers):
    video_id = _make_video(tmp_path)
    _add_segment(video_id, 0, admitted=False)

    frame = _frames(headers, video_id)[0]

    assert frame["admitted"] is False
    assert frame["admission_reason"] is None


def test_frames_for_a_missing_video_is_a_404(headers):
    assert client.get("/videos/99999999/frames", headers=headers).status_code == 404


def test_frames_requires_auth(tmp_path):
    video_id = _make_video(tmp_path)
    assert client.get(f"/videos/{video_id}/frames").status_code == 401


def test_two_hundred_admitted_frames_come_back_in_one_call(tmp_path, headers):
    """The acceptance criterion's own number, at the layer this endpoint is
    actually responsible for: two hundred rows returned in one request, each
    with a usable thumb_url, is what a frame grid (OMNI-309) needs in order
    to have any chance of loading without a stall. Whether it actually
    renders that fast in a browser is that ticket's own claim to verify."""
    video_id = _make_video(tmp_path)
    for i in range(200):
        _add_segment(video_id, i, admitted=True, with_thumb=True)

    frames = _frames(headers, video_id, admitted="true", limit=200)

    assert len(frames) == 200
    assert all(f["thumb_url"] for f in frames)
    assert len({f["thumb_url"] for f in frames}) == 200  # all distinct
