"""`clip_vectors` (OMNI-710): created once, never recreated, with `frame_vectors`' payload and
indexes. On qdrant-client's in-process mode; TC-3's clip half on the real Qdrant is
`scripts/verify_tc3_frame_vectors.py clip`.
"""

import pytest
from omnisight_common.clip_vectors import (
    CLIP_VECTOR_SIZE,
    clip_point,
    ensure_clip_collection,
)
from omnisight_common.domain import Domain
from omnisight_common.frame_vectors import FramePayload
from omnisight_common.segment_source_type import SegmentSourceType
from qdrant_client import QdrantClient, models

NAME = "clip_vectors"


def _payload(segment_id: int) -> FramePayload:
    return FramePayload(
        segment_id=segment_id,
        video_id=7,
        camera_id=None,
        source_type=SegmentSourceType.UPLOAD,
        domain=Domain.SURVEILLANCE,
        timestamp_s=1.5,
        captured_at="2026-10-19T09:00:01.500000+00:00",
        frame_path="/data/frames/7/000045.jpg",
        thumb_path="/data/thumbs/7/000045.jpg",
        model="OpenGVLab/InternVideo2_CLIP_S",
        model_revision="test",
    )


def _unit(axis: int) -> list[float]:
    vector = [0.0] * CLIP_VECTOR_SIZE
    vector[axis] = 1.0
    return vector


@pytest.fixture
def client():
    c = QdrantClient(":memory:")
    yield c
    c.close()


def test_collection_follows_the_model_cosine(client):
    assert ensure_clip_collection(client, NAME) is True

    params = client.get_collection(NAME).config.params.vectors
    assert params.size == 512
    assert params.distance == models.Distance.COSINE


def test_an_existing_collection_is_never_recreated(client):
    ensure_clip_collection(client, NAME)
    client.upsert(NAME, [clip_point(_payload(1), _unit(0))], wait=True)

    assert ensure_clip_collection(client, NAME) is False
    assert client.count(NAME).count == 1


def test_point_id_is_the_segment_id_so_a_second_import_overwrites(client):
    ensure_clip_collection(client, NAME)
    client.upsert(NAME, [clip_point(_payload(42), _unit(0))], wait=True)
    client.upsert(NAME, [clip_point(_payload(42), _unit(1))], wait=True)

    assert client.count(NAME).count == 1
    [point] = client.retrieve(NAME, [42], with_payload=True)
    assert set(point.payload) == set(FramePayload.model_fields)


def test_a_vector_of_the_wrong_size_is_refused():
    with pytest.raises(ValueError):
        clip_point(_payload(1), [1.0] * 768)
