"""OMNI-707: `GET /search` over `frame_vectors`.

Needs Postgres (`docker compose up -d`); runs on the test database (conftest). Qdrant is
qdrant-client's in-process mode, put in place of the real one, and ai_workers is replaced at
its HTTP call (`httpx.post` in ai_workers_client), so the cache and the model check are the
real code. Every frame vector is cos(θ)·e0 + sin(θ)·e1 and every query is e0, so a frame's
score is exactly the cosine chosen for it.
"""

import logging
import math
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app import ai_workers_client
from app import consumer as consumer_module
from app.db import SessionLocal
from app.embed_jobs import job_for_frame
from app.embeddings import get_qdrant
from app.main import app
from app.models import Camera, Segment, User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import Domain, Role, SegmentMessage, VideoSource, VideoStatus
from omnisight_common.frame_vectors import FRAME_VECTOR_SIZE, ensure_frame_collection, frame_point
from qdrant_client import QdrantClient

NAME_PREFIX = "omni707-"
RUN = "run-707"
PASSWORD = "Omni707Pass!"
EMAILS = {role: f"omni707-{role.value}@omnisight.local" for role in Role}

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def users():
    with SessionLocal() as session:
        for role, email in EMAILS.items():
            session.add(User(email=email, password_hash=hash_password(PASSWORD), role=role, is_active=True))
        session.commit()
    yield
    with SessionLocal() as session:
        session.query(User).filter(User.email.in_(EMAILS.values())).delete(synchronize_session=False)
        session.commit()


@pytest.fixture(autouse=True)
def cleanup():
    ai_workers_client.cache.clear()
    yield
    ai_workers_client.cache.clear()
    with SessionLocal() as session:
        session.query(Video).filter(Video.filename.like(f"{NAME_PREFIX}%")).delete(synchronize_session=False)
        camera_ids = [c.id for c in session.query(Camera).filter(Camera.name.like(f"{NAME_PREFIX}%"))]
        session.query(Segment).filter(Segment.camera_id.in_(camera_ids)).delete(synchronize_session=False)
        session.query(Camera).filter(Camera.id.in_(camera_ids)).delete(synchronize_session=False)
        session.commit()


@pytest.fixture
def qdrant():
    memory = QdrantClient(":memory:")
    ensure_frame_collection(memory, settings.frame_collection)
    app.dependency_overrides[get_qdrant] = lambda: memory
    yield memory
    app.dependency_overrides.pop(get_qdrant, None)
    memory.close()


class FakeAiWorkers:
    """ai_workers' `/encode/text`: every query is e0, of the pinned model unless told
    otherwise. Counts the calls, to see the cache."""

    def __init__(self, model=None, down=False):
        self.calls = []
        self.model = model or settings.frame_model_id
        self.down = down

    def post(self, url, json, timeout):
        self.calls.append((url, json["q"]))
        request = httpx.Request("POST", url)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        vector = [0.0] * FRAME_VECTOR_SIZE
        vector[0] = 1.0
        body = {"vector": vector, "model": self.model, "model_revision": settings.frame_model_revision}
        return httpx.Response(200, json=body, request=request)


@pytest.fixture
def ai_workers(monkeypatch):
    fake = FakeAiWorkers()
    monkeypatch.setattr(ai_workers_client.httpx, "post", fake.post)
    return fake


