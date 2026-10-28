"""OMNI-705: every admitted frame gets an embed job, and `GET /embeddings/status`.

Needs Postgres and RabbitMQ (`docker compose up -d`); runs on the test database (conftest).
Each test uses scratch queues of its own, so nothing reaches the real `omnisight.embed` or
ai_workers. Qdrant is qdrant-client's in-process mode, put in place of the real one.
"""

import time
import uuid
from datetime import UTC, timedelta

import pika
import pytest
from app import consumer as consumer_module
from app.db import SessionLocal
from app.embed_jobs import UNKNOWN_DOMAIN, job_for_frame, jobs_missing_from
from app.embeddings import get_qdrant
from app.main import app
from app.models import Camera, DatasetManifest, Segment, User, Video
from app.security import hash_password
from app.settings import settings
from fastapi.testclient import TestClient
from omnisight_common import (
    Domain,
    Role,
    SegmentMessage,
    VideoSource,
    VideoStatus,
    connection_parameters,
    dead_letter_queue,
    declare_segment_queue,
)
from omnisight_common.embed_queue import EmbedJob
from omnisight_common.frame_vectors import (
    FRAME_VECTOR_SIZE,
    ensure_frame_collection,
    frame_point,
)
from qdrant_client import QdrantClient

NAME_PREFIX = "omni705-"
RUN = "run-705"
PARAMS = connection_parameters(settings)
EMAIL = "omni705-operator@omnisight.local"
PASSWORD = "Omni705Pass!"

client = TestClient(app)


def _scratch_queue(monkeypatch, setting: str) -> str:
    name = f"omni705-{setting}-{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(settings, setting, name)
    return name


@pytest.fixture
def queues(monkeypatch):
    names = (_scratch_queue(monkeypatch, "segment_queue"), _scratch_queue(monkeypatch, "embed_queue"))
    yield names
    with pika.BlockingConnection(PARAMS) as connection:
        channel = connection.channel()
        for name in names:
            channel.queue_delete(name)
            channel.queue_delete(dead_letter_queue(name))


@pytest.fixture(scope="module", autouse=True)
def user():
    with SessionLocal() as session:
        session.add(User(email=EMAIL, password_hash=hash_password(PASSWORD), role=Role.OPERATOR, is_active=True))
        session.commit()
    yield
    with SessionLocal() as session:
        session.query(User).filter(User.email == EMAIL).delete(synchronize_session=False)
        session.commit()


@pytest.fixture(autouse=True)
def cleanup():
    yield
    with SessionLocal() as session:
        session.query(DatasetManifest).filter(DatasetManifest.clip_key.like(f"{NAME_PREFIX}%")).delete(synchronize_session=False)
        session.query(Video).filter(Video.filename.like(f"{NAME_PREFIX}%")).delete(synchronize_session=False)
        camera_ids = [c.id for c in session.query(Camera).filter(Camera.name.like(f"{NAME_PREFIX}%"))]
        session.query(Segment).filter(Segment.camera_id.in_(camera_ids)).delete(synchronize_session=False)
        session.query(Video).filter(Video.camera_id.in_(camera_ids)).delete(synchronize_session=False)
        session.query(Camera).filter(Camera.id.in_(camera_ids)).delete(synchronize_session=False)
        session.commit()


def _camera(domain=Domain.TRAFFIC) -> int:
    with SessionLocal() as session:
        camera = Camera(
            name=f"{NAME_PREFIX}{uuid.uuid4().hex[:8]}", rtsp_url="rtsp://example.invalid/x",
            location="lab", group_name="g", domain=domain, status="registered",
        )
        session.add(camera)
        session.commit()
        return camera.id


def _video(camera_id=None, source=VideoSource.UPLOAD) -> int:
    with SessionLocal() as session:
        video = Video(
            filename=f"{NAME_PREFIX}{uuid.uuid4().hex[:8]}.mp4", path="/nonexistent.mp4", source=source,
            size_bytes=1, status=VideoStatus.EXTRACTING, extraction_id=RUN, camera_id=camera_id,
        )
        session.add(video)
        session.commit()
        return video.id


def _in_dataset(video_id, domain) -> None:
    with SessionLocal() as session:
        session.add(DatasetManifest(
            dataset="ccd", clip_key=f"{NAME_PREFIX}{uuid.uuid4().hex[:8]}", domain=domain,
            annotation_source="ccd_binlabels", video_id=video_id, video_relpath="x.mp4",
        ))
        session.commit()


def _message(video_id, index, *, admitted=True, camera_id=None, timestamp_s=None) -> SegmentMessage:
    return SegmentMessage(
        video_id=video_id, camera_id=camera_id, frame_index=index,
        timestamp_s=index / 30 if timestamp_s is None else timestamp_s,
        frame_path=f"/data/frames/{video_id}/{index:06d}.jpg" if admitted else None,
        thumb_path=f"/data/thumbs/{video_id}/{index:06d}.jpg" if admitted else None,
        motion_score=2.0, admitted=admitted,
        source_type="upload" if video_id is not None else "camera",
        admission_reason="motion" if admitted else None,
        extraction_id=RUN if video_id is not None else None,
    )


