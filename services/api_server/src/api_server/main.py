"""OmniSight API server — video ingestion and semantic search."""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

_qdrant: QdrantClient | None = None

# Persistent video store: source_id -> {path, fps, suffix}
_UPLOADS: dict[str, dict] = {}

UPLOAD_DIR = Path("./uploads")


def _client() -> QdrantClient:
    if _qdrant is None:
        raise HTTPException(500, "Qdrant not initialised")
    return _qdrant


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _qdrant
    UPLOAD_DIR.mkdir(exist_ok=True)
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
    expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
)


# ── /health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}


# ── /ingest ───────────────────────────────────────────────────────────────────

@app.post("/ingest")
async def ingest(video: UploadFile = File(...)):
    """Accept a video file, stream ROI sampler + SigLIP2 progress via SSE."""
    from ai_worker_frame.pipeline import process_frame
    from ingestion.sampler import VideoFileSource, roi_aware_sampler

    client = _client()
    suffix = Path(video.filename or "video.mp4").suffix or ".mp4"
    source_id = uuid.uuid4().hex[:12]
    save_path = UPLOAD_DIR / f"{source_id}{suffix}"

    content = await video.read()
    save_path.write_bytes(content)

    source = VideoFileSource(str(save_path))
    fps = source.fps
    _UPLOADS[source_id] = {"path": str(save_path), "fps": fps, "suffix": suffix}
    logger.info("Saved upload %s (fps=%.1f)", source_id, fps)

    def _event(data: dict) -> str:
        return f"data: {json.dumps(data)}\n\n"

    async def generate():
        try:
            cap = cv2.VideoCapture(str(save_path))
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            cap.release()

            count = 0
            for payload in roi_aware_sampler(source, source_id=source_id):
                process_frame(
                    client=client,
                    frame_bgr=payload.frame,
                    camera_id=source_id,
                    timestamp=str(round(payload.t / fps, 4)),
                    domain="uploaded",
                    source_id=source_id,
                    fps=fps,
                )
                count += 1
                pct = min(int(payload.t / total * 100), 99)
                yield _event({"progress": pct, "indexed": count})

            logger.info("Indexed %d frames from %s", count, source_id)
            yield _event({"progress": 100, "indexed": count, "done": True})
        except Exception as exc:
            logger.exception("Ingest error: %s", exc)
            yield _event({"error": str(exc), "done": True})

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── /video/{source_id} ────────────────────────────────────────────────────────

@app.get("/video/{source_id}")
def get_video(source_id: str):
    """Serve a stored upload; supports byte-range requests for HTML5 seeking."""
    upload = _UPLOADS.get(source_id)
    if not upload:
        raise HTTPException(404, "Video not found")
    path = Path(upload["path"])
    if not path.exists():
        raise HTTPException(404, "Video file missing on disk")
    suffix = upload.get("suffix", ".mp4").lower()
    media_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
    }
    media_type = media_types.get(suffix, "video/mp4")
    return FileResponse(str(path), media_type=media_type)


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
        text_out = model.text_model(**inputs)
        pooled = text_out.pooler_output  # (1, hidden_size)
        if hasattr(model, "text_projection"):
            pooled = model.text_projection(pooled)

    vec: np.ndarray = pooled[0].cpu().float().numpy()
    norm = np.linalg.norm(vec)
    if norm > 0.0:
        vec = vec / norm

    vec_list = vec.tolist()

    try:
        result = client.query_points(
            collection_name=_COLLECTION,
            query=vec_list,
            limit=req.limit,
        )
    except Exception as exc:
        logger.exception("Qdrant search failed: %s", exc)
        raise HTTPException(500, str(exc))

    from qdrant_client.models import FieldCondition, Filter, MatchValue

    # Log raw scores to help tune the threshold
    if result.points:
        scores = [round(h.score, 4) for h in result.points[:5]]
        logger.info("Search '%s' — top raw scores: %s", req.query, scores)
    else:
        logger.warning("Search '%s' — Qdrant returned 0 points (collection may be empty)", req.query)

    # Frames below this cosine-similarity score are never shown, regardless of diversity logic.
    # Raise to tighten relevance; lower if genuine matches are being filtered out.
    _MIN_SCORE = 0.05

    # Drop irrelevant frames from the main results before diversity passes run
    result.points = [h for h in result.points if h.score >= _MIN_SCORE]

    # Cross-source diversity: add missing sources only when they have a genuinely matching frame
    represented = {h.payload.get("source_id") for h in result.points}
    for source_id in list(_UPLOADS.keys()):
        if source_id not in represented:
            try:
                top_few = client.query_points(
                    collection_name=_COLLECTION,
                    query=vec_list,
                    query_filter=Filter(
                        must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]
                    ),
                    limit=3,
                )
                qualifying = [p for p in top_few.points if p.score >= _MIN_SCORE]
                if qualifying:
                    result.points.extend(qualifying)
                    represented.add(source_id)
            except Exception as exc:
                logger.warning("Cross-source fallback for %s failed: %s", source_id, exc)

    # Within-source temporal diversity: surface every distinct event, not just the dominant one.
    # Gap matches the frontend CLUSTER_WINDOW_SEC (1.5 s) so every cluster the UI would
    # show as a separate card is guaranteed to have at least one frame in the response.
    _MIN_EVENT_GAP_SEC = 2.0
    _MAX_EXTRA_PER_SOURCE = 20
    source_covered: dict[str, list[float]] = {}
    for h in result.points:
        sid = h.payload.get("source_id", "")
        t = float(h.payload.get("timestamp") or 0)
        source_covered.setdefault(sid, []).append(t)

    for source_id, covered in source_covered.items():
        try:
            more = client.query_points(
                collection_name=_COLLECTION,
                query=vec_list,
                query_filter=Filter(
                    must=[FieldCondition(key="source_id", match=MatchValue(value=source_id))]
                ),
                limit=50,
            )
            extra = 0
            for h in more.points:
                if extra >= _MAX_EXTRA_PER_SOURCE:
                    break
                if h.score < _MIN_SCORE:
                    continue
                t = float(h.payload.get("timestamp") or 0)
                if all(abs(t - ct) > _MIN_EVENT_GAP_SEC for ct in covered):
                    result.points.append(h)
                    covered.append(t)
                    extra += 1
        except Exception as exc:
            logger.warning("Temporal diversity query for %s failed: %s", source_id, exc)

    def _fmt(h) -> dict:
        return {
            "frame_id": h.id,
            "score": round(float(h.score), 4),
            "timestamp": h.payload.get("timestamp", ""),
            "camera_id": h.payload.get("camera_id", ""),
            "source_id": h.payload.get("source_id", ""),
            "fps": h.payload.get("fps", 30.0),
            "thumb": h.payload.get("thumb", ""),
        }

    return {"results": [_fmt(h) for h in result.points]}