def _headers(role=Role.OPERATOR) -> dict[str, str]:
    token = client.post("/auth/login", json={"email": EMAILS[role], "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _camera() -> int:
    with SessionLocal() as session:
        camera = Camera(
            name=f"{NAME_PREFIX}{uuid.uuid4().hex[:8]}", rtsp_url="rtsp://example.invalid/x",
            location="lab", group_name="g", domain=Domain.SURVEILLANCE, status="registered",
        )
        session.add(camera)
        session.commit()
        return camera.id


def _video() -> int:
    with SessionLocal() as session:
        video = Video(
            filename=f"{NAME_PREFIX}{uuid.uuid4().hex[:8]}.mp4", path="/nonexistent.mp4", source=VideoSource.UPLOAD,
            size_bytes=1, status=VideoStatus.EXTRACTING, extraction_id=RUN,
        )
        session.add(video)
        session.commit()
        return video.id


def _frame(qdrant, cosine, *, video_id=None, camera_id=None, at=None, model=None) -> int:
    """Store one admitted frame (an upload's, or a camera's at Unix time `at`) and its point
    with the given cosine to the query. Returns the segment id."""
    index = int(cosine * 1000) if at is None else 0
    message = SegmentMessage(
        video_id=video_id, camera_id=camera_id, frame_index=index,
        timestamp_s=index / 30 if at is None else at,
        frame_path=f"/data/frames/{video_id}/{index:06d}.jpg", thumb_path=f"/data/thumbs/{video_id}/{index:06d}.jpg",
        motion_score=2.0, admitted=True, source_type="upload" if video_id is not None else "camera",
        admission_reason="motion", extraction_id=RUN if video_id is not None else None,
    )
    consumer_module.store_segment(message.model_dump_json().encode())
    with SessionLocal() as db:
        job = job_for_frame(db, video_id=video_id, camera_id=camera_id, frame_index=index, timestamp_s=message.timestamp_s)
    vector = [0.0] * FRAME_VECTOR_SIZE
    vector[0], vector[1] = cosine, math.sqrt(1 - cosine**2)
    payload = job.payload(model or settings.frame_model_id, settings.frame_model_revision)
    qdrant.upsert(settings.frame_collection, points=[frame_point(payload, vector)])
    return job.segment_id


def _search(**params):
    return client.get("/search", params={"q": "a person", **params}, headers=params.pop("headers", None) or _headers())


# --- results --------------------------------------------------------------------------------


def test_a_query_returns_ranked_moments_with_every_field(qdrant, ai_workers):
    video_id = _video()
    ids = [_frame(qdrant, c, video_id=video_id) for c in (0.3, 0.9, 0.6)]

    response = _search()

    assert response.status_code == 200
    body = response.json()
    assert [hit["segment_id"] for hit in body["results"]] == [ids[1], ids[2], ids[0]]
    assert [round(hit["score"], 4) for hit in body["results"]] == [0.9, 0.6, 0.3]
    hit = body["results"][0]
    assert hit["video_id"] == video_id
    assert hit["camera"] is None
    assert hit["timestamp_s"] == pytest.approx(900 / 30)
    assert hit["captured_at"]
    assert hit["matched_by"] == "frame"
    assert hit["thumb_url"] == f"/thumbs/{video_id}/000900.jpg"
    assert body["mode"] == "frame"
    assert body["total"] == 3
    assert body["dropped"] == 0
    assert body["message"] is None
    assert set(body["timings"]) == {"encode_ms", "search_ms", "join_ms", "encode_cached"}
    assert body["elapsed_ms"] >= body["timings"]["search_ms"]


def test_k_limits_the_results_and_defaults_to_5(qdrant, ai_workers):
    video_id = _video()
    for c in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        _frame(qdrant, c, video_id=video_id)

    assert _search().json()["total"] == 5
    assert [round(h["score"], 1) for h in _search(k=2).json()["results"]] == [0.7, 0.6]


@pytest.mark.parametrize("k", [0, 51])
def test_k_outside_1_to_50_is_refused(qdrant, ai_workers, k):
    assert _search(k=k).status_code == 422


def test_only_vectors_of_the_pinned_model_are_searched(qdrant, ai_workers):
    video_id = _video()
    ours = _frame(qdrant, 0.5, video_id=video_id)
    _frame(qdrant, 0.9, video_id=video_id, model="another/model")

    assert [h["segment_id"] for h in _search().json()["results"]] == [ours]


# --- filters inside the search --------------------------------------------------------------


def test_a_camera_filter_finds_that_cameras_frames_even_below_other_cameras_top_k(qdrant, ai_workers):
    # The acceptance: camera A's best frame ranks below camera B's k frames unfiltered.
    camera_a, camera_b = _camera(), _camera()
    a = _frame(qdrant, 0.4, camera_id=camera_a, at=1_790_000_000.0)
    for i, c in enumerate((0.95, 0.9, 0.85, 0.8, 0.75)):
        _frame(qdrant, c, camera_id=camera_b, at=1_790_000_100.0 + i)

    unfiltered = _search(k=5).json()["results"]
    filtered = _search(k=5, camera_id=camera_a).json()

    assert a not in [h["segment_id"] for h in unfiltered]
    assert [h["segment_id"] for h in filtered["results"]] == [a]
    assert filtered["results"][0]["camera"]["id"] == camera_a


def test_a_date_filter_is_applied_inside_the_search(qdrant, ai_workers):
    camera_id = _camera()
    early = 1_790_000_000.0
    late = early + 3600
    in_window = _frame(qdrant, 0.3, camera_id=camera_id, at=early)
    for i, c in enumerate((0.9, 0.8, 0.7)):
        _frame(qdrant, c, camera_id=camera_id, at=late + i)
    start = datetime.fromtimestamp(early - 60, UTC)
    end = datetime.fromtimestamp(early + 60, UTC)

    body = _search(k=1, **{"from": start.isoformat(), "to": end.isoformat()}).json()

    assert [h["segment_id"] for h in body["results"]] == [in_window]


def test_a_date_without_a_zone_is_utc(qdrant, ai_workers):
    camera_id = _camera()
    at = 1_790_000_000.0
    segment = _frame(qdrant, 0.5, camera_id=camera_id, at=at)
    naive = datetime.fromtimestamp(at, UTC).replace(tzinfo=None)

    body = _search(**{"from": (naive - timedelta(seconds=1)).isoformat(), "to": (naive + timedelta(seconds=1)).isoformat()}).json()

    assert [h["segment_id"] for h in body["results"]] == [segment]


def test_from_after_to_is_refused(qdrant, ai_workers):
    response = _search(**{"from": "2026-10-28T12:00:00Z", "to": "2026-10-28T11:00:00Z"})

    assert response.status_code == 422


# --- hits that no longer exist (K-24) -------------------------------------------------------


def test_a_hit_whose_segment_is_gone_is_dropped_counted_and_logged(qdrant, ai_workers, caplog):
    video_id = _video()
    kept = _frame(qdrant, 0.5, video_id=video_id)
    gone = _frame(qdrant, 0.9, video_id=video_id)
    with SessionLocal() as session:
        session.query(Segment).filter(Segment.id == gone).delete()
        session.commit()

    with caplog.at_level(logging.WARNING, logger="app.search"):
        body = _search().json()

    assert [h["segment_id"] for h in body["results"]] == [kept]
    assert body["dropped"] == 1
    assert body["total"] == 1
    assert any("dropped" in record.getMessage() for record in caplog.records)


def test_a_hit_whose_segment_is_no_longer_admitted_is_dropped(qdrant, ai_workers):
    video_id = _video()
    regated = _frame(qdrant, 0.9, video_id=video_id)
    with SessionLocal() as session:
        session.query(Segment).filter(Segment.id == regated).update({"admitted": False})
        session.commit()

    body = _search().json()

    assert body["results"] == []
    assert body["dropped"] == 1


# --- repeated queries (NFR-2) ---------------------------------------------------------------


def test_a_repeated_query_is_not_encoded_again(qdrant, ai_workers):
    _frame(qdrant, 0.5, video_id=_video())

    first = _search(q="a red car").json()
    second = _search(q="a red car").json()
    other = _search(q="a red car ").json()  # the same text once stripped
    different = _search(q="a blue car").json()

    assert [q for _, q in ai_workers.calls] == ["a red car", "a blue car"]
    assert (first["timings"]["encode_cached"], second["timings"]["encode_cached"]) == (False, True)
    assert other["timings"]["encode_cached"] is True
    assert different["timings"]["encode_cached"] is False


def test_results_are_not_cached(qdrant, ai_workers):
    video_id = _video()
    _frame(qdrant, 0.5, video_id=video_id)
    assert _search(q="a red car").json()["total"] == 1

    _frame(qdrant, 0.6, video_id=video_id)

    assert _search(q="a red car").json()["total"] == 2


# --- clear answers --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["clip", "fused"])
def test_clip_and_fused_say_the_clip_index_is_not_ready(qdrant, ai_workers, mode):
    response = _search(mode=mode)

    assert response.status_code == 503
    assert "clip index is not ready" in response.json()["detail"]
    assert ai_workers.calls == []


def test_an_unknown_mode_is_refused(qdrant, ai_workers):
    assert _search(mode="audio").status_code == 422


@pytest.mark.parametrize("q", ["", "   "])
def test_an_empty_query_is_refused(qdrant, ai_workers, q):
    response = client.get("/search", params={"q": q}, headers=_headers())

    assert response.status_code == 422
    assert response.json()["detail"] == "the query is empty"
    assert ai_workers.calls == []


def test_an_empty_index_says_nothing_is_indexed(qdrant, ai_workers):
    body = _search().json()

    assert body["results"] == []
    assert body["message"] == "nothing is indexed yet: no frame has a vector"


def test_a_filter_that_matches_nothing_is_not_an_empty_index(qdrant, ai_workers):
    _frame(qdrant, 0.5, video_id=_video())

    body = _search(camera_id=2_000_000_000).json()

    assert body["results"] == []
    assert body["message"] is None


def test_ai_workers_down_is_a_clear_503(qdrant, monkeypatch):
    monkeypatch.setattr(ai_workers_client.httpx, "post", FakeAiWorkers(down=True).post)

    response = _search()

    assert response.status_code == 503
    assert response.json()["detail"] == "the text encoder (ai_workers) is unreachable"


def test_a_text_vector_of_another_model_is_refused(qdrant, monkeypatch):
    monkeypatch.setattr(ai_workers_client.httpx, "post", FakeAiWorkers(model="another/model").post)

    response = _search()

    assert response.status_code == 503
    assert response.json()["detail"] == "the text encoder runs another model than the stored vectors"


def test_qdrant_down_is_a_clear_503(ai_workers):
    class Down:
        def query_points(self, *args, **kwargs):
            raise ConnectionError("qdrant is down")

    app.dependency_overrides[get_qdrant] = lambda: Down()
    try:
        response = _search()
    finally:
        app.dependency_overrides.pop(get_qdrant, None)

    assert response.status_code == 503
    assert response.json()["detail"] == "the vector store is unreachable"


# --- who may search (NFR-7) -----------------------------------------------------------------


def test_search_needs_a_token(qdrant, ai_workers):
    assert client.get("/search", params={"q": "a person"}).status_code == 401


@pytest.mark.parametrize("role", [Role.OPERATOR, Role.ANALYST, Role.ADMIN])
def test_every_role_may_search(qdrant, ai_workers, role):
    assert _search(headers=_headers(role)).status_code == 200