def _store(message: SegmentMessage) -> int | None:
    consumer_module.store_segment(message.model_dump_json().encode())
    with SessionLocal() as session:
        query = session.query(Segment.id)
        if message.video_id is not None:
            query = query.filter_by(video_id=message.video_id, frame_index=message.frame_index)
        else:
            query = query.filter_by(camera_id=message.camera_id, timestamp_s=message.timestamp_s)
        row = query.one_or_none()
        return None if row is None else row.id


def _job(message: SegmentMessage) -> EmbedJob | None:
    with SessionLocal() as db:
        return job_for_frame(
            db, video_id=message.video_id, camera_id=message.camera_id,
            frame_index=message.frame_index, timestamp_s=message.timestamp_s,
        )


# --- the job: what it carries -----------------------------------------------------------


def test_an_uploaded_frame_job_carries_its_payload_and_absolute_time():
    video_id = _video()
    message = _message(video_id, 45)
    segment_id = _store(message)

    job = _job(message)

    assert job.segment_id == segment_id
    assert (job.video_id, job.camera_id, job.source_type) == (video_id, None, "upload")
    assert job.frame_path == message.frame_path and job.thumb_path == message.thumb_path
    assert job.timestamp_s == 1.5
    with SessionLocal() as session:
        uploaded = session.get(Video, video_id).created_at
    assert job.captured_at == (uploaded.astimezone(UTC) + timedelta(seconds=1.5)).isoformat()


def test_a_frame_that_was_not_admitted_has_no_job():
    video_id = _video()
    message = _message(video_id, 3, admitted=False)
    _store(message)

    assert _job(message) is None


def test_the_domain_is_the_live_frames_camera():
    camera_id = _camera(Domain.SPORTS)
    message = _message(None, 0, camera_id=camera_id, timestamp_s=1_790_000_000.25)
    _store(message)

    job = _job(message)
    assert job.domain == Domain.SPORTS and job.camera_id == camera_id
    assert job.captured_at.startswith("2026-09-21T")


def test_the_domain_is_the_videos_camera():
    video_id = _video(camera_id=_camera(Domain.TRAFFIC))
    message = _message(video_id, 1)
    _store(message)

    assert _job(message).domain == Domain.TRAFFIC


def test_the_domain_is_the_dataset_the_video_came_from():
    video_id = _video(source=VideoSource.DATASET)
    _in_dataset(video_id, Domain.TRAFFIC)
    message = _message(video_id, 1)
    _store(message)

    assert _job(message).domain == Domain.TRAFFIC


def test_a_plain_upload_falls_back_to_surveillance():
    video_id = _video()
    message = _message(video_id, 1)
    _store(message)

    assert _job(message).domain == UNKNOWN_DOMAIN == Domain.SURVEILLANCE


def test_the_backfill_finds_only_frames_without_a_point():
    video_id = _video()
    ids = [_store(_message(video_id, i)) for i in range(4)]
    _store(_message(video_id, 9, admitted=False))

    with SessionLocal() as db:
        missing = [job.segment_id for job in jobs_missing_from(db, embedded={ids[0], ids[2]}) if job.video_id == video_id]

    assert missing == [ids[1], ids[3]]


# --- the consumer publishes it ----------------------------------------------------------


def _publish(queue_name, bodies):
    with pika.BlockingConnection(PARAMS) as connection:
        channel = connection.channel()
        channel.confirm_delivery()
        declare_segment_queue(channel, queue_name)
        for body in bodies:
            channel.basic_publish("", queue_name, body, pika.BasicProperties(delivery_mode=2), mandatory=True)


def _drain(queue_name) -> list[EmbedJob]:
    jobs = []
    with pika.BlockingConnection(PARAMS) as connection:
        channel = connection.channel()
        while True:
            method, _props, body = channel.basic_get(queue_name, auto_ack=True)
            if method is None:
                return jobs
            jobs.append(EmbedJob.model_validate_json(body))


def _ready(queue_name) -> int:
    with pika.BlockingConnection(PARAMS) as connection:
        return connection.channel().queue_declare(queue_name, passive=True).method.message_count


def _run_consumer(segment_queue, *, until, seconds=5.0, on_message=consumer_module._on_message):
    connection = pika.BlockingConnection(PARAMS)
    error = None
    try:
        channel = connection.channel()
        consumer_module.start(channel, on_message=on_message, queue=segment_queue)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not until():
            connection.process_data_events(time_limit=0.2)
    except Exception as exc:  # noqa: BLE001 - the "crash" under test
        error = exc
    finally:
        connection.close()
    return error


