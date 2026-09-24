import logging
import time
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from omnisight_common import connection_parameters

from app.file_probe import FileProbeError, probe_file
from app.logging_conf import configure_logging
from app.pipeline import ExtractError, HeartbeatGate, MotionGate, extract_file
from app.playback import PlaybackError, ensure_playback_copy
from app.publisher import PublishError, publish_segments
from app.schemas import (
    ExtractedSegment,
    FileExtractRequest,
    FileExtractResponse,
    FileProbeRequest,
    FileProbeResponse,
    PlaybackRequest,
    PlaybackResponse,
    PublishExtractRequest,
    PublishExtractResponse,
    StreamProbeRequest,
    StreamProbeResponse,
)
from app.settings import settings
from app.streaming import ProbeError, probe_stream

configure_logging()
logger = logging.getLogger("app.request")

app = FastAPI(title=settings.app_name)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "request",
        extra={
            "extra_fields": {
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            }
        },
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_exception",
        extra={"extra_fields": {"path": request.url.path, "error": str(exc)}},
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/probe/stream", response_model=StreamProbeResponse)
def probe_stream_route(payload: StreamProbeRequest) -> StreamProbeResponse:
    try:
        result = probe_stream(payload.rtsp_url)
    except ProbeError as exc:
        return StreamProbeResponse(reachable=False, error=exc.reason)
    return StreamProbeResponse(reachable=True, resolution=result["resolution"], fps=result["fps"])


@app.post("/probe/file", response_model=FileProbeResponse)
def probe_file_route(payload: FileProbeRequest) -> FileProbeResponse:
    try:
        result = probe_file(payload.path)
    except FileProbeError as exc:
        return FileProbeResponse(ok=False, error=exc.reason)
    return FileProbeResponse(ok=True, **result)


@app.post("/playback/file", response_model=PlaybackResponse)
def playback_file_route(payload: PlaybackRequest) -> PlaybackResponse:
    # A plain (not async def) route: the transcode below is blocking work,
    # same reasoning as every other file-handling route in this service.
    try:
        playback_path = ensure_playback_copy(payload.path)
    except PlaybackError as exc:
        logger.warning(
            "playback copy failed",
            extra={"extra_fields": {"path": payload.path, "error": exc.reason}},
        )
        return PlaybackResponse(ok=False, error=exc.reason)
    return PlaybackResponse(ok=True, playback_path=playback_path)


def _gate_for(payload: FileExtractRequest) -> tuple[HeartbeatGate, dict[str, float | int]]:
    """A fresh gate for one extraction, and the parameters it was built with.

    Any override left None falls back to this service's own settings — a
    normal extraction (OMNI-303) sends none of these and gets the configured
    defaults; a re-gate (OMNI-306) sends whichever it's tuning. A fresh gate
    each time: its buffer of earlier frames, and the heartbeat wrapper's "next
    one due" clock, must never carry over between videos.
    """
    params: dict[str, float | int] = {
        "stride_s": payload.stride_s if payload.stride_s is not None else settings.motion_stride_s,
        "grid_size": payload.grid_size if payload.grid_size is not None else settings.motion_grid_size,
        "cell_threshold": (
            payload.cell_threshold
            if payload.cell_threshold is not None
            else settings.motion_cell_threshold
        ),
        "min_active_cells": (
            payload.min_active_cells
            if payload.min_active_cells is not None
            else settings.motion_min_active_cells
        ),
    }
    gate = HeartbeatGate(
        MotionGate(
            grid_size=params["grid_size"],
            cell_threshold=params["cell_threshold"],
            min_active_cells=params["min_active_cells"],
            stride_s=params["stride_s"],
            blur_kernel=settings.motion_blur_kernel,
        ),
        heartbeat_interval_s=settings.heartbeat_interval_s,
        stride_s=params["stride_s"],
    )
    return gate, params


def _decode_and_gate(payload: FileExtractRequest, gate: HeartbeatGate) -> list:
    folder = str(payload.video_id)
    return extract_file(
        payload.path,
        source_type=payload.source_type.value,
        video_id=payload.video_id,
        camera_id=payload.camera_id,
        frames_dir=Path(settings.frames_path) / folder,
        thumbs_dir=Path(settings.thumbs_path) / folder,
        thumb_width=settings.thumb_width_px,
        frame_quality=settings.frame_jpeg_quality,
        thumb_quality=settings.thumb_jpeg_quality,
        gate=gate,
    )


@app.post("/extract/file", response_model=FileExtractResponse)
def extract_file_route(payload: FileExtractRequest) -> FileExtractResponse:
    """Decode, gate, and return every record in the response. Used by
    re-gating (OMNI-306), which needs the new flags back at once to update the
    existing rows in place; a first extraction goes through the queue instead
    (`/extract/publish`)."""
    # A plain (not async def) route: decoding a video is blocking work, so
    # FastAPI runs it in its threadpool instead of stalling the event loop.
    gate, params = _gate_for(payload)
    try:
        records = _decode_and_gate(payload, gate)
    except ExtractError as exc:
        logger.warning(
            "extraction failed",
            extra={"extra_fields": {"video_id": payload.video_id, "error": exc.reason}},
        )
        return FileExtractResponse(ok=False, error=exc.reason)
    return FileExtractResponse(
        ok=True,
        segments=[ExtractedSegment(**asdict(record)) for record in records],
        **params,
    )


@app.post("/extract/publish", response_model=PublishExtractResponse)
def extract_publish_route(payload: PublishExtractRequest) -> PublishExtractResponse:
    """Decode and gate a file, then put every record on the durable queue
    (OMNI-311) instead of returning it. The response says how many went out
    and which gate parameters were used; the rows are written by the consumer,
    and the caller waits for them to appear.

    Everything is decoded and gated *before* anything is published, so a
    decode failure publishes nothing at all — no half-published extraction to
    clean up. Only a broker failure part-way through can leave some messages
    behind, and those carry the extraction's id so the consumer can recognise
    and drop them."""
    gate, params = _gate_for(payload)
    try:
        records = _decode_and_gate(payload, gate)
        published = publish_segments(
            records,
            payload.extraction_id,
            connection_params=connection_parameters(settings),
            queue=settings.segment_queue,
        )
    except ExtractError as exc:
        logger.warning(
            "extraction failed",
            extra={"extra_fields": {"video_id": payload.video_id, "error": exc.reason}},
        )
        return PublishExtractResponse(ok=False, error=exc.reason)
    except PublishError as exc:
        logger.error(
            "publishing segments failed",
            extra={"extra_fields": {"video_id": payload.video_id, "error": str(exc)}},
        )
        return PublishExtractResponse(ok=False, error=str(exc))
    logger.info(
        "segments published",
        extra={
            "extra_fields": {
                "video_id": payload.video_id,
                "extraction_id": payload.extraction_id,
                "published": published,
            }
        },
    )
    return PublishExtractResponse(ok=True, published=published, **params)
