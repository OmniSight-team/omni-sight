"""ai_workers' internal API (OMNI-704). Not published to the host and not routed by nginx:
only services inside the Docker network reach it, and query is the one that does, to turn a
search query into a vector. query never loads a model itself.
"""

import logging
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from PIL import Image
from pydantic import BaseModel, Field

from app.encoder import FrameTextEncoder, ensure_checkpoint
from app.logging_conf import configure_logging
from app.settings import settings

configure_logging()
logger = logging.getLogger("app.encoder")

state: dict[str, FrameTextEncoder] = {}


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
    yield
    state.clear()


app = FastAPI(title=settings.app_name, lifespan=lifespan)


class TextQuery(BaseModel):
    q: str = Field(min_length=1, max_length=1000)


class Embedding(BaseModel):
    vector: list[float]
    model: str
    model_revision: str


def _encoder() -> FrameTextEncoder:
    encoder = state.get("encoder")
    if encoder is None:
        raise HTTPException(status_code=503, detail="the encoder is not loaded")
    return encoder


@app.get("/health")
def health() -> dict:
    return {"model": settings.frame_model_id, "model_revision": settings.frame_model_revision, "loaded": "encoder" in state}


@app.post("/encode/text")
def encode_text(body: TextQuery) -> Embedding:
    [vector] = _encoder().encode_texts([body.q])
    return Embedding(vector=vector.tolist(), model=settings.frame_model_id, model_revision=settings.frame_model_revision)
