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
_THUMB_W, _THUMB_H = 64, 36


def _frame_id(camera_id: str, timestamp: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{camera_id}:{timestamp}"))


def _thumbnail_b64(frame_bgr: np.ndarray) -> str:
    thumb = cv2.resize(frame_bgr, (_THUMB_W, _THUMB_H))
    ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 70])
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
) -> str:
    """Store one frame embedding; returns the frame_id string."""
    fid = _frame_id(camera_id, timestamp)
    payload = {
        "timestamp": timestamp,
        "camera_id": camera_id,
        "domain": domain,
        "frame_id": fid,
        "thumb": _thumbnail_b64(frame_bgr),
    }
    client.upsert(
        collection_name=_COLLECTION,
        points=[PointStruct(id=fid, vector=embedding.tolist(), payload=payload)],
    )
    logger.debug("Upserted frame %s", fid)
    return fid
