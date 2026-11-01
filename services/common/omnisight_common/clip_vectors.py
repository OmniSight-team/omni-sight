"""The `clip_vectors` collection in Qdrant (OMNI-710): the InternVideo2 half of Algorithm 2.

The same payload, payload indexes and point id as `frame_vectors`: a frame and its clip are
one segment, so the id is what matches the two (B.2 line 4, D-29). Only the vector differs.
"""

from qdrant_client import QdrantClient, models

from omnisight_common.frame_vectors import FramePayload, ensure_collection

# The space where InternVideo2_CLIP_S's video and text meet (D-33; Phase A writes 768).
CLIP_VECTOR_SIZE = 512


def clip_point(payload: FramePayload, vector: list[float]) -> models.PointStruct:
    if len(vector) != CLIP_VECTOR_SIZE:
        raise ValueError(f"a clip vector has {CLIP_VECTOR_SIZE} dimensions, got {len(vector)}")
    return models.PointStruct(id=payload.segment_id, vector=vector, payload=payload.model_dump(mode="json"))


def ensure_clip_collection(client: QdrantClient, name: str) -> bool:
    """Create the collection if it is missing; never recreate it. True if it was created."""
    return ensure_collection(client, name, CLIP_VECTOR_SIZE)
