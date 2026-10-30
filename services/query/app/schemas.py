from datetime import datetime
from typing import Literal

from omnisight_common import (
    AdmissionReason,
    CameraStatus,
    Domain,
    Role,
    VideoSource,
    VideoStatus,
)
from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role


class UserResponse(BaseModel):
    id: int
    email: str
    role: Role


class CameraCreate(BaseModel):
    name: str
    rtsp_url: str
    location: str
    group: str
    domain: Domain


class CameraUpdate(BaseModel):
    name: str | None = None
    rtsp_url: str | None = None
    location: str | None = None
    group: str | None = None
    domain: Domain | None = None
    status: CameraStatus | None = None


class CameraCreateResponse(BaseModel):
    id: int
    status: CameraStatus


class CameraOut(BaseModel):
    id: int
    name: str
    location: str
    group: str
    domain: Domain
    status: CameraStatus
    last_seen_at: datetime | None


class CameraTestResponse(BaseModel):
    reachable: bool
    resolution: str | None = None
    fps: float | None = None
    error: str | None = None


class CameraStartResponse(BaseModel):
    worker_id: str
    status: str


class CameraStopResponse(BaseModel):
    status: str


class CameraStatsOut(BaseModel):
    """How a live camera is keeping up (OMNI-314), and what the gate did with
    its frames (OMNI-501). The counters are totals across every capture session."""

    # Frames decoded from the stream and offered to the pipeline.
    captured: int
    # Of those, the ones thrown away because the pipeline could not keep up.
    dropped: int
    # The rest, which the gate was shown: `captured = gated + dropped`.
    gated: int = 0
    # What the gate decided: `gated = admitted + discarded`. Only admitted frames
    # are stored; `admitted` is the two reasons added together.
    admitted: int = 0
    admitted_motion: int = 0
    admitted_heartbeat: int = 0
    discarded: int = 0
    # Frames actually gated per second, recently. Zero when not capturing.
    fps_effective: float
    # Seconds the current capture session has been running. Zero when not capturing.
    uptime_s: float


class CameraLiveOut(BaseModel):
    """One camera on the wall, and what it is doing right now (OMNI-504)."""

    camera_id: int
    name: str
    location: str
    group_name: str
    # live | frozen | offline | stopped, from evidence (app/live_state.py).
    state: Literal["live", "frozen", "offline", "stopped"]
    # When the newest frame arrived (the preview's write time); None when there
    # is no preview, which is always the case for a stopped camera.
    last_frame_at: datetime | None


class CameraBufferFrameOut(BaseModel):
    """One frame of a camera's rewind buffer (OMNI-505): an admitted frame
    already stored, not a copy."""

    segment_id: int
    # When the frame was captured, as Unix time in seconds.
    timestamp_s: float
    # Why the gate kept it: "motion" or "heartbeat".
    reason: AdmissionReason
    # The thumbnail, served by nginx (OMNI-307), and the full frame, served by
    # this API with the token check.
    thumb_url: str
    frame_url: str


class CameraFrameOut(BaseModel):
    """One stored frame of a live camera. Only admitted frames have a
    thumbnail, so only they are listed."""

    segment_id: int
    # The moment the frame was captured, as Unix time in seconds — not seconds
    # from the start of anything, so it means the same across restarts.
    timestamp_s: float
    thumb_url: str


class VideoUploadResponse(BaseModel):
    id: int
    filename: str
    duration_s: float | None
    size_mb: float
    fps: float | None
    status: VideoStatus
    error: str | None = None


class VideoDetailResponse(BaseModel):
    id: int
    filename: str
    camera_id: int | None
    source: VideoSource
    duration_s: float | None
    fps: float | None
    width: int | None
    height: int | None
    size_bytes: int
    status: VideoStatus
    error: str | None = None
    retention_until: datetime | None
    created_at: datetime
    segments_count: int = 0
    # A URL the player (OMNI-308) can point a <video> element at directly —
    # Nginx serves it straight off the shared volume, same as thumbnails
    # (OMNI-307). Never the server-side filesystem path itself. Always set:
    # the playback copy if one was made, otherwise the original, which is
    # exactly what should play when it was already H.264.
    playback_url: str
    # The parameters that produced the video's current admitted/discarded flags
    # (OMNI-306 records them; OMNI-310's slider reads them so it starts at the
    # real value, not a guess). None until a first extraction has run.
    gate_stride_s: float | None = None
    gate_grid_size: int | None = None
    gate_cell_threshold: float | None = None
    gate_min_active_cells: int | None = None


