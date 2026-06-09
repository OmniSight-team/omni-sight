"""Algorithm 2 — Dual-Stream Embedding Generation (frame path, SigLIP2 only).

Implements pseudocode steps 1, 4, 5:
  1: e_f <- SigLIP2_image(f_t);  e_f <- e_f / ||e_f||
  4: meta <- { timestamp, camera_id, domain, frame_id, thumb(f_t) }
  5: Qdrant.upsert(DB_frame, e_f, meta)

Steps 2–3, 6 (InternVideo2 clip path) are deferred to Phase B.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from qdrant_client import QdrantClient

from .embedder import embed_frame
from .store import ensure_collection, upsert_frame

logger = logging.getLogger(__name__)


@dataclass
class FrameRecord:
    frame_id: str
    embedding: np.ndarray  # (EMBED_DIM,) L2-normalized


def process_frame(
    client: QdrantClient,
    frame_bgr: np.ndarray,
    camera_id: str,
    timestamp: str,
    domain: str,
    source_id: str = "",
    fps: float = 30.0,
) -> FrameRecord:
    """Embed one admitted frame and persist it to Qdrant."""
    ensure_collection(client)
    embedding = embed_frame(frame_bgr)
    frame_id = upsert_frame(
        client, embedding, frame_bgr, camera_id, timestamp, domain,
        source_id=source_id, fps=fps,
    )
    logger.info("Processed frame %s (cam=%s)", frame_id, camera_id)
    return FrameRecord(frame_id=frame_id, embedding=embedding)
