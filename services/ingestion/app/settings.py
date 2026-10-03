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
    # (see docs/decisions.md, D-4). Must be odd (OpenCV's requirement for a blur
    # kernel).
    motion_blur_kernel: int = Field(21, ge=1)

    # Live capture (OMNI-312). There is no sampling setting: every decoded frame
    # of a stream is gated with the motion settings above, the same as a file's
    # (OMNI-501; docs/decisions.md, D-9), and only admitted frames are published.
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
    # OMNI-510a: threads each live stream's decoder may use. FFmpeg's default is one
    # per CPU (8 here), so ten cameras started some 150 decoder threads on 8 CPUs,
    # and ingestion spent about twice the work it did (OMNI-509). One decoder
    # thread keeps up with a 24 fps 1280x720 stream. 0 leaves FFmpeg's default.
    live_decoder_threads: int = Field(1, ge=0)
    # OMNI-510a: run each camera's worker in a process of its own. In one process
    # the cameras' threads took turns on Python's interpreter lock and ten
    # realistic feeds gated well under half their frames (OMNI-509). Off runs
    # every worker in this process, as before.
    live_worker_processes: bool = True
    # OMNI-510a: threads one OpenCV call (the blur, the colour conversion) may use,
    # for the whole process. 0 leaves OpenCV's default, one per CPU. With many
    # cameras each gating on its own thread, the cameras are the parallelism.
    opencv_threads: int = Field(1, ge=0)
    # Also the longest a stalled stream can hold up a stop, and it must outlast
    # the wait for a first keyframe: 5 s was too close to that and failed a
    # healthy start.
    live_read_timeout_ms: int = Field(10000, ge=1)

    # Reconnection (OMNI-313). After a stream drops, the first retry comes after
    # `initial`, and each failure multiplies the wait by `factor` up to `max`, so
    # a dead camera is tried at 1 s, 2 s, 4 s ... 30 s and then every 30 s, not
    # every 100 ms. The jitter (a fraction of the delay, either way) keeps many
    # cameras that lost the same network from all retrying at once. The cap is
    # also the longest a camera that has just come back can go unnoticed.
    live_reconnect_initial_s: float = Field(1.0, gt=0)
    live_reconnect_max_s: float = Field(30.0, gt=0)
    live_reconnect_factor: float = Field(2.0, ge=1.0)
    live_reconnect_jitter: float = Field(0.2, ge=0.0, le=1.0)
    # A connection has to last this long before it earns the backoff a fresh
    # start. Without it a camera that flaps every couple of seconds would be
    # retried at the shortest delay for ever.
    live_backoff_reset_s: float = Field(10.0, ge=0)

    # The bounded queue between capture and processing (OMNI-314). A decoded frame
    # waits here for the processing thread; when it is full the frame is dropped
    # and counted, so a slow gate or broker costs frames, not memory. Sixty
    # frames is 2 s of a 30 fps stream (2.5 s at 24 fps), the margin this queue
    # had when it held sampled frames; at 10 it was a third of a second once
    # every frame was gated, and a moment's hiccup on an idle machine dropped
    # frames (OMNI-510a). At most about 166 MB for a full 1280x720 queue.
    live_queue_size: int = Field(60, ge=1)
    # The most segments the durable queue may hold before live frames are dropped
    # instead of added to it, so a consumer that has fallen behind cannot let the
    # broker's queue grow for ever. 0 turns the limit off. It is the live queue
    # that is measured (OMNI-502): a large upload waiting to be stored is on the
    # file queue and does not count.
    live_max_backlog: int = Field(2000, ge=0)
    # The preview a camera wall polls (OMNI-503): the current decoded frame,
    # admitted or not, written at most this often, scaled so its longest side is
    # at most this many pixels. One file per camera, replaced, never accumulated.
    live_preview_interval_s: float = Field(0.5, gt=0)
    live_preview_max_side_px: int = Field(640, ge=16)
    live_preview_jpeg_quality: int = Field(70, ge=1, le=100)
    # OMNI-507 (K-13): a worker counts as receiving only when, within the last
    # `live_steady_window_s`, at least two frames arrived at least
    # `live_steady_min_span_s` apart. A stalled stream can still hand over a late
    # burst of old frames all at once; that is not a working camera.
    live_steady_window_s: float = Field(3.0, gt=0)
    live_steady_min_span_s: float = Field(1.0, ge=0)
    # How often a worker sends its counters to `camera_stats`.
    live_stats_interval_s: float = Field(5.0, gt=0)
    # Drops are logged when a stretch of them begins and then summarised this
    # often, not once per frame.
    live_drop_log_interval_s: float = Field(5.0, gt=0)
    # The window `fps_effective` is measured over.
    live_fps_window_s: float = Field(10.0, gt=0)

    @field_validator("motion_blur_kernel")
    @classmethod
    def _blur_kernel_must_be_odd(cls, value: int) -> int:
        if value % 2 == 0:
            raise ValueError("motion_blur_kernel must be odd")
        return value


settings = Settings()
