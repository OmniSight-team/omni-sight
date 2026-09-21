from omnisight_common import SegmentSourceType
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
    frame_path: str
    thumb_path: str
    motion_score: float | None
    admitted: bool
    source_type: SegmentSourceType


class FileExtractResponse(BaseModel):
    ok: bool
    segments: list[ExtractedSegment] = []
    error: str | None = None
