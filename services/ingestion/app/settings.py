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

    # Algorithm 1 step 5 (OMNI-305): a frame is admitted at least once every
    # this many seconds even when the gate finds no motion, so a parked car or
    # an empty room stays represented instead of being invisible for an
    # entire recording. Renamed from EXTRACT_INTERVAL_S in OMNI-303's rework,
    # when it was still the (removed) extraction sampling rate.
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

    # Live capture (OMNI-312). A stream is read frame by frame, but only one
    # frame per this many seconds is processed and published — never every
    # frame of a 25 fps camera. Not the file extractor's setting: that path has
    # no sampling step since OMNI-303's rework, it gates every frame; a live
    # stream cannot afford to, one camera per core, so it has its own.
    live_sample_interval_s: float = Field(0.2, gt=0)
    # How long a start waits for the stream to open and deliver a first frame.
    # A stream sends nothing useful until its next keyframe, which on the
    # simulator is several seconds after connecting (3-4.5 s measured), so this
    # is generous.
    live_start_timeout_s: float = Field(30.0, gt=0)
    # How long the reachability check before a start may take. It waits for the
    # stream to open, not for a frame, so this is a ceiling for a host that
    # accepts the connection and then says nothing.
    live_probe_timeout_s: float = Field(15.0, gt=0)
    # How long a stop waits for the worker's thread to end. A worker blocked on
    # a stalled stream ends when its read times out, so this must be longer
    # than live_read_timeout_ms.
    live_stop_timeout_s: float = Field(15.0, gt=0)
    live_open_timeout_ms: int = Field(10000, ge=1)
    # Also the longest a stalled stream can hold up a stop, and it must outlast
    # the wait for a first keyframe: 5 s was too close to that and failed a
    # healthy start.
    live_read_timeout_ms: int = Field(10000, ge=1)

    @field_validator("motion_blur_kernel")
    @classmethod
    def _blur_kernel_must_be_odd(cls, value: int) -> int:
        if value % 2 == 0:
            raise ValueError("motion_blur_kernel must be odd")
        return value


settings = Settings()
