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
