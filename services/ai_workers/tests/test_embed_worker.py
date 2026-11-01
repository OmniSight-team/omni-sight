"""OMNI-705: the embed queue's consumer — a point per job, acknowledged only after the upsert.

The broker is the real RabbitMQ (`docker compose up -d rabbitmq`), on a scratch queue per
test; Qdrant is qdrant-client's in-process mode; the encoder is a stand-in that returns a
unit vector per readable file, so no model is loaded. What the real model does to a frame
is test_encoder.py's business; this is about what happens to the jobs.

embed_worker.py is loaded by file path, like encoder.py (query and ingestion also have a
top-level package called `app`).
"""

import importlib.util
import time
import uuid
from pathlib import Path

import numpy as np
import pika
import pytest
from omnisight_common import CommonSettings, connection_parameters, dead_letter_queue
from omnisight_common.embed_queue import EmbedJob, declare_embed_queue
from omnisight_common.frame_vectors import FRAME_VECTOR_SIZE
from omnisight_common.segment_queue import PERSISTENT
from PIL import Image
from qdrant_client import QdrantClient

_spec = importlib.util.spec_from_file_location(
    "omnisight_ai_workers_embed_worker", Path(__file__).resolve().parents[1] / "app" / "embed_worker.py"
)
embed_worker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(embed_worker)

PARAMS = connection_parameters(CommonSettings())
COLLECTION = "frame_vectors"
MODEL, REVISION = "test/model", "rev-705"


class FakeEncoder:
    """A unit vector per image, from the file's bytes; raises like PIL on a missing file."""

    def __init__(self, delay_s: float = 0.0, fail_with: Exception | None = None):
        self.batches: list[int] = []
        self.delay_s = delay_s
        self.fail_with = fail_with

    def encode_images(self, paths):
        if self.fail_with is not None:
            raise self.fail_with
        rows = []
        for path in paths:
            with Image.open(path) as image:
                image.load()
            vector = np.zeros(FRAME_VECTOR_SIZE, dtype=np.float32)
            vector[hash(str(path)) % FRAME_VECTOR_SIZE] = 1.0
            rows.append(vector)
        self.batches.append(len(paths))
        time.sleep(self.delay_s)
        return np.stack(rows)


class SharedQdrant:
    """The in-process client, handed to the worker without being closed by it."""

    def __init__(self, client):
        self.client = client

    def __getattr__(self, name):
        return getattr(self.client, name)

    def close(self):
        pass


@pytest.fixture
def queue():
    name = f"omni705-embed-{uuid.uuid4().hex[:10]}"
    yield name
    with pika.BlockingConnection(PARAMS) as connection:
        channel = connection.channel()
        channel.queue_delete(name)
        channel.queue_delete(dead_letter_queue(name))


@pytest.fixture
def qdrant():
    client = QdrantClient(":memory:")
    yield client
    client.close()


@pytest.fixture
def frames(tmp_path):
    def make(count: int) -> list[str]:
        paths = []
        for i in range(count):
            path = tmp_path / f"{i:06d}.jpg"
            Image.new("RGB", (32, 32), (i * 10 % 256, 0, 0)).save(path)
            paths.append(str(path))
        return paths

    return make


def _job(segment_id: int, frame_path: str) -> EmbedJob:
    return EmbedJob(
        segment_id=segment_id, video_id=7, camera_id=None, source_type="upload", domain="surveillance",
        timestamp_s=segment_id / 10, captured_at="2026-10-28T09:00:00+00:00", frame_path=frame_path, thumb_path=None,
    )


def _publish(queue_name, jobs):
    with pika.BlockingConnection(PARAMS) as connection:
        channel = connection.channel()
        channel.confirm_delivery()
        declare_embed_queue(channel, queue_name)
        for job in jobs:
            body = job if isinstance(job, bytes) else job.model_dump_json().encode()
            channel.basic_publish("", queue_name, body, pika.BasicProperties(delivery_mode=PERSISTENT), mandatory=True)


def _ready(queue_name) -> int:
    with pika.BlockingConnection(PARAMS) as connection:
        return connection.channel().queue_declare(queue_name, passive=True).method.message_count


def _worker(encoder, qdrant, queue_name, batch_size=8):
    return embed_worker.EmbedWorker(
        encoder, lambda: SharedQdrant(qdrant), connection_params=PARAMS, queue=queue_name,
        collection=COLLECTION, model=MODEL, model_revision=REVISION, batch_size=batch_size, batch_wait_s=0.3,
    )


