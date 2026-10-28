"""The embed queue (OMNI-705): admitted frames waiting for their vector.

NFR-5 applies to vectors too: an admitted frame that never gets a vector is a frame search
can never find. So the path from a stored segment to its point in `frame_vectors` is the
same kind of durable hand-over as the segment queue (OMNI-311): a durable queue, persistent
and confirmed messages, and an acknowledgement only after the work is safely stored.

- **query's consumer** publishes one `EmbedJob` per admitted frame, after the segment's
  row has committed (also when a redelivered message finds the row already there, since
  the first delivery may have died between the commit and this publish)
- **ai_workers** encodes the frame, upserts the point (id = segment id, D-29) and only then
  acknowledges. A job delivered twice upserts the same point twice: still one point

Both import this, so they agree on the message and the queue's arguments.
"""

from pika.adapters.blocking_connection import BlockingChannel
from pydantic import BaseModel

from omnisight_common.domain import Domain
from omnisight_common.frame_vectors import FramePayload
from omnisight_common.segment_queue import _declare_durable
from omnisight_common.segment_source_type import SegmentSourceType


class EmbedJob(BaseModel):
    """One admitted frame to encode: the frame's file and every payload field but the
    model, which only the encoder knows."""

    segment_id: int
    video_id: int | None
    camera_id: int | None
    source_type: SegmentSourceType
    domain: Domain
    timestamp_s: float
    captured_at: str
    frame_path: str
    thumb_path: str | None

    def payload(self, model: str, model_revision: str) -> FramePayload:
        return FramePayload(**self.model_dump(), model=model, model_revision=model_revision)


def declare_embed_queue(channel: BlockingChannel, queue: str) -> None:
    """Idempotent, like the segment queue's: durable, with a dead-letter queue for a job
    that can never be encoded (it does not parse, or its frame file cannot be read)."""
    _declare_durable(channel, queue)
