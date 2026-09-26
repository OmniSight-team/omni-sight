from datetime import datetime

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