def test_each_stored_admitted_frame_gets_one_job_and_the_rest_none(queues):
    segment_queue, embed_queue = queues
    video_id = _video()
    messages = [_message(video_id, i, admitted=i % 2 == 0) for i in range(6)]
    _publish(segment_queue, [m.model_dump_json().encode() for m in messages])

    # Ready counts drop on delivery, not on acknowledgement: wait for the jobs themselves.
    _run_consumer(segment_queue, until=lambda: _ready(embed_queue) >= 3)
    time.sleep(0.5)

    jobs = _drain(embed_queue)
    with SessionLocal() as session:
        admitted_ids = sorted(i for (i,) in session.query(Segment.id).filter_by(video_id=video_id, admitted=True))
    assert sorted(job.segment_id for job in jobs) == admitted_ids
    assert len(admitted_ids) == 3


def test_a_stale_frame_gets_no_job(queues):
    segment_queue, embed_queue = queues
    video_id = _video()
    stale = _message(video_id, 0).model_copy(update={"extraction_id": "an-older-run"})
    _publish(segment_queue, [stale.model_dump_json().encode()])

    _run_consumer(segment_queue, until=lambda: False, seconds=2.0)

    assert _ready(segment_queue) == 0  # handled and acknowledged
    assert _drain(embed_queue) == []


def test_a_consumer_killed_after_the_commit_still_gets_the_job_out(queues):
    """Dies between the commit and the publish: the message comes back, its row is already
    there (DUPLICATE), and the job is published then."""
    segment_queue, embed_queue = queues
    video_id = _video()
    message = _message(video_id, 0)
    _publish(segment_queue, [message.model_dump_json().encode()])

    def dies_after_commit(channel, method, properties, body):
        consumer_module.store_segment(body)
        raise RuntimeError("killed after the commit")

    error = _run_consumer(segment_queue, until=lambda: False, seconds=2.0, on_message=dies_after_commit)
    assert isinstance(error, RuntimeError)
    assert _ready(embed_queue) == 0 and _ready(segment_queue) == 1

    _run_consumer(segment_queue, until=lambda: _ready(embed_queue) >= 1)
    time.sleep(0.5)

    jobs = _drain(embed_queue)
    assert [job.segment_id for job in jobs] == [_store(message)]


# --- GET /embeddings/status --------------------------------------------------------------


@pytest.fixture
def qdrant(monkeypatch):
    memory = QdrantClient(":memory:")
    ensure_frame_collection(memory, settings.frame_collection)
    app.dependency_overrides[get_qdrant] = lambda: memory
    yield memory
    app.dependency_overrides.pop(get_qdrant, None)
    memory.close()


def _point(job: EmbedJob, *, model=None):
    vector = [0.0] * FRAME_VECTOR_SIZE
    vector[job.segment_id % FRAME_VECTOR_SIZE] = 1.0
    payload = job.payload(model or settings.frame_model_id, settings.frame_model_revision)
    return frame_point(payload, vector)


def _headers() -> dict[str, str]:
    token = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_status_counts_admitted_frames_against_points_of_the_pinned_model(qdrant):
    video_id = _video()
    camera_id = _camera()
    video_frames = [_message(video_id, i) for i in range(5)] + [_message(video_id, 7, admitted=False)]
    live_frames = [_message(None, 0, camera_id=camera_id, timestamp_s=1_790_000_000.0 + i) for i in range(3)]
    for message in video_frames + live_frames:
        _store(message)
    jobs = [_job(m) for m in video_frames[:3] + live_frames[:1]]
    qdrant.upsert(settings.frame_collection, points=[_point(j) for j in jobs])
    # Another model's vector of a frame is not this model's: not counted.
    qdrant.upsert(settings.frame_collection, points=[_point(_job(video_frames[3]), model="another/model")])
    # A point whose segment no longer exists (K-24) is not counted either.
    orphan = jobs[0].model_copy(update={"segment_id": 2_000_000_000})
    qdrant.upsert(settings.frame_collection, points=[_point(orphan)])

    response = client.get("/embeddings/status", headers=_headers())

    assert response.status_code == 200
    rows = {(r["video_id"], r["camera_id"]): r for r in response.json()}
    assert rows[(video_id, None)] == {
        "video_id": video_id, "camera_id": None, "frames_total": 5, "frames_embedded": 3,
        "clips_embedded": 0, "model": settings.frame_model_id,
    }
    assert rows[(None, camera_id)]["frames_total"] == 3
    assert rows[(None, camera_id)]["frames_embedded"] == 1


def test_status_needs_a_login(qdrant):
    assert client.get("/embeddings/status").status_code == 401


def test_status_says_so_when_qdrant_is_unreachable():
    class Down:
        def scroll(self, *args, **kwargs):
            raise ConnectionError("qdrant is down")

    app.dependency_overrides[get_qdrant] = lambda: Down()
    try:
        response = client.get("/embeddings/status", headers=_headers())
    finally:
        app.dependency_overrides.pop(get_qdrant, None)
    assert response.status_code == 503