class ExtractResponse(BaseModel):
    video_id: int
    status: VideoStatus


class GateRequest(BaseModel):
    # All four optional (OMNI-306): whatever is left out falls back to
    # ingestion's own configured default, same as a plain extraction.
    stride_s: float | None = None
    grid_size: int | None = None
    cell_threshold: float | None = None
    min_active_cells: int | None = None


class GateResponse(BaseModel):
    admitted: int
    discarded: int


class FrameOut(BaseModel):
    segment_id: int
    frame_index: int
    timestamp_s: float
    motion_score: float | None
    admitted: bool
    # None on a segment with no file (most rows, since OMNI-303's rework —
    # only admitted frames get one).
    thumb_url: str | None
    # Not in the ticket's own sketch, added deliberately: OMNI-305 left this
    # exact note — "admission_reason is on the row and returned once a frames
    # API exists to show it." This is that API.
    admission_reason: AdmissionReason | None = None


class DashboardSummaryOut(BaseModel):
    """The Operations Dashboard's figures (OMNI-610), read from the rollup and small
    tables, never from a count over `segments`."""

    # Cameras whose state is `live` (GET /cameras/live), out of every camera registered.
    cameras_online: int
    cameras_total: int
    videos: int
    segments: int
    # None until alerts exist (slice 9): no alerts is not the same as zero alerts.
    alerts_today: int | None
    # Video bytes plus frame and thumbnail bytes, in GB (10^9 bytes).
    storage_gb: float
    # How long an uploaded or recorded video is kept (VIDEO_RETENTION_DAYS); dataset
    # footage never expires.
    retention_days: int
    # The oldest video that retention will delete in time; None when there is none.
    oldest_recording_at: datetime | None


class DashboardActivityOut(BaseModel):
    """One hour of activity (OMNI-610): the hour's start (UTC) and the segments stored in it."""

    hour: datetime
    segments: int
    # None until alerts exist (slice 9).
    alerts: int | None


class SearchCameraOut(BaseModel):
    id: int
    name: str


class SearchHitOut(BaseModel):
    """OMNI-707: one ranked moment."""

    segment_id: int
    video_id: int | None
    camera: SearchCameraOut | None
    timestamp_s: float
    captured_at: datetime
    # Higher is closer. Cosine similarity in `frame` and `clip`; B.3's reciprocal rank score in `fused`.
    score: float
    # Which index found it: "frame", "clip" or "both" (OMNI-711).
    matched_by: str
    thumb_url: str | None


class SearchTimingsOut(BaseModel):
    """Where `elapsed_ms` went, measured inside query."""

    encode_ms: float
    search_ms: float
    # Algorithm 3's classifier and merge; about nothing in the other modes.
    fusion_ms: float
    join_ms: float
    # True when every vector of the query came from the cache (a repeated query, NFR-2).
    encode_cached: bool


class SearchOut(BaseModel):
    results: list[SearchHitOut]
    mode: str
    elapsed_ms: float
    timings: SearchTimingsOut
    # How many hits were returned.
    total: int
    # Hits whose segment no longer exists, or is no longer admitted (K-24): left out.
    dropped: int
    # Set when there is nothing to search yet (no frame has a vector of the pinned model).
    message: str | None = None


class EmbeddingStatusOut(BaseModel):
    """OMNI-705: one video's (or one camera's live) admitted frames against their vectors."""

    video_id: int | None
    camera_id: int | None
    frames_total: int
    frames_embedded: int
    # 0 until clip vectors exist (OMNI-710).
    clips_embedded: int
    model: str
