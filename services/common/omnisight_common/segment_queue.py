"""The durable queue segments travel through (OMNI-311): the message contract,
the queue's declaration and how to reach the broker.

Ingestion (the producer) and query (the consumer) both import this, so the two
can never disagree about a queue argument — RabbitMQ refuses to redeclare an
existing queue with different arguments, which would otherwise show up as a
startup failure in whichever service happened to start second.

NFR-5 is the reason this exists: a frame that has been gated and accepted must
survive a crash of any process between the gate and the database. Two things
have to hold together for that, and dropping either loses data on a broker
restart — the queue is durable, and every message is persistent.
"""

import pika
from pika.adapters.blocking_connection import BlockingChannel
from pydantic import BaseModel

from omnisight_common.admission_reason import AdmissionReason
from omnisight_common.segment_source_type import SegmentSourceType
from omnisight_common.settings import CommonSettings

# A message the consumer cannot ever store (it does not parse) goes here
# instead of being requeued forever or silently deleted. A person can look at
# it; nothing retries it.
DEAD_LETTER_SUFFIX = ".dead"

# delivery_mode 2 — the broker writes the message to disk. Named so the
# publisher and the tests that check it say the same thing.
PERSISTENT = pika.DeliveryMode.Persistent


class SegmentMessage(BaseModel):
    """One gated frame, exactly as the segments table stores it.

    The same shape whether a file extractor or a live worker produced it —
    nothing downstream can tell the two apart, which is the point of moving
    both onto one queue.
    """

    video_id: int | None
    camera_id: int | None
    frame_index: int
    timestamp_s: float
    frame_path: str | None
    thumb_path: str | None
    motion_score: float | None
    admitted: bool
    source_type: SegmentSourceType
    clip_start_s: float | None = None
    clip_end_s: float | None = None
    admission_reason: AdmissionReason | None = None
    # Which extraction of the video produced this frame. Lets the consumer
    # recognise a message left over from an extraction that has since failed or
    # been replaced, and drop it instead of writing an old run's frame into a
    # newer run's video. None for a live frame, which has no extraction.
    extraction_id: str | None = None


def dead_letter_queue(queue: str) -> str:
    return queue + DEAD_LETTER_SUFFIX


def connection_parameters(settings: CommonSettings) -> pika.ConnectionParameters:
    return pika.ConnectionParameters(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        credentials=pika.PlainCredentials(settings.rabbitmq_user, settings.rabbitmq_password),
        # Long enough that a consumer busy in the database is not declared
        # dead, short enough that a killed process is noticed within a minute
        # and its unacknowledged messages go back to the queue.
        heartbeat=30,
        connection_attempts=3,
        retry_delay=2,
    )


def declare_segment_queue(channel: BlockingChannel, queue: str) -> None:
    """Idempotent: safe from both the producer and the consumer on every start."""
    dead = dead_letter_queue(queue)
    channel.queue_declare(queue=dead, durable=True)
    channel.queue_declare(
        queue=queue,
        durable=True,
        arguments={
            # Through the default exchange straight into the dead-letter queue.
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": dead,
        },
    )
