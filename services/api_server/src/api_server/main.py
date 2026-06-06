"""OmniSight API server — video ingestion and semantic search."""
from __future__ import annotations

import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

_qdrant: QdrantClient | None = None


def _client() -> QdrantClient:
    if _qdrant is None:
        raise HTTPException(500, "Qdrant not initialised")
    return _qdrant


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _qdrant
    _qdrant = QdrantClient(":memory:")
    logger.info("Qdrant in-memory ready")
    yield
    _qdrant = None


app = FastAPI(title="OmniSight API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── /health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── /ingest ───────────────────────────────────────────────────────────────────

@app.post("/ingest")
def ingest(video: UploadFile = File(...)):
    """Accept a video file, run ROI sampler + SigLIP2, store in Qdrant."""
    from ai_worker_frame.pipeline import process_frame
    from ingestion.sampler import VideoFileSource, roi_aware_sampler

    client = _client()
    suffix = Path(video.filename or "video.mp4").suffix or ".mp4"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(video.file.read())
        tmp_path = tmp.name

    count = 0
    try:
        source = VideoFileSource(tmp_path)
        for payload in roi_aware_sampler(source, source_id="upload"):
            process_frame(
                client=client,
                frame_bgr=payload.frame,
                camera_id="upload",
                timestamp=str(payload.t),
                domain="uploaded",
            )
            count += 1
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    logger.info("Indexed %d frames", count)
    return {"frames_indexed": count}


# ── /search ───────────────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    limit: int = 12


@app.post("/search")
def search(req: SearchRequest):
    """Encode a text query with SigLIP2 and return matching frames."""
    import torch

    from ai_worker_frame.embedder import _load_model
    from ai_worker_frame.store import _COLLECTION

    client = _client()
    processor, model, device = _load_model()

    inputs = processor(
        text=[req.query],
        return_tensors="pt",
        padding="max_length",
        max_length=64,
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        features = model.get_text_features(**inputs)

    vec: np.ndarray = features[0].cpu().float().numpy()
    norm = np.linalg.norm(vec)
    if norm > 0.0:
        vec = vec / norm

    try:
        hits = client.search(
            collection_name=_COLLECTION,
            query_vector=vec.tolist(),
            limit=req.limit,
        )
    except Exception:
        return {"results": []}

    return {
        "results": [
            {
                "frame_id": h.id,
                "score": round(float(h.score), 4),
                "timestamp": h.payload.get("timestamp", ""),
                "camera_id": h.payload.get("camera_id", ""),
                "thumb": h.payload.get("thumb", ""),
            }
            for h in hits
        ]
    }
