"""The segment consumer (OMNI-311): reads gated frames off the durable queue and
writes their rows.

Run as its own process (`python -m app.consumer`, the `consumer` service in
docker-compose.yml) so it can be killed and restarted without touching the API.

The rule that makes NFR-5 ("lost = 0") true rather than hoped for: a message is
acknowledged only **after** its row is committed. Kill this process at any
point and the broker hands every unacknowledged message to the next consumer.
The one thing that can then happen twice is a message whose row *was*
committed but whose acknowledgement never got out; the unique index on
(video_id, frame_index) turns that second delivery into a no-op instead of a
duplicate row.
"""

import logging
import time
from contextlib import closing
from enum import Enum

import pika
from omnisight_common import (
    SegmentMessage,
    VideoStatus,
    connection_parameters,
    declare_segment_queue,
)
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.logging_conf import configure_logging
from app.models import Camera, Segment, Video
from app.settings import settings

logger = logging.getLogger("app.consumer")

MAX_BACKOFF_S = 30.0


class Outcome(Enum):
    STORED = "stored"
    # The row was already there: a redelivery of a message whose row had been
    # committed before its acknowledgement got out.
    DUPLICATE = "duplicate"
    # Belongs to a video that no longer exists, or to an extraction that is no
    # longer the current one. Nothing to store, and nothing to retry.
    STALE = "stale"


class MalformedMessage(Exception):
    """Cannot ever be stored, however often it is retried."""


def store_segment(body: bytes) -> Outcome:
    """Write one message's row and commit it. Returns only after the commit."""
    try:
        message = SegmentMessage.model_validate_json(body)
    except ValidationError as exc:
        raise MalformedMessage(str(exc)) from exc

    values = message.model_dump(exclude={"extraction_id"})
    with SessionLocal() as db:
        if message.video_id is not None:
            # FOR SHARE: while this row is being written, the video cannot be
            # failed or deleted underneath it. The video's state is the check,
            # so a frame from a run that has since failed or been replaced is
            # dropped rather than written into the newer run's video.
            video = db.execute(
                select(Video.status, Video.extraction_id)
                .where(Video.id == message.video_id)
                .with_for_update(read=True)
            ).one_or_none()
            if (
                video is None
                or video.status != VideoStatus.EXTRACTING
                or video.extraction_id != message.extraction_id
            ):
                return Outcome.STALE

        else:
            # A live frame (OMNI-312). Its camera may have been deleted while
            # the frame was in flight; storing it would fail on the foreign key,
            # the consumer would drop its connection, and the same message
            # would fail again on redelivery, for ever. Nothing to store, and
            # nothing to retry.
            if message.camera_id is None:
                raise MalformedMessage("a segment needs a video or a camera")
            if db.get(Camera, message.camera_id) is None:
                return Outcome.STALE

        statement = pg_insert(Segment).values(**values)
        if message.video_id is not None:
            statement = statement.on_conflict_do_nothing(
                index_elements=["video_id", "frame_index"],
                index_where=text("video_id IS NOT NULL"),
            )
        else:
            statement = statement.on_conflict_do_nothing(
                index_elements=["camera_id", "timestamp_s"],
                index_where=text("video_id IS NULL"),
            )
        # RETURNING, not rowcount: with this driver rowcount is -1 for an
        # INSERT, so it cannot tell a new row from a conflict. A row comes back
        # only when one was actually inserted.
        inserted = db.execute(statement.returning(Segment.id)).scalar_one_or_none()
        db.commit()
        return Outcome.STORED if inserted is not None else Outcome.DUPLICATE


def _on_message(channel, method, _properties, body: bytes) -> None:
    try:
        outcome = store_segment(body)
    except MalformedMessage as exc:
        # Goes to the dead-letter queue, where a person can look at it. Not
        # requeued: it would fail the same way forever.
        logger.error(
            "segment message could not be parsed, dead-lettered",
            extra={"extra_fields": {"error": str(exc)[:300]}},
        )
        channel.basic_nack(method.delivery_tag, requeue=False)
        return
    # store_segment returned: the row is committed (or there was nothing to
    # commit). Only now is it safe to tell the broker it can forget the message.
    channel.basic_ack(method.delivery_tag)
    if outcome is not Outcome.STORED:
        logger.info(
            "segment message acknowledged without a new row",
            extra={"extra_fields": {"outcome": outcome.value}},
        )


def start(channel, on_message=_on_message) -> None:
    """Declare the queue, limit what this consumer may hold unacknowledged, and
    subscribe. Deliveries then arrive as the connection's I/O loop runs."""
    declare_segment_queue(channel, settings.segment_queue)
    # The most unacknowledged messages this consumer may hold. Without it the
    # broker pushes the whole backlog at the first consumer to connect, and a
    # second consumer sits idle while the first works through it.
    channel.basic_qos(prefetch_count=settings.segment_prefetch)
    channel.basic_consume(queue=settings.segment_queue, on_message_callback=on_message, auto_ack=False)


def consume() -> None:
    """One connection's lifetime: returns only if the broker closes it cleanly,
    raises on anything else."""
    with closing(pika.BlockingConnection(connection_parameters(settings))) as connection:
        channel = connection.channel()
        start(channel)
        logger.info(
            "consuming segments",
            extra={
                "extra_fields": {
                    "queue": settings.segment_queue,
                    "prefetch": settings.segment_prefetch,
                }
            },
        )
        channel.start_consuming()


def run() -> None:
    """Consume forever. Any failure — the broker restarting, the database being
    down — closes the connection, which returns every unacknowledged message to
    the queue, and the loop reconnects after a growing pause."""
    backoff = 1.0
    while True:
        started = time.monotonic()
        try:
            consume()
        except Exception as exc:  # noqa: BLE001 - nothing may end the consumer for good
            logger.error(
                "consumer stopped, will reconnect",
                extra={"extra_fields": {"error": repr(exc)[:300]}},
            )
        if time.monotonic() - started > MAX_BACKOFF_S:
            backoff = 1.0
        time.sleep(backoff)
        backoff = min(backoff * 2, MAX_BACKOFF_S)


if __name__ == "__main__":
    configure_logging()
    run()
