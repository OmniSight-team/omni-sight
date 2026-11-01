"""The embed queue's consumer (OMNI-705): every admitted frame gets its vector, durably.

Runs on a thread inside the ai_workers process, beside the HTTP API, so the one loaded
model serves both (two copies do not fit on this laptop, OMNI-704). For each batch of jobs:

1. encode the frames together (Algorithm 2 line 1, `encoder.encode_images`)
2. upsert one point per frame into `frame_vectors` and wait for Qdrant to apply it
3. **only then** acknowledge the jobs

Killed anywhere before 3, the broker hands the unacknowledged jobs to the next start, which
encodes them again and upserts the same points (id = segment id, D-29): nothing lost,
nothing doubled. A job that can never be encoded (it does not parse, or its frame file is
gone or unreadable) goes to the dead-letter queue, where a person can see it; anything else
(Qdrant or the broker down) drops the connection, so the jobs come back, and the loop
reconnects after a growing pause.

While a batch encodes (about 9 s a frame on this CPU), the connection keeps being serviced,
so the broker's heartbeat does not time out and take the batch back half-way.

Like encoder.py, this imports nothing from `app.*`: the encoder, the Qdrant client and the
broker arrive as arguments, so a test loads it by file path.
"""

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass

import pika
from omnisight_common.embed_queue import EmbedJob, declare_embed_queue
from omnisight_common.frame_vectors import ensure_frame_collection, frame_point
from pydantic import ValidationError
from qdrant_client import QdrantClient

logger = logging.getLogger("app.embed_worker")

MAX_BACKOFF_S = 30.0
# How often the connection is serviced while a batch encodes.
SERVICE_INTERVAL_S = 1.0
# What an unreadable frame raises (FileNotFoundError and PIL's UnidentifiedImageError
# are OSErrors; a truncated file can raise either).
UNREADABLE = (OSError, ValueError)


@dataclass
class Delivery:
    tag: int
    job: EmbedJob


