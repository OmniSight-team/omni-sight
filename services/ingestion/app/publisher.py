"""Publishing gated frames to the durable queue (OMNI-311).

The one place a segment record leaves ingestion. A file extractor publishes a
whole recording through `publish_segments`; the live capture worker
(OMNI-312) holds a `SegmentPublisher` open for as long as it runs and
publishes one frame at a time. Both go through the same `publish`, so nothing
downstream can tell the two sources apart.

Like pipeline.py, this imports nothing from `app.*`: the broker and queue
arrive as arguments. That keeps it independent of the service around it, and
loadable by file path in a test session that also has query's own `app`
package on the path.
"""

from collections.abc import Iterable
from dataclasses import asdict
from typing import Any, Self

import pika
from omnisight_common import (
    CameraEvent,
    CameraStatsReport,
    SegmentMessage,
    declare_camera_event_queue,
    declare_segment_queue,
)
from omnisight_common.segment_queue import PERSISTENT
from pika.exceptions import AMQPError


class PublishError(Exception):
    """A segment could not be handed to the broker. Always reported, never
    swallowed: a frame that was gated but neither published nor reported is
    exactly the silent loss the queue exists to prevent."""


class SegmentPublisher:
    """One connection to the broker, kept open across many publishes.

    Every message is persistent and confirmed: `confirm_delivery` makes each
    publish wait for the broker's acknowledgement that the message is safely
    queued (and, being persistent, on disk), and `mandatory=True` turns a
    message that cannot be routed into an error instead of a silent drop.

    Not thread-safe (a pika blocking connection never is): create it, use it
    and close it on one thread.
    """

    def __init__(
        self,
        connection_params: pika.ConnectionParameters,
        queue: str,
        event_queue: str | None = None,
    ):
        self._queue = queue
        self._event_queue = event_queue
        self.published = 0
        try:
            self._connection = pika.BlockingConnection(connection_params)
            self._channel = self._connection.channel()
            self._channel.confirm_delivery()
            declare_segment_queue(self._channel, queue)
            if event_queue is not None:
                declare_camera_event_queue(self._channel, event_queue)
        except AMQPError as exc:
            raise PublishError(f"could not connect to the segment queue: {exc!r}") from exc

    def publish(self, record: Any, extraction_id: str | None = None) -> None:
        """Publish one pipeline `SegmentRecord`."""
        message = SegmentMessage(**asdict(record), extraction_id=extraction_id)
        try:
            self._channel.basic_publish(
                exchange="",
                routing_key=self._queue,
                body=message.model_dump_json().encode(),
                properties=pika.BasicProperties(
                    delivery_mode=PERSISTENT,
                    content_type="application/json",
                ),
                mandatory=True,
            )
        except AMQPError as exc:
            raise PublishError(
                f"could not publish to the segment queue after {self.published}: {exc!r}"
            ) from exc
        self.published += 1

    def publish_event(
        self, camera_id: int, status: str, at: float, worker_id: str | None = None
    ) -> None:
        """Tell the camera status queue that a camera became reachable or not
        (OMNI-313), persistent and confirmed like a segment."""
        if self._event_queue is None:
            raise PublishError("this publisher was not given a camera event queue")
        event = CameraEvent(camera_id=camera_id, status=status, at=at, worker_id=worker_id)
        try:
            self._channel.basic_publish(
                exchange="",
                routing_key=self._event_queue,
                body=event.model_dump_json().encode(),
                properties=pika.BasicProperties(
                    delivery_mode=PERSISTENT,
                    content_type="application/json",
                ),
                mandatory=True,
            )
        except AMQPError as exc:
            raise PublishError(f"could not publish a camera event: {exc!r}") from exc

    def publish_stats(self, report: dict[str, Any]) -> None:
        """Send a worker's running totals to the camera queue (OMNI-314),
        persistent and confirmed like everything else."""
        if self._event_queue is None:
            raise PublishError("this publisher was not given a camera event queue")
        message = CameraStatsReport(**report)
        try:
            self._channel.basic_publish(
                exchange="",
                routing_key=self._event_queue,
                body=message.model_dump_json().encode(),
                properties=pika.BasicProperties(
                    delivery_mode=PERSISTENT,
                    content_type="application/json",
                ),
                mandatory=True,
            )
        except AMQPError as exc:
            raise PublishError(f"could not publish camera stats: {exc!r}") from exc

    def backlog(self) -> int:
        """How many segments are waiting in the queue. Not counting ones a
        consumer is holding unacknowledged, so it drops the moment a consumer
        picks something up; it is a measure of how far behind the consumers are,
        which is what a producer needs to know before adding more."""
        try:
            return self._channel.queue_declare(self._queue, passive=True).method.message_count
        except AMQPError as exc:
            raise PublishError(f"could not read the queue depth: {exc!r}") from exc

    def keepalive(self) -> None:
        """Let the connection answer the broker's heartbeats. A blocking
        connection only does that while something is using it, so a worker that
        is waiting out a backoff — up to half a minute without publishing —
        would otherwise have the broker close the connection on it."""
        try:
            self._connection.process_data_events(time_limit=0)
        except AMQPError as exc:
            raise PublishError(f"the connection to the broker was lost: {exc!r}") from exc

    def close(self) -> None:
        try:
            if self._connection.is_open:
                self._connection.close()
        except AMQPError:
            pass  # already gone; nothing left to release

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def publish_segments(
    records: Iterable[Any],
    extraction_id: str | None,
    *,
    connection_params: pika.ConnectionParameters,
    queue: str,
) -> int:
    """Publish every record and return how many went out."""
    with SegmentPublisher(connection_params, queue) as publisher:
        for record in records:
            publisher.publish(record, extraction_id)
        return publisher.published
