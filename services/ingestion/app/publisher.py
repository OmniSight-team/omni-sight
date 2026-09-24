"""Publishing gated frames to the durable queue (OMNI-311).

The one place a segment record leaves ingestion. A file extractor uses it now;
the live capture worker (OMNI-312) will call the same function, so both
producers share one path and nothing downstream can tell them apart.

Like pipeline.py, this imports nothing from `app.*`: the broker and the queue
arrive as arguments. That keeps it independent of the service around it, and
loadable by file path in a test session that also has query's own `app`
package on the path.
"""

from collections.abc import Iterable
from contextlib import closing
from dataclasses import asdict
from typing import Any

import pika
from omnisight_common import (
    SegmentMessage,
    declare_segment_queue,
)
from omnisight_common.segment_queue import PERSISTENT
from pika.exceptions import AMQPError


class PublishError(Exception):
    """A segment could not be handed to the broker. Always reported, never
    swallowed: a frame that was gated but neither published nor reported is
    exactly the silent loss the queue exists to prevent."""


def publish_segments(
    records: Iterable[Any],
    extraction_id: str | None,
    *,
    connection_params: pika.ConnectionParameters,
    queue: str,
) -> int:
    """Publish every record (a pipeline `SegmentRecord`), each one persistent
    and confirmed by the broker, and return how many went out.

    `confirm_delivery` makes each publish wait for the broker's acknowledgement
    that the message is safely queued (and, being persistent, on disk). A
    message the broker refuses or cannot route raises instead of vanishing.
    """
    published = 0
    try:
        with closing(pika.BlockingConnection(connection_params)) as connection:
            channel = connection.channel()
            channel.confirm_delivery()
            declare_segment_queue(channel, queue)
            for record in records:
                message = SegmentMessage(**asdict(record), extraction_id=extraction_id)
                channel.basic_publish(
                    exchange="",
                    routing_key=queue,
                    body=message.model_dump_json().encode(),
                    properties=pika.BasicProperties(
                        delivery_mode=PERSISTENT,
                        content_type="application/json",
                    ),
                    # An unroutable message is returned to us as an error
                    # rather than dropped by the broker.
                    mandatory=True,
                )
                published += 1
    except AMQPError as exc:
        raise PublishError(f"could not publish to the segment queue after {published}: {exc!r}") from exc
    return published
