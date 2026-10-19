"""The `frame_vectors` collection in Qdrant (OMNI-703): its shape, its payload and the one
way a point is made.

Algorithm 2 (Phase A Appendix B.2) stores each admitted frame's SigLIP 2 embedding with its
metadata. ai_workers writes the points (OMNI-705) and query searches them (OMNI-706); both
import this, so the two can never disagree about the collection, a payload field or an id.

**Point id = segment id** (D-29, a deviation from B.2 line 4's `hash(camera_id, timestamp)`):
unique for every source, uploads included, and the id slice 8's `clip_vectors` uses for the
same frame. It also makes a write idempotent: a redelivered message upserts the same point
again instead of adding a second one.
"""

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, field_validator
from qdrant_client import QdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from omnisight_common.domain import Domain
from omnisight_common.segment_source_type import SegmentSourceType
from omnisight_common.settings import CommonSettings

# SigLIP 2 so400m's embedding size (Phase A §3.5.2, Algorithm 2 line 1).
FRAME_VECTOR_SIZE = 1152

# Filtered inside the vector search (OMNI-706), not after it, so each needs an index.
# `captured_at` is a datetime index, which takes RFC 3339 strings.
PAYLOAD_INDEXES: dict[str, models.PayloadSchemaType] = {
    "camera_id": models.PayloadSchemaType.INTEGER,
    "video_id": models.PayloadSchemaType.INTEGER,
    "captured_at": models.PayloadSchemaType.DATETIME,
}


class FramePayload(BaseModel):
    """What is stored next to a frame's vector: enough to show and filter a search hit
    without asking Postgres."""

    segment_id: int
    video_id: int | None
    camera_id: int | None
    source_type: SegmentSourceType
    domain: Domain
    # Seconds into the video for an upload; Unix time for a live frame (as on `segments`),
    # to the microsecond (see `_to_the_microsecond`).
    timestamp_s: float
    # Absolute capture time, RFC 3339 in UTC, for every source (see `captured_at`).
    captured_at: str
    frame_path: str
    thumb_path: str | None
    model: str
    model_revision: str

    @field_validator("timestamp_s")
    @classmethod
    def _to_the_microsecond(cls, value: float) -> float:
        # Qdrant 1.19 does not read every float back exactly: a value that needs 17
        # significant digits (0.9175842509175843, a frame index over 23.976 fps) came
        # back one unit in the last place off in OMNI-703's TC-3. Rounded to the
        # microsecond, like `captured_at`, a timestamp has at most 16 digits and round-
        # trips exactly. A frame's time means nothing finer than that.
        return round(value, 6)


def captured_at(source_type: SegmentSourceType, timestamp_s: float, uploaded_at: datetime | None) -> str:
    """The absolute time a frame shows, so one time filter covers cameras and files.

    A live frame's `timestamp_s` already is its capture time (Unix seconds). A file
    carries no wall-clock time, so its frame is placed at the upload time plus its offset
    into the video (D-29).
    """
    if source_type == SegmentSourceType.CAMERA:
        moment = datetime.fromtimestamp(timestamp_s, UTC)
    else:
        if uploaded_at is None:
            raise ValueError("an uploaded frame needs its video's upload time")
        moment = uploaded_at.astimezone(UTC) + timedelta(seconds=timestamp_s)
    return moment.isoformat()


def frame_point(payload: FramePayload, vector: list[float]) -> models.PointStruct:
    if len(vector) != FRAME_VECTOR_SIZE:
        raise ValueError(f"a frame vector has {FRAME_VECTOR_SIZE} dimensions, got {len(vector)}")
    return models.PointStruct(id=payload.segment_id, vector=vector, payload=payload.model_dump(mode="json"))


def qdrant_client(settings: CommonSettings) -> QdrantClient:
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port, timeout=settings.qdrant_timeout_s)


def ensure_frame_collection(client: QdrantClient, name: str) -> bool:
    """Create the collection if it is missing; never recreate it. True if it was created.

    The payload indexes are asked for every time: creating one that exists changes
    nothing, and a startup that died between the collection and its indexes is repaired
    by the next one.
    """
    created = False
    if not client.collection_exists(name):
        try:
            # Cosine (B.2); Qdrant's vector index is HNSW, here with its default m and
            # ef_construct.
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(size=FRAME_VECTOR_SIZE, distance=models.Distance.COSINE),
            )
            created = True
        except UnexpectedResponse:
            # Another service created it between the check and the call.
            if not client.collection_exists(name):
                raise
    for field, schema in PAYLOAD_INDEXES.items():
        client.create_payload_index(collection_name=name, field_name=field, field_schema=schema, wait=True)
    return created
