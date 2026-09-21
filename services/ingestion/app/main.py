import logging
import time
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.file_probe import FileProbeError, probe_file
from app.logging_conf import configure_logging
from app.pipeline import ExtractError, extract_file
from app.schemas import (
    ExtractedSegment,
    FileExtractRequest,
    FileExtractResponse,
    FileProbeRequest,
    FileProbeResponse,
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


@app.post("/extract/file", response_model=FileExtractResponse)
def extract_file_route(payload: FileExtractRequest) -> FileExtractResponse:
    # A plain (not async def) route: decoding a video is blocking work, so
    # FastAPI runs it in its threadpool instead of stalling the event loop.
    folder = str(payload.video_id)
    try:
        records = extract_file(
            payload.path,
            source_type=payload.source_type.value,
            video_id=payload.video_id,
            camera_id=payload.camera_id,
            interval_s=settings.extract_interval_s,
            frames_dir=Path(settings.frames_path) / folder,
            thumbs_dir=Path(settings.thumbs_path) / folder,
            thumb_width=settings.thumb_width_px,
            frame_quality=settings.frame_jpeg_quality,
            thumb_quality=settings.thumb_jpeg_quality,
        )
    except ExtractError as exc:
        logger.warning(
            "extraction failed",
            extra={"extra_fields": {"video_id": payload.video_id, "error": exc.reason}},
        )
        return FileExtractResponse(ok=False, error=exc.reason)
    return FileExtractResponse(
        ok=True, segments=[ExtractedSegment(**asdict(record)) for record in records]
    )
