"""ai_workers' internal API (OMNI-704). Not published to the host and not routed by nginx:
only services inside the Docker network reach it, and query is the one that does, to turn a
search query into a vector. query never loads a model itself.

OMNI-705: the same process consumes the embed queue on a thread of its own (embed_worker.py),
so the one loaded model encodes both the admitted frames and the search queries.

OMNI-706: it also holds InternVideo2's text side, for Algorithm 3's second query vector. Only
the text side (D-32): clip vectors are made on Colab.
"""

import logging
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from omnisight_common import connection_parameters
from omnisight_common.frame_vectors import qdrant_client
from PIL import Image
from pydantic import BaseModel, Field

from app.clip_encoder import ALLOW_PATTERNS as CLIP_ALLOW_PATTERNS
from app.clip_encoder import ClipTextEncoder
from app.embed_worker import EmbedWorker
from app.encoder import FrameTextEncoder, ensure_checkpoint
from app.logging_conf import configure_logging
from app.settings import settings

configure_logging()
logger = logging.getLogger("app.encoder")

state: dict[str, FrameTextEncoder | ClipTextEncoder] = {}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    started = time.perf_counter()
    folder = ensure_checkpoint(settings.frame_model_id, settings.frame_model_revision, settings.frame_model_dir)
    encoder = FrameTextEncoder(folder)
    loaded = time.perf_counter()
    # The weights are memory-mapped and read on first use: without this the first search
    # waited about 30 s (OMNI-704). /health reports loaded only after it.
    with tempfile.TemporaryDirectory() as scratch:
        blank = Path(scratch) / "warm-up.jpg"
        Image.new("RGB", (384, 384)).save(blank)
        encoder.encode_images([blank])
    encoder.encode_texts(["warm-up"])
    state["encoder"] = encoder
    logger.info(
        "frame encoder loaded",
        extra={"extra_fields": {
            "model": settings.frame_model_id,
            "revision": settings.frame_model_revision,
            "load_s": round(loaded - started, 1),
            "warm_up_s": round(time.perf_counter() - loaded, 1),
        }},
    )
    started = time.perf_counter()
    folder = ensure_checkpoint(
        settings.clip_model_id, settings.clip_model_revision, settings.clip_model_dir, CLIP_ALLOW_PATTERNS
    )
    clip = ClipTextEncoder(folder, video=False)
    clip.encode_texts(["warm-up"])
    state["clip"] = clip
    logger.info(
        "clip text encoder loaded",
        extra={"extra_fields": {
            "model": settings.clip_model_id,
            "revision": settings.clip_model_revision,
            "load_s": round(time.perf_counter() - started, 1),
        }},
    )
    worker = None
    if settings.embed_consumer_enabled:
        worker = EmbedWorker(
            encoder,
            lambda: qdrant_client(settings),
            connection_params=connection_parameters(settings),
            queue=settings.embed_queue,
            collection=settings.frame_collection,
            model=settings.frame_model_id,
            model_revision=settings.frame_model_revision,
            batch_size=settings.embed_batch_size,
            batch_wait_s=settings.embed_batch_wait_s,
        )
        worker.start()
    yield
    if worker is not None:
        worker.stop(timeout_s=5)
    state.clear()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


class TextQuery(BaseModel):
    q: str = Field(min_length=1, max_length=1000)


class Embedding(BaseModel):
    vector: list[float]
    model: str
    model_revision: str


def _encoder(name: str = "encoder"):
    encoder = state.get(name)
    if encoder is None:
        raise HTTPException(status_code=503, detail="the encoder is not loaded")
    return encoder


@app.get("/health")
def health() -> dict:
    return {
        "model": settings.frame_model_id,
        "model_revision": settings.frame_model_revision,
        "clip_model": settings.clip_model_id,
        "clip_model_revision": settings.clip_model_revision,
        "loaded": "encoder" in state and "clip" in state,
    }


@app.post("/encode/text")
def encode_text(body: TextQuery) -> Embedding:
    [vector] = _encoder().encode_texts([body.q])
    return Embedding(vector=vector.tolist(), model=settings.frame_model_id, model_revision=settings.frame_model_revision)


@app.post("/encode/clip-text")
def encode_clip_text(body: TextQuery) -> Embedding:
    """The query in InternVideo2's space, to search clip vectors (Algorithm 3 line 2)."""
    [vector] = _encoder("clip").encode_texts([body.q])
    return Embedding(vector=vector.tolist(), model=settings.clip_model_id, model_revision=settings.clip_model_revision)
