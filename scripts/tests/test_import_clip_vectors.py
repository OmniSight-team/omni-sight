"""OMNI-710: the clip vector import's checks and its upsert, on qdrant-client's in-process mode."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from omnisight_common.clip_vectors import ensure_clip_collection
from omnisight_common.domain import Domain
from omnisight_common.frame_vectors import FramePayload
from omnisight_common.segment_source_type import SegmentSourceType
from qdrant_client import QdrantClient

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("import_clip_vectors", ROOT / "scripts" / "import_clip_vectors.py")
script = importlib.util.module_from_spec(spec)
importlib.sys.modules[spec.name] = script
spec.loader.exec_module(script)

NAME = "clip_vectors"


def _unit(n: int) -> np.ndarray:
    return np.eye(n, 512, dtype=np.float32)


def _job(segment_id: int):
    def payload(model: str, revision: str) -> FramePayload:
        return FramePayload(
            segment_id=segment_id, video_id=7, camera_id=None, source_type=SegmentSourceType.UPLOAD,
            domain=Domain.SURVEILLANCE, timestamp_s=1.5, captured_at="2026-10-19T09:00:01.500000+00:00",
            frame_path="/data/frames/7/000045.jpg", thumb_path=None, model=model, model_revision=revision,
        )

    return SimpleNamespace(payload=payload)


@pytest.fixture
def client():
    c = QdrantClient(":memory:")
    ensure_clip_collection(c, NAME)
    yield c
    c.close()


def test_a_rerun_leaves_one_point_per_segment(client):
    ids = np.array([11, 12, 13])
    jobs = {i: _job(i) for i in (11, 12, 13)}

    for _ in range(2):
        assert script.upsert_vectors(client, NAME, ids, _unit(3), jobs, "m", "r") == []

    assert client.count(NAME, exact=True).count == 3
    [point] = client.retrieve(NAME, [12], with_payload=True, with_vectors=True)
    assert (point.payload["model"], point.payload["model_revision"]) == ("m", "r")
    assert point.vector[1] == pytest.approx(1.0)


def test_a_segment_with_no_admitted_frame_is_reported_and_not_stored(client):
    unknown = script.upsert_vectors(client, NAME, np.array([11, 99]), _unit(2), {11: _job(11)}, "m", "r")

    assert unknown == [99]
    assert client.count(NAME, exact=True).count == 1


@pytest.mark.parametrize(
    "ids, vectors",
    [
        (np.array([1, 2]), np.eye(2, 768, dtype=np.float32)),  # the wrong size
        (np.array([1, 2, 3]), _unit(2)),  # fewer vectors than ids
        (np.array([1, 1]), _unit(2)),  # an id twice
        (np.array([1, 2]), _unit(2) * 2),  # not unit length
        (np.array([1, 2]), _unit(2) * np.nan),  # not finite
    ],
)
def test_bad_vectors_are_refused(ids, vectors):
    with pytest.raises(ValueError):
        script.check_vectors("x.npz", ids, vectors, 512)


def test_unit_vectors_of_the_right_size_pass():
    script.check_vectors("x.npz", np.array([1, 2]), _unit(2), 512)


def test_an_archive_of_another_model_is_refused():
    pins = {"clip_model_id": "m", "clip_model_revision": "r"}
    script.check_pins(pins, "m", "r")
    with pytest.raises(ValueError):
        script.check_pins(pins, "m", "another")