class EmbedWorker:
    def __init__(
        self,
        encoder,
        qdrant_factory: Callable[[], QdrantClient],
        *,
        connection_params: pika.ConnectionParameters,
        queue: str,
        collection: str,
        model: str,
        model_revision: str,
        batch_size: int = 8,
        batch_wait_s: float = 0.5,
    ) -> None:
        self.encoder = encoder
        self.qdrant_factory = qdrant_factory
        self.connection_params = connection_params
        self.queue = queue
        self.collection = collection
        self.model = model
        self.model_revision = model_revision
        self.batch_size = batch_size
        self.batch_wait_s = batch_wait_s
        self.embedded = 0
        self.dead_lettered = 0
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    # --- lifecycle --------------------------------------------------------------------------

    def start(self) -> threading.Thread:
        self._thread = threading.Thread(target=self.run, name="embed-worker", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self, timeout_s: float | None = None) -> None:
        """Stop after the batch in hand (it is finished and acknowledged, or not acknowledged
        at all and redelivered later)."""
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout_s)

    def run(self) -> None:
        backoff = 1.0
        while not self._stopping.is_set():
            started = time.monotonic()
            try:
                self.consume()
            except Exception as exc:  # noqa: BLE001 - nothing may end the worker for good
                logger.error(
                    "embed worker stopped, will reconnect",
                    extra={"extra_fields": {"error": repr(exc)[:300]}},
                )
            if time.monotonic() - started > MAX_BACKOFF_S:
                backoff = 1.0
            if self._stopping.wait(backoff):
                return
            backoff = min(backoff * 2, MAX_BACKOFF_S)

    def consume(self) -> None:
        """One connection's lifetime; returns when stopped, raises on any failure."""
        with closing(self.qdrant_factory()) as qdrant, closing(pika.BlockingConnection(self.connection_params)) as connection:
            # Query creates the collection too; asked here so a first start of ai_workers
            # before query's does not fail every upsert.
            ensure_frame_collection(qdrant, self.collection)
            channel = connection.channel()
            declare_embed_queue(channel, self.queue)
            # Never more unacknowledged jobs than one batch.
            channel.basic_qos(prefetch_count=self.batch_size)
            logger.info(
                "consuming embed jobs",
                extra={"extra_fields": {"queue": self.queue, "batch_size": self.batch_size, "model": self.model}},
            )
            pending: list[tuple[int, bytes]] = []
            for method, _properties, body in channel.consume(self.queue, inactivity_timeout=self.batch_wait_s):
                if method is not None:
                    pending.append((method.delivery_tag, body))
                # A batch closes when it is full or nothing more arrived within the wait.
                if pending and (method is None or len(pending) >= self.batch_size):
                    self.handle(connection, channel, qdrant, pending)
                    pending = []
                if self._stopping.is_set() and not pending:
                    break
            # Anything delivered but not handled goes back to the queue.
            channel.cancel()

    # --- one batch --------------------------------------------------------------------------

    def handle(self, connection, channel, qdrant: QdrantClient, deliveries: list[tuple[int, bytes]]) -> None:
        batch: list[Delivery] = []
        for tag, body in deliveries:
            try:
                batch.append(Delivery(tag, EmbedJob.model_validate_json(body)))
            except ValidationError as exc:
                self._dead_letter(channel, tag, None, "embed job could not be parsed", exc)
        if not batch:
            return

        started = time.perf_counter()
        encoded, unreadable = self._while_serviced(connection, lambda: self._encode(batch))
        for delivery, exc in unreadable:
            self._dead_letter(channel, delivery.tag, delivery.job, "frame file could not be read", exc)
        if not encoded:
            return
        qdrant.upsert(
            collection_name=self.collection,
            points=[frame_point(d.job.payload(self.model, self.model_revision), vector.tolist()) for d, vector in encoded],
            wait=True,
        )
        # The points are stored: only now may the broker forget the jobs.
        for delivery, _vector in encoded:
            channel.basic_ack(delivery.tag)
        self.embedded += len(encoded)
        logger.info(
            "frames embedded",
            extra={"extra_fields": {
                "frames": len(encoded),
                "seconds": round(time.perf_counter() - started, 2),
                "embedded_total": self.embedded,
            }},
        )

    def _encode(self, batch: list[Delivery]):
        """The vectors of the frames that could be read, paired with their deliveries, and
        the deliveries whose frame could not be read. One unreadable frame does not sink the
        batch: the batch is then encoded one frame at a time. Runs on a helper thread, so it
        never touches the channel."""
        try:
            vectors = self.encoder.encode_images([d.job.frame_path for d in batch])
            return list(zip(batch, vectors, strict=True)), []
        except UNREADABLE:
            pass
        encoded, unreadable = [], []
        for delivery in batch:
            try:
                [vector] = self.encoder.encode_images([delivery.job.frame_path])
                encoded.append((delivery, vector))
            except UNREADABLE as exc:
                unreadable.append((delivery, exc))
        return encoded, unreadable

    @staticmethod
    def _while_serviced(connection, work: Callable):
        """Run `work` on a helper thread while this thread keeps the connection serviced
        (heartbeats): a pika connection may only be used from its own thread, and a batch
        that outlasts two heartbeats would otherwise be taken back by the broker."""
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="encode") as pool:
            future = pool.submit(work)
            while not future.done():
                connection.process_data_events(time_limit=SERVICE_INTERVAL_S)
            return future.result()

    def _dead_letter(self, channel, tag: int, job: EmbedJob | None, message: str, exc: Exception) -> None:
        # Not requeued: it would fail the same way for ever. GET /embeddings/status shows
        # the frame as not embedded, and the dead-letter queue says why.
        channel.basic_nack(tag, requeue=False)
        self.dead_lettered += 1
        logger.error(
            message + ", dead-lettered",
            extra={"extra_fields": {
                "segment_id": None if job is None else job.segment_id,
                "frame_path": None if job is None else job.frame_path,
                "error": repr(exc)[:300],
            }},
        )
