"""Qdrant storage for Algorithm 2 frame embeddings (DB_frame collection)."""
from __future__ import annotations

import base64
import logging
import uuid

import cv2
import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from .embedder import EMBED_DIM

logger = logging.getLogger(__name__)

_COLLECTION = "DB_frame"
_THUMB_W, _THUMB_H = 320, 180


def _frame_id(camera_id: str, timestamp: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{camera_id}:{timestamp}"))


def _thumbnail_b64(frame_bgr: np.ndarray) -> str:
    thumb = cv2.resize(frame_bgr, (_THUMB_W, _THUMB_H))
    ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buf.tobytes()).decode() if ok else ""


def ensure_collection(client: QdrantClient) -> None:
    existing = {c.name for c in client.get_collections().collections}
    if _COLLECTION not in existing:
        client.create_collection(
            _COLLECTION,
            vectors_config=VectorParams(size=EMBED_DIM, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection %s", _COLLECTION)


def upsert_frame(
    client: QdrantClient,
    embedding: np.ndarray,
    frame_bgr: np.ndarray,
    camera_id: str,
    timestamp: str,
    domain: str,
    source_id: str = "",
    fps: float = 30.0,
) -> str:
    """Store one frame embedding; returns the frame_id string."""
    fid = _frame_id(camera_id, timestamp)
    payload = {
        "timestamp": timestamp,
        "camera_id": camera_id,
        "domain": domain,
        "frame_id": fid,
        "thumb": _thumbnail_b64(frame_bgr),
        "source_id": source_id or camera_id,
        "fps": fps,
    }
    vec = embedding
    while vec.ndim > 1:  # collapse (batch, seq, dim) → (dim,) by mean-pooling leading dims
        vec = vec.mean(axis=0)
    assert vec.ndim == 1, f"Expected 1-D embedding, got shape {vec.shape}"
    logger.debug("Upserting frame %s with vector shape %s", fid, vec.shape)
    client.upsert(
        collection_name=_COLLECTION,
        points=[PointStruct(id=fid, vector=vec.tolist(), payload=payload)],
    )
    logger.debug("Upserted frame %s", fid)
    return fid
