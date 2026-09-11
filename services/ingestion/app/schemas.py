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
