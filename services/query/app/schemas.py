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
