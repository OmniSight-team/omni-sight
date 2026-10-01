import logging
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

import cv2
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from omnisight_common import connection_parameters

from app.file_probe import FileProbeError, probe_file
from app.live_capture import (
    LIVE_STATES,
    AlreadyRunning,
    Backoff,
    LiveWorker,
    WorkerRegistry,
    WorkerState,
)
from app.logging_conf import configure_logging
from app.pipeline import (
    ExtractError,
    FrameSource,
    HeartbeatGate,
    MotionGate,
    extract_file,
    process_frame,
)
from app.playback import PlaybackError, ensure_playback_copy
from app.publisher import PublishError, SegmentPublisher, publish_segments
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
    WorkerInfo,
    WorkerStartRequest,
    WorkerStartResponse,
    WorkerStopRequest,
    WorkerStopResponse,
)
from app.settings import settings
from app.streaming import ProbeError, probe_stream

configure_logging()
logger = logging.getLogger("app.request")

workers = WorkerRegistry()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    # Every stream opened by a worker is closed when the service goes down,
    # not left for the operating system to reap.
    workers.stop_all(settings.live_stop_timeout_s)


app = FastAPI(title=settings.app_name, lifespan=lifespan)


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


def _gate_for(
    payload: FileExtractRequest | None = None, *, start_s: float = 0.0
) -> tuple[HeartbeatGate, dict[str, float | int]]:
    """A fresh gate for one extraction (or one live capture), and the
    parameters it was built with.

    Any override left None falls back to this service's own settings — a
    normal extraction (OMNI-303) sends none of these and gets the configured
    defaults; a re-gate (OMNI-306) sends whichever it's tuning; a live worker
    (OMNI-312) passes no payload at all. A fresh gate each time: its buffer of
    earlier frames, and the heartbeat wrapper's "next one due" clock, must
    never carry over between videos. `start_s` is the source's own time
    origin: 0 for a file, the moment capture began for a live stream.
    """

    def pick(name: str, default: float) -> float:
        value = getattr(payload, name, None)
        return default if value is None else value

    params: dict[str, float | int] = {
        "stride_s": pick("stride_s", settings.motion_stride_s),
        "grid_size": pick("grid_size", settings.motion_grid_size),
        "cell_threshold": pick("cell_threshold", settings.motion_cell_threshold),
        "min_active_cells": pick("min_active_cells", settings.motion_min_active_cells),
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
        start_s=start_s,
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


def _open_stream(rtsp_url: str) -> cv2.VideoCapture:
    # Timeouts so a stream that stalls returns from a read instead of blocking
    # its worker forever — which is also what lets a stop take effect.
    return cv2.VideoCapture(
        rtsp_url,
        cv2.CAP_FFMPEG,
        [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
            settings.live_open_timeout_ms,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC,
            settings.live_read_timeout_ms,
        ],
    )


def _live_worker_for(camera_id: int, rtsp_url: str) -> LiveWorker:
    """A worker whose frames go through the same `process_frame`, the same gate
    settings and the same kind of durable queue as a file's (OMNI-312, OMNI-501);
    its own queue, so it never waits behind a recording (OMNI-502). Nothing about
    its records says "camera" beyond `source_type`, and `video_id` is null. The
    one live-specific part is in the worker: it publishes admitted frames only."""
    started_at = time.time()
    # One folder per capture session: a frame's file is named by its index in
    # the session, and a restarted worker starts counting again, so sharing a
    # folder would overwrite files that stored segments still point at. A
    # reconnection stays in the same session: its frame indexes carry on.
    session = str(int(started_at))
    frames_dir = Path(settings.frames_path) / f"camera-{camera_id}" / session
    thumbs_dir = Path(settings.thumbs_path) / f"camera-{camera_id}" / session
    frames_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    def make_process():
        # A new gate for every connection (OMNI-313): the frames a gate has
        # buffered are from before a gap, and comparing the first frame back
        # with them would read as motion. Its heartbeat clock starts now.
        gate, _params = _gate_for(start_s=time.time())

        def process(frame, timestamp_s: float, frame_index: int):
            return process_frame(
                frame,
                FrameSource(
                    source_type="camera",
                    frame_index=frame_index,
                    timestamp_s=timestamp_s,
                    video_id=None,
                    camera_id=camera_id,
                ),
                gate,
                frames_dir,
                thumbs_dir,
                thumb_width=settings.thumb_width_px,
                frame_quality=settings.frame_jpeg_quality,
                thumb_quality=settings.thumb_jpeg_quality,
            )

        return process

    return LiveWorker(
        camera_id,
        open_capture=lambda: _open_stream(rtsp_url),
        make_publisher=lambda: SegmentPublisher(
            connection_parameters(settings), settings.live_segment_queue, settings.camera_event_queue
        ),
        make_process=make_process,
        clock=lambda: time.time(),
        backoff=Backoff(
            settings.live_reconnect_initial_s,
            settings.live_reconnect_max_s,
            factor=settings.live_reconnect_factor,
            jitter=settings.live_reconnect_jitter,
        ),
        stable_after_s=settings.live_backoff_reset_s,
        queue_size=settings.live_queue_size,
        max_backlog=settings.live_max_backlog or None,
        stats_interval_s=settings.live_stats_interval_s,
        drop_log_interval_s=settings.live_drop_log_interval_s,
        fps_window_s=settings.live_fps_window_s,
    )


@app.post("/workers/start", response_model=WorkerStartResponse)
def start_worker_route(payload: WorkerStartRequest) -> WorkerStartResponse:
    """Start capturing a camera: open its stream, gate every frame it delivers
    and publish the admitted ones until told to stop. Returns once the first frame has
    arrived, or with the reason it did not."""
    existing = workers.get(payload.camera_id)
    if existing is not None and existing.state in LIVE_STATES:
        return WorkerStartResponse(
            ok=False,
            worker_id=existing.worker_id,
            status=existing.state.value,
            error="camera is already being captured",
            already_running=True,
        )

    # The camera connection test's check, first, without waiting for a frame: a
    # dead host or a wrong password is rejected in seconds with a named reason
    # instead of as a generic failure to open. The worker's own first frame is
    # what confirms the stream really delivers.
    try:
        probe_stream(payload.rtsp_url, settings.live_probe_timeout_s, read_first_frame=False)
    except ProbeError as exc:
        return WorkerStartResponse(ok=False, error=exc.reason)

    try:
        worker = workers.start(
            payload.camera_id,
            lambda: _live_worker_for(payload.camera_id, payload.rtsp_url),
            settings.live_start_timeout_s,
        )
    except AlreadyRunning as exc:
        return WorkerStartResponse(
            ok=False,
            worker_id=exc.worker.worker_id,
            status=exc.worker.state.value,
            error="camera is already being captured",
            already_running=True,
        )

    if worker.state not in (WorkerState.RUNNING, WorkerState.RECONNECTING):
        error = worker.error or "the stream did not deliver a frame in time"
        workers.stop(payload.camera_id, settings.live_stop_timeout_s)
        return WorkerStartResponse(ok=False, error=error)

    logger.info(
        "live capture started",
        extra={"extra_fields": {"camera_id": payload.camera_id, "worker_id": worker.worker_id}},
    )
    return WorkerStartResponse(ok=True, worker_id=worker.worker_id, status=worker.state.value)


@app.post("/workers/stop", response_model=WorkerStopResponse)
def stop_worker_route(payload: WorkerStopRequest) -> WorkerStopResponse:
    """Stop a camera's worker and release its stream and broker connection.
    Stopping a camera that is not being captured is not an error."""
    was_running = workers.stop(payload.camera_id, settings.live_stop_timeout_s)
    if was_running:
        logger.info("live capture stopped", extra={"extra_fields": {"camera_id": payload.camera_id}})
    return WorkerStopResponse(ok=True, status="stopped", was_running=was_running)


@app.get("/workers", response_model=list[WorkerInfo])
def list_workers_route() -> list[WorkerInfo]:
    return [WorkerInfo(**snapshot) for snapshot in workers.snapshots()]
