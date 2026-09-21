from omnisight_common import CommonSettings
from pydantic import Field


class Settings(CommonSettings):
    app_name: str = "omnisight-ingestion"

    # Same path query writes uploads to (OMNI-205); OMNI-206 probes by path
    # from here, never by re-sending the bytes.
    video_storage_path: str = "/data/videos"

    # One frame every this many seconds. 1.0 = 1 fps: a ten-minute recording is
    # 600 frames plus 600 thumbnails. Lower it for short clips (a 5-second CCD
    # clip yields only 5 segments at 1.0), raise it to save disk on long ones.
    extract_interval_s: float = Field(1.0, gt=0)
    thumb_width_px: int = Field(320, ge=16)
    frame_jpeg_quality: int = Field(85, ge=1, le=100)
    thumb_jpeg_quality: int = Field(70, ge=1, le=100)


settings = Settings()
