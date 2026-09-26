from omnisight_common import AdmissionReason, SegmentSourceType
from pydantic import BaseModel


class StreamProbeRequest(BaseModel):
    rtsp_url: str


class StreamProbeResponse(BaseModel):
    reachable: bool
    resolution: str | None = None
    fps: float | None = None
    error: str | None = None


class FileProbeRequest(BaseModel):
    path: str


class FileProbeResponse(BaseModel):
    ok: bool
    duration_s: float | None = None
    fps: float | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None


class FileExtractRequest(BaseModel):
    video_id: int
    path: str
    source_type: SegmentSourceType
    camera_id: int | None = None
    # Gate parameter overrides (OMNI-306's re-gating). Any left None falls
    # back to this service's own settings — a normal extraction (OMNI-303)
    # omits all four and gets the configured defaults.
    stride_s: float | None = None
    grid_size: int | None = None
    cell_threshold: float | None = None
    min_active_cells: int | None = None


class ExtractedSegment(BaseModel):
    video_id: int | None
    camera_id: int | None
    frame_index: int
    timestamp_s: float
    # None unless the frame was admitted — only admitted frames (by motion or
    # by heartbeat, OMNI-305) get a JPEG written.
    frame_path: str | None
    thumb_path: str | None
    motion_score: float | None
    admitted: bool
    source_type: SegmentSourceType
    # The causal clip window [t-2Δ, t], set only when admitted (OMNI-304).
    clip_start_s: float | None = None
    clip_end_s: float | None = None
    # Why the frame was admitted (OMNI-305). None on a frame that was not
    # admitted at all.
    admission_reason: AdmissionReason | None = None


class FileExtractResponse(BaseModel):
    ok: bool
    segments: list[ExtractedSegment] = []
    error: str | None = None
    # The gate parameters actually used — the resolved values after any
    # override was applied, not just an echo of what the caller sent. This is
    # what lets query record "the parameters used" without duplicating
    # ingestion's own settings defaults.
    stride_s: float | None = None
    grid_size: int | None = None
    cell_threshold: float | None = None
    min_active_cells: int | None = None


class PublishExtractRequest(FileExtractRequest):
    # Query's id for this extraction of the video (OMNI-311). Stamped on every
    # message so the consumer can tell this run's frames from an older run's.
    extraction_id: str


class PublishExtractResponse(BaseModel):
    ok: bool
    # How many segment messages the broker confirmed. Query waits until this
    # many rows exist.
    published: int = 0
    error: str | None = None
    # The gate parameters actually used, same as FileExtractResponse.
    stride_s: float | None = None
    grid_size: int | None = None
    cell_threshold: float | None = None
    min_active_cells: int | None = None


class PlaybackRequest(BaseModel):
    path: str


class PlaybackResponse(BaseModel):
    ok: bool
    # None either way: the source was already H.264 and needed no copy
    # (`ok=True`), or the attempt failed (`ok=False`, `error` set).
    playback_path: str | None = None
    error: str | None = None


class WorkerStartRequest(BaseModel):
    camera_id: int
    rtsp_url: str


class WorkerStartResponse(BaseModel):
    ok: bool
    worker_id: str | None = None
    status: str | None = None
    # Why it did not start: a probe reason ("unreachable", "authentication
    # failed", "timeout") or what the worker itself reported.
    error: str | None = None
    already_running: bool = False


class WorkerStopRequest(BaseModel):
    camera_id: int


class WorkerStopResponse(BaseModel):
    ok: bool
    status: str
    # False when there was nothing to stop — stopping is idempotent.
    was_running: bool


class WorkerInfo(BaseModel):
    camera_id: int
    worker_id: str
    status: str
    error: str | None = None
    started_at: float
    grabbed: int
    published: int
    decode_errors: int
    captured: int = 0
    dropped: int = 0
    dropped_backlog: int = 0
    queue_depth: int = 0
    queue_size: int = 0
    fps_effective: float = 0.0
    uptime_s: float = 0.0
    reconnects: int = 0
    failed_attempts: int = 0
    last_frame_at: float | None = None

