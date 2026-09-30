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

import json
import logging
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from enum import Enum

import pika
from omnisight_common import (
    CameraEvent,
    CameraStatsReport,
    CameraStatus,
    SegmentMessage,
    VideoStatus,
    connection_parameters,
    declare_camera_event_queue,
    declare_segment_queue,
)
from pydantic import ValidationError
from sqlalchemy import or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.logging_conf import configure_logging
from app.models import Camera, CameraStats, Segment, Video
from app.settings import settings

logger = logging.getLogger("app.consumer")

MAX_BACKOFF_S = 30.0

# The running totals a stats report carries. Each is a column of `camera_stats`
# with a `session_` twin holding how much of it has been counted for the current
# worker.
STATS_COUNTERS = (
    "captured",
    "dropped",
    "gated",
    "admitted_motion",
    "admitted_heartbeat",
    "discarded",
)


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
        if inserted is not None and message.video_id is None:
            _refresh_last_seen(db, message.camera_id, message.timestamp_s)
        db.commit()
        return Outcome.STORED if inserted is not None else Outcome.DUPLICATE


def _refresh_last_seen(db, camera_id: int, timestamp_s: float) -> None:
    """A frame from the camera is the freshest evidence it is alive (OMNI-313), so
    `last_seen_at` follows the frames as they are stored rather than waiting for
    the next poll. It only moves forward, and only when the new time is at least
    the configured interval past the old one: one row updated five times a second
    per camera would be all write and no information."""
    seen = datetime.fromtimestamp(timestamp_s, UTC)
    db.execute(
        update(Camera)
        .where(
            Camera.id == camera_id,
            or_(
                Camera.last_seen_at.is_(None),
                Camera.last_seen_at < seen - timedelta(seconds=settings.camera_last_seen_interval_s),
            ),
        )
        .values(last_seen_at=seen)
    )


def apply_camera_event(body: bytes) -> Outcome:
    """Record that a camera became reachable or not, and commit it (OMNI-313).
    Returns only after the commit, like `store_segment`.

    A camera an operator has disabled stays disabled: whether it is in use is a
    decision, and a stream cannot overrule it. A camera that no longer exists has
    nothing to update.
    """
    try:
        event = CameraEvent.model_validate_json(body)
    except ValidationError as exc:
        raise MalformedMessage(str(exc)) from exc

    with SessionLocal() as db:
        camera = db.execute(
            select(Camera).where(Camera.id == event.camera_id).with_for_update()
        ).scalar_one_or_none()
        if camera is None or camera.status == CameraStatus.DISABLED:
            return Outcome.STALE
        camera.status = event.status
        if event.status == CameraStatus.CONNECTED:
            seen = datetime.fromtimestamp(event.at, UTC)
            if camera.last_seen_at is None or camera.last_seen_at < seen:
                camera.last_seen_at = seen
        db.commit()
        return Outcome.STORED


def apply_camera_stats(body: bytes) -> Outcome:
    """Fold a live worker's running totals into `camera_stats` and commit
    (OMNI-314). Returns only after the commit.

    The report carries the worker's totals for its own session. What is added to
    each of the camera's lifetime counters (`STATS_COUNTERS`) is the difference
    from the last total counted for that worker, never the total itself, so a
    report delivered
    twice adds nothing the second time, and one arriving late (below what is
    already counted) adds nothing at all. The rate and the session start are only
    taken from a report at least as recent as the last one, so a late report
    cannot turn a running camera back into a stopped one.
    """
    try:
        report = CameraStatsReport.model_validate_json(body)
    except ValidationError as exc:
        raise MalformedMessage(str(exc)) from exc

    with SessionLocal() as db:
        if db.get(Camera, report.camera_id) is None:
            return Outcome.STALE
        db.execute(
            pg_insert(CameraStats)
            .values(camera_id=report.camera_id)
            .on_conflict_do_nothing(index_elements=["camera_id"])
        )
        stats = db.execute(
            select(CameraStats).where(CameraStats.camera_id == report.camera_id).with_for_update()
        ).scalar_one()

        new_session = stats.session_id != report.worker_id
        if new_session:
            stats.session_id = report.worker_id
        for counter in STATS_COUNTERS:
            counted = 0 if new_session else getattr(stats, f"session_{counter}")
            reported = getattr(report, counter)
            setattr(stats, counter, getattr(stats, counter) + max(0, reported - counted))
            setattr(stats, f"session_{counter}", max(counted, reported))

        made_at = datetime.fromtimestamp(report.at, UTC)
        if stats.reported_at is None or made_at >= stats.reported_at:
            stats.reported_at = made_at
            stats.fps_effective = report.fps_effective if report.running else 0.0
            stats.session_started_at = (
                datetime.fromtimestamp(report.started_at, UTC) if report.running else None
            )
        if report.last_frame_at is not None:
            last_frame = datetime.fromtimestamp(report.last_frame_at, UTC)
            if stats.last_frame_at is None or last_frame > stats.last_frame_at:
                stats.last_frame_at = last_frame
        db.commit()
        return Outcome.STORED


def apply_camera_message(body: bytes) -> Outcome:
    """The camera queue carries more than one kind of message (a status change,
    a stats report); this picks the handler. A message without a `kind` is a
    status change, which is all the queue carried before reports existed."""
    try:
        kind = json.loads(body).get("kind", "status")
    except (ValueError, AttributeError) as exc:
        raise MalformedMessage("a camera message must be a JSON object") from exc
    if kind == "status":
        return apply_camera_event(body)
    if kind == "stats":
        return apply_camera_stats(body)
    raise MalformedMessage(f"unknown camera message kind {kind!r}")


def _on_event(channel, method, _properties, body: bytes) -> None:
    try:
        outcome = apply_camera_message(body)
    except MalformedMessage as exc:
        logger.error(
            "camera event could not be parsed, dead-lettered",
            extra={"extra_fields": {"error": str(exc)[:300]}},
        )
        channel.basic_nack(method.delivery_tag, requeue=False)
        return
    channel.basic_ack(method.delivery_tag)
    if outcome is not Outcome.STORED:
        logger.info(
            "camera event acknowledged without a change",
            extra={"extra_fields": {"outcome": outcome.value}},
        )


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


def start(channel, on_message=_on_message, on_event=None) -> None:
    """Declare the queues, limit what this consumer may hold unacknowledged, and
    subscribe. Deliveries then arrive as the connection's I/O loop runs.
    `on_event` also subscribes to the camera status queue (OMNI-313)."""
    declare_segment_queue(channel, settings.segment_queue)
    # The most unacknowledged messages this consumer may hold. Without it the
    # broker pushes the whole backlog at the first consumer to connect, and a
    # second consumer sits idle while the first works through it.
    channel.basic_qos(prefetch_count=settings.segment_prefetch)
    channel.basic_consume(queue=settings.segment_queue, on_message_callback=on_message, auto_ack=False)
    if on_event is not None:
        declare_camera_event_queue(channel, settings.camera_event_queue)
        channel.basic_consume(
            queue=settings.camera_event_queue, on_message_callback=on_event, auto_ack=False
        )


def consume() -> None:
    """One connection's lifetime: returns only if the broker closes it cleanly,
    raises on anything else."""
    with closing(pika.BlockingConnection(connection_parameters(settings))) as connection:
        channel = connection.channel()
        start(channel, on_event=_on_event)
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