def _run_until(worker, done, timeout_s=60.0):
    worker.start()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline and not done():
        time.sleep(0.1)
    worker.stop(timeout_s=10)


def _ids(qdrant) -> list[int]:
    if not qdrant.collection_exists(COLLECTION):
        return []
    points, _ = qdrant.scroll(COLLECTION, limit=1000)
    return sorted(int(p.id) for p in points)


def test_every_job_becomes_one_point_with_its_payload(queue, qdrant, frames):
    paths = frames(5)
    _publish(queue, [_job(100 + i, p) for i, p in enumerate(paths)])

    _run_until(_worker(FakeEncoder(), qdrant, queue), lambda: len(_ids(qdrant)) == 5 and _ready(queue) == 0)

    assert _ids(qdrant) == [100, 101, 102, 103, 104]
    [point] = qdrant.retrieve(COLLECTION, [102], with_vectors=True)
    assert point.payload["frame_path"] == paths[2]
    assert (point.payload["model"], point.payload["model_revision"]) == (MODEL, REVISION)
    assert len(point.vector) == FRAME_VECTOR_SIZE
    assert _ready(queue) == 0


def test_waiting_jobs_are_encoded_together_up_to_the_batch_size(queue, qdrant, frames):
    _publish(queue, [_job(i, p) for i, p in enumerate(frames(7))])
    encoder = FakeEncoder()

    _run_until(_worker(encoder, qdrant, queue, batch_size=3), lambda: len(_ids(qdrant)) == 7)

    assert sum(encoder.batches) == 7
    assert max(encoder.batches) == 3 and len(encoder.batches) < 7


def test_the_same_job_delivered_twice_is_still_one_point(queue, qdrant, frames):
    [path] = frames(1)
    _publish(queue, [_job(5, path), _job(5, path)])

    _run_until(_worker(FakeEncoder(), qdrant, queue), lambda: _ready(queue) == 0 and _ids(qdrant) == [5])
    time.sleep(0.5)

    assert _ids(qdrant) == [5]


def test_a_frame_that_cannot_be_read_is_dead_lettered_and_the_rest_stored(queue, qdrant, frames):
    paths = frames(3)
    jobs = [_job(1, paths[0]), _job(2, "/nonexistent/000002.jpg"), _job(3, paths[2])]
    _publish(queue, jobs + [b"not a job"])

    _run_until(_worker(FakeEncoder(), qdrant, queue), lambda: _ready(dead_letter_queue(queue)) == 2)

    assert _ids(qdrant) == [1, 3]
    assert _ready(queue) == 0
    assert _ready(dead_letter_queue(queue)) == 2


def test_nothing_is_acknowledged_when_the_upsert_fails(queue, qdrant, frames):
    """Qdrant down: the batch's jobs stay with the broker and are done on the next try."""
    _publish(queue, [_job(i, p) for i, p in enumerate(frames(3))])
    attempts = []

    class Broken(SharedQdrant):
        def upsert(self, *args, **kwargs):
            attempts.append(1)
            raise ConnectionError("qdrant is down")

    worker = embed_worker.EmbedWorker(
        FakeEncoder(), lambda: Broken(qdrant), connection_params=PARAMS, queue=queue,
        collection=COLLECTION, model=MODEL, model_revision=REVISION, batch_size=8, batch_wait_s=0.3,
    )
    _run_until(worker, lambda: bool(attempts), timeout_s=10)
    time.sleep(0.5)

    assert _ids(qdrant) == []
    assert _ready(queue) == 3  # back in the queue, none lost

    _run_until(_worker(FakeEncoder(), qdrant, queue), lambda: len(_ids(qdrant)) == 3)
    assert _ids(qdrant) == [0, 1, 2]


def test_a_batch_longer_than_two_heartbeats_keeps_its_connection(queue, qdrant, frames):
    """A batch on this CPU takes over a minute; the broker must not take it back meanwhile.
    Heartbeat 2 s here, a 6 s batch."""
    _publish(queue, [_job(i, p) for i, p in enumerate(frames(2))])
    params = connection_parameters(CommonSettings())
    params.heartbeat = 2
    worker = embed_worker.EmbedWorker(
        FakeEncoder(delay_s=6.0), lambda: SharedQdrant(qdrant), connection_params=params, queue=queue,
        collection=COLLECTION, model=MODEL, model_revision=REVISION, batch_size=8, batch_wait_s=0.3,
    )

    _run_until(worker, lambda: len(_ids(qdrant)) == 2, timeout_s=30)

    assert _ids(qdrant) == [0, 1]
    assert _ready(queue) == 0
