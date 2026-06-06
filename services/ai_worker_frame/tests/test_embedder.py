"""Tests for Algorithm 2 — SigLIP2 frame embedding (ai_worker_frame)."""
from __future__ import annotations

import base64
import sys
import uuid
from unittest.mock import MagicMock

import numpy as np
import pytest


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def small_frame():
    """64×64 synthetic BGR frame."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)


@pytest.fixture(autouse=False)
def torch_stub(monkeypatch):
    """Inject a minimal torch stub so tests run without the real package."""
    stub = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = lambda s: None
    ctx.__exit__ = MagicMock(return_value=False)
    stub.no_grad.return_value = ctx
    stub.cuda.is_available.return_value = False
    monkeypatch.setitem(sys.modules, "torch", stub)
    monkeypatch.setitem(sys.modules, "transformers", MagicMock())
    return stub


# ── store helpers ─────────────────────────────────────────────────────────────

class TestFrameId:
    def test_valid_uuid(self):
        from ai_worker_frame.store import _frame_id
        fid = _frame_id("cam-1", "2025-01-01T00:00:00")
        uuid.UUID(fid)  # raises ValueError if invalid

    def test_deterministic(self):
        from ai_worker_frame.store import _frame_id
        assert _frame_id("cam-1", "t1") == _frame_id("cam-1", "t1")

    def test_unique_across_timestamps(self):
        from ai_worker_frame.store import _frame_id
        assert _frame_id("cam-1", "t1") != _frame_id("cam-1", "t2")

    def test_unique_across_cameras(self):
        from ai_worker_frame.store import _frame_id
        assert _frame_id("cam-1", "t1") != _frame_id("cam-2", "t1")


class TestThumbnail:
    def test_returns_valid_base64(self, small_frame):
        from ai_worker_frame.store import _thumbnail_b64
        b64 = _thumbnail_b64(small_frame)
        assert b64
        decoded = base64.b64decode(b64)
        assert len(decoded) > 0

    def test_large_frame_produces_thumbnail(self):
        from ai_worker_frame.store import _thumbnail_b64, _THUMB_W, _THUMB_H
        import cv2
        rng = np.random.default_rng(1)
        frame = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        b64 = _thumbnail_b64(frame)
        assert b64
        raw = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        thumb = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        assert thumb.shape == (_THUMB_H, _THUMB_W, 3)


# ── embed_frame ───────────────────────────────────────────────────────────────

class TestEmbedFrame:
    def test_shape_and_l2_norm(self, small_frame, torch_stub, monkeypatch):
        from ai_worker_frame import embedder

        embedder._load_model.cache_clear()

        raw = np.full(embedder.EMBED_DIM, 2.0, dtype=np.float32)

        tensor_mock = MagicMock()
        tensor_mock.cpu.return_value = tensor_mock
        tensor_mock.float.return_value = tensor_mock
        tensor_mock.numpy.return_value = raw

        features_mock = MagicMock()
        features_mock.__getitem__ = MagicMock(return_value=tensor_mock)

        model_mock = MagicMock()
        model_mock.get_image_features.return_value = features_mock
        model_mock.to.return_value = model_mock

        processor_mock = MagicMock()
        processor_mock.return_value = {}

        monkeypatch.setattr(embedder, "_load_model", lambda: (processor_mock, model_mock, "cpu"))

        result = embedder.embed_frame(small_frame)

        assert result.shape == (embedder.EMBED_DIM,)
        assert result.dtype == np.float32
        assert np.isclose(np.linalg.norm(result), 1.0, atol=1e-6)

    def test_zero_vector_not_divided(self, small_frame, torch_stub, monkeypatch):
        from ai_worker_frame import embedder

        embedder._load_model.cache_clear()

        raw = np.zeros(embedder.EMBED_DIM, dtype=np.float32)

        tensor_mock = MagicMock()
        tensor_mock.cpu.return_value = tensor_mock
        tensor_mock.float.return_value = tensor_mock
        tensor_mock.numpy.return_value = raw

        features_mock = MagicMock()
        features_mock.__getitem__ = MagicMock(return_value=tensor_mock)

        model_mock = MagicMock()
        model_mock.get_image_features.return_value = features_mock
        model_mock.to.return_value = model_mock

        processor_mock = MagicMock()
        processor_mock.return_value = {}

        monkeypatch.setattr(embedder, "_load_model", lambda: (processor_mock, model_mock, "cpu"))

        result = embedder.embed_frame(small_frame)

        assert result.shape == (embedder.EMBED_DIM,)
        assert np.all(result == 0.0)  # zero vector left unchanged — no division by zero


# ── upsert_frame ──────────────────────────────────────────────────────────────

class TestUpsertFrame:
    def test_calls_qdrant_upsert(self, small_frame):
        from ai_worker_frame.store import upsert_frame, _COLLECTION, _frame_id

        embedding = np.ones(1152, dtype=np.float32)
        embedding /= np.linalg.norm(embedding)

        client = MagicMock()
        client.get_collections.return_value.collections = []

        fid = upsert_frame(client, embedding, small_frame, "cam-1", "2025-01-01T00:00:00", "test")

        assert fid == _frame_id("cam-1", "2025-01-01T00:00:00")
        client.upsert.assert_called_once()

    def test_payload_fields(self, small_frame):
        from ai_worker_frame.store import upsert_frame
        from qdrant_client.models import PointStruct

        embedding = np.ones(1152, dtype=np.float32)
        embedding /= np.linalg.norm(embedding)

        client = MagicMock()
        client.get_collections.return_value.collections = []

        upsert_frame(client, embedding, small_frame, "cam-2", "ts-123", "surveillance")

        call_kwargs = client.upsert.call_args.kwargs
        points = call_kwargs["points"]
        assert len(points) == 1
        p = points[0]
        assert p.payload["camera_id"] == "cam-2"
        assert p.payload["timestamp"] == "ts-123"
        assert p.payload["domain"] == "surveillance"
        assert p.payload["thumb"]  # non-empty thumbnail

    def test_vector_stored_as_list(self, small_frame):
        from ai_worker_frame.store import upsert_frame

        embedding = np.ones(1152, dtype=np.float32)
        embedding /= np.linalg.norm(embedding)

        client = MagicMock()
        upsert_frame(client, embedding, small_frame, "c", "t", "d")

        points = client.upsert.call_args.kwargs["points"]
        assert isinstance(points[0].vector, list)
        assert len(points[0].vector) == 1152
