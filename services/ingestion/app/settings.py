from omnisight_common import CommonSettings
from pydantic import Field, field_validator


class Settings(CommonSettings):
    app_name: str = "omnisight-ingestion"

    # Same path query writes uploads to (OMNI-205); OMNI-206 probes by path
    # from here, never by re-sending the bytes.
    video_storage_path: str = "/data/videos"

    thumb_width_px: int = Field(320, ge=16)
    frame_jpeg_quality: int = Field(85, ge=1, le=100)
    thumb_jpeg_quality: int = Field(70, ge=1, le=100)

    # OMNI-303 rework: this used to be the extraction sampling rate
    # (EXTRACT_INTERVAL_S). Algorithm 1 has no sampling step — every frame is
    # decoded and gated — so the name was freed up for its real OMNI-305
    # meaning: how often a frame is admitted by heartbeat regardless of the
    # gate's verdict. Renamed now; not read anywhere yet — OMNI-305 wires the
    # actual heartbeat trigger.
    heartbeat_interval_s: float = Field(1.0, gt=0)

    # Algorithm 1 (OMNI-304), Phase A §3.5.1 / Appendix B.1. The frame grid a
    # difference image is divided into, each cell judged independently — a
    # person crossing one corner lights up a few cells without moving a
    # whole-frame average.
    motion_grid_size: int = Field(8, ge=2)
    # Per-cell mean absolute pixel difference (0-255 grayscale) above which a
    # cell counts as showing "meaningful change" (pseudocode τ).
    motion_cell_threshold: float = Field(25.0, ge=0, le=255)
    # How many active cells it takes to admit a frame (pseudocode k).
    motion_min_active_cells: int = Field(3, ge=1)
    # Δ: how far back in **time** the "earlier buffered frame" is, and half the
    # width of the causal clip window recorded on an admitted frame
    # ([t-2Δ, t]). A duration, not a frame count, so the same Δ means the same
    # amount of real time at any source frame rate — a frame-count buffer does
    # not have this property, and was why a 5-second CCD clip sampled at 1 fps
    # never produced a single scored frame under the original implementation.
    motion_stride_s: float = Field(0.5, gt=0)
    # Gaussian blur kernel applied before differencing, so sensor noise is not
    # read as motion. Not in the pseudocode; a documented departure from it
    # (see docs/results.md). Must be odd (OpenCV's requirement for a blur
    # kernel).
    motion_blur_kernel: int = Field(21, ge=1)

    @field_validator("motion_blur_kernel")
    @classmethod
    def _blur_kernel_must_be_odd(cls, value: int) -> int:
        if value % 2 == 0:
            raise ValueError("motion_blur_kernel must be odd")
        return value


settings = Settings()
