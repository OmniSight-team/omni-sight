"""`frame_vectors` (OMNI-703): created once, never recreated; a point's id is its segment id,
so writing the same frame twice leaves one point; `captured_at` is absolute for every source.

Runs on qdrant-client's in-process mode, so it needs no server. TC-3 itself, on the real
Qdrant in the stack and across a restart, is `scripts/verify_tc3_frame_vectors.py`.
"""

from datetime import UTC, datetime

import pytest
from omnisight_common.domain import Domain
from omnisight_common.frame_vectors import (
    FRAME_VECTOR_SIZE,
    FramePayload,
    captured_at,
    ensure_frame_collection,
    frame_point,
)
from omnisight_common.segment_source_type import SegmentSourceType
from qdrant_client import QdrantClient, models

NAME = "frame_vectors"


def _payload(segment_id: int, **changes) -> FramePayload:
    fields = dict(
        segment_id=segment_id,
        video_id=7,
        camera_id=None,
        source_type=SegmentSourceType.UPLOAD,
        domain=Domain.SURVEILLANCE,
        timestamp_s=1.5,
        captured_at="2026-10-19T09:00:01.500000+00:00",
        frame_path="/data/frames/7/000045.jpg",
        thumb_path="/data/thumbs/7/000045.jpg",
        model="google/siglip2-so400m-patch14-384",
        model_revision="test",
    )
    fields.update(changes)
    return FramePayload(**fields)


def _unit(axis: int) -> list[float]:
    vector = [0.0] * FRAME_VECTOR_SIZE
    vector[axis] = 1.0
    return vector


@pytest.fixture
def client():
    c = QdrantClient(":memory:")
    yield c
    c.close()


def test_collection_is_created_with_phase_a_shape(client):
    assert ensure_frame_collection(client, NAME) is True

    params = client.get_collection(NAME).config.params.vectors
    assert params.size == 1152
    assert params.distance == models.Distance.COSINE


def test_an_existing_collection_is_never_recreated(client):
    ensure_frame_collection(client, NAME)
    client.upsert(NAME, [frame_point(_payload(1), _unit(0))], wait=True)

    assert ensure_frame_collection(client, NAME) is False
    assert client.count(NAME).count == 1


def test_point_id_is_the_segment_id_and_a_redelivery_overwrites_it(client):
    ensure_frame_collection(client, NAME)
    client.upsert(NAME, [frame_point(_payload(42), _unit(0))], wait=True)
    client.upsert(NAME, [frame_point(_payload(42, frame_path="/data/frames/7/again.jpg"), _unit(1))], wait=True)

    assert client.count(NAME).count == 1
    [point] = client.retrieve(NAME, [42], with_payload=True)
    assert point.payload["segment_id"] == 42
    assert point.payload["frame_path"] == "/data/frames/7/again.jpg"


def test_a_vector_of_the_wrong_size_is_refused():
    with pytest.raises(ValueError):
        frame_point(_payload(1), [1.0] * 768)


def test_payload_is_stored_as_plain_json():
    stored = frame_point(_payload(3), _unit(0)).payload

    assert stored["source_type"] == "upload"
    assert stored["domain"] == "surveillance"
    assert set(stored) == set(FramePayload.model_fields)


def test_timestamp_is_kept_to_the_microsecond():
    # 1078 / 23.976 needs 17 significant digits, which Qdrant did not read back exactly.
    assert _payload(1, timestamp_s=1078 / 23.976).timestamp_s == 44.961628
    assert _payload(1, timestamp_s=1_760_864_401.2003456).timestamp_s == 1_760_864_401.200346


def test_captured_at_of_a_live_frame_is_its_capture_time():
    at = captured_at(SegmentSourceType.CAMERA, 1_760_864_401.25, None)

    assert at == "2025-10-19T09:00:01.250000+00:00"


def test_captured_at_of_an_uploaded_frame_is_upload_time_plus_offset():
    uploaded = datetime(2026, 10, 19, 9, 0, 0, tzinfo=UTC)

    assert captured_at(SegmentSourceType.UPLOAD, 61.5, uploaded) == "2026-10-19T09:01:01.500000+00:00"


def test_an_uploaded_frame_needs_its_upload_time():
    with pytest.raises(ValueError):
        captured_at(SegmentSourceType.UPLOAD, 1.0, None)
