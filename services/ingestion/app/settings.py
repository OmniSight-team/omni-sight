from omnisight_common import CommonSettings
from pydantic import Field, field_validator


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

    # Algorithm 1 (OMNI-304). The frame grid a difference image is divided
    # into, each cell judged independently — a person crossing one corner
    # lights up a few cells without moving a whole-frame average.
    motion_grid_size: int = Field(8, ge=2)
    # Per-cell mean absolute pixel difference (0-255 grayscale) above which a
    # cell counts as showing "meaningful change".
    motion_cell_threshold: float = Field(25.0, ge=0, le=255)
    # How many active cells it takes to admit a frame.
    motion_min_active_cells: int = Field(3, ge=1)
    # How many sampled frames back the "earlier buffered frame" is. Must be at
    # least 2: at 1 it would be the immediately preceding frame, which
    # consecutive frames barely differ from — exactly what this ticket's
    # design note says not to compare against.
    motion_buffer_frames: int = Field(5, ge=2)
    # Gaussian blur kernel applied before differencing, so sensor noise is not
    # read as motion. Must be odd (OpenCV's requirement for a blur kernel).
    motion_blur_kernel: int = Field(21, ge=1)

    @field_validator("motion_blur_kernel")
    @classmethod
    def _blur_kernel_must_be_odd(cls, value: int) -> int:
        if value % 2 == 0:
            raise ValueError("motion_blur_kernel must be odd")
        return value


settings = Settings()
