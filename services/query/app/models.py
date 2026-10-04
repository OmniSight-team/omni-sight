from datetime import datetime

from omnisight_common import (
    AdmissionReason,
    CameraStatus,
    Domain,
    Role,
    SegmentSourceType,
    VideoSource,
    VideoStatus,
)
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    false,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _enum_column(enum_cls: type, name: str):
    return Enum(enum_cls, name=name, values_callable=lambda cls: [member.value for member in cls])


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="role", values_callable=lambda enum_cls: [member.value for member in enum_cls]),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    rtsp_url: Mapped[str] = mapped_column(String, nullable=False)
    location: Mapped[str] = mapped_column(String, nullable=False)
    # "group" is a reserved word in SQL; the column and the attribute are both
    # named group_name to sidestep it rather than quoting a reserved word forever.
    group_name: Mapped[str] = mapped_column(String, nullable=False)
    domain: Mapped[Domain] = mapped_column(_enum_column(Domain, "domain"), nullable=False)
    status: Mapped[CameraStatus] = mapped_column(_enum_column(CameraStatus, "camera_status"), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # OMNI-504: whether someone wants this camera captured. Set by a successful
    # start, cleared by stop, disable and delete. Not what the camera is doing
    # (that is `GET /cameras/live`, from evidence); what it should be doing, so a
    # restarted ingestion can be told to resume it (app/capture_resume.py).
    capture_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    camera_id: Mapped[int | None] = mapped_column(
        ForeignKey("cameras.id"), nullable=True, index=True
    )
    source: Mapped[VideoSource] = mapped_column(_enum_column(VideoSource, "video_source"), nullable=False)
    duration_s: Mapped[float | None] = mapped_column(Float)
    fps: Mapped[float | None] = mapped_column(Float)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[VideoStatus] = mapped_column(_enum_column(VideoStatus, "video_status"), nullable=False)
    # Why the video is `failed`. Set by extraction, which runs after the request
    # that started it has already returned, so there is nowhere else to say why.
    error: Mapped[str | None] = mapped_column(String)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A browser-playable H.264 copy of `path`, beside it, never in its place
    # (OMNI-308) — extraction and gating always read `path`, the original.
    # NULL when the original is already H.264 and needs no copy, or when one
    # hasn't been attempted or produced yet.
    playback_path: Mapped[str | None] = mapped_column(String)
    # The Algorithm 1 parameters that produced the video's *current* segment
    # rows — set by extraction (from ingestion's settings) and updated by
    # re-gating (OMNI-306, from whatever the caller supplied). NULL until the
    # first successful extraction. This is what "records the parameters used,
    # so a result can be reproduced" means: one video, one set of numbers that
    # explains its current `admitted` flags, not a log of every run tried.
    gate_stride_s: Mapped[float | None] = mapped_column(Float)
    gate_grid_size: Mapped[int | None] = mapped_column(Integer)
    gate_cell_threshold: Mapped[float | None] = mapped_column(Float)
    gate_min_active_cells: Mapped[int | None] = mapped_column(Integer)
    # Names the extraction currently in progress (OMNI-311), set when it is
    # claimed. Every segment message carries the id of the run that produced
    # it, so the consumer can drop a message left over from a run that failed
    # or was replaced instead of writing an old run's frame into a newer run's
    # video. NULL until a video is first extracted.
    extraction_id: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class Segment(Base):
    """One analysed frame: where it came from, where its files are, and what
    the motion gate decided. Both a file extractor and a live worker write rows
    here, so nothing downstream can tell the two sources apart."""

    __tablename__ = "segments"
    __table_args__ = (
        # Slice 8 asks "what happened in this recording between t1 and t2".
        Index("ix_segments_video_id_timestamp_s", "video_id", "timestamp_s"),
        # Part B writes live frames against a camera and reads them by time.
        Index("ix_segments_camera_id_timestamp_s", "camera_id", "timestamp_s"),
        # One row per frame of a video (OMNI-311). A message is delivered at
        # least once — a consumer that dies between committing a row and
        # acknowledging it gets the same message again — so the database, not
        # the consumer's memory, is what stops that becoming a duplicate row.
        # Partial: a live frame has no video, and OMNI-312 decides what
        # identifies one of those.
        Index(
            "uq_segments_video_id_frame_index",
            "video_id",
            "frame_index",
            unique=True,
            postgresql_where=text("video_id IS NOT NULL"),
        ),
        # The same guarantee for a live frame (OMNI-312), which has no video and
        # so is not covered by the index above. What identifies one is the
        # camera and the moment it was captured: a redelivered message carries
        # the same timestamp, and two different frames never share one because
        # the worker takes one sample per interval.
        Index(
            "uq_segments_camera_id_timestamp_s",
            "camera_id",
            "timestamp_s",
            unique=True,
            postgresql_where=text("video_id IS NULL"),
        ),
        # A segment always came from somewhere: an uploaded file, a camera, or both.
        CheckConstraint("video_id IS NOT NULL OR camera_id IS NOT NULL", name="ck_segments_has_a_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL for a live frame: it has a camera but no uploaded file. CASCADE means
    # deleting a video takes its rows with it; the frame and thumbnail files are
    # removed by delete_video, because a database cascade cannot touch the disk.
    video_id: Mapped[int | None] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), nullable=True
    )
    # NULL for an upload. No ondelete: a camera that still has live frames must
    # be disabled, not deleted (see delete_camera).
    camera_id: Mapped[int | None] = mapped_column(ForeignKey("cameras.id"), nullable=True)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp_s: Mapped[float] = mapped_column(Float, nullable=False)
    # NULL unless the frame was admitted (OMNI-303 rework): a row is written
    # for every gated frame, but a JPEG only for the ones actually worth
    # looking at — writing one per decoded frame of a 30 fps video is not
    # affordable at slice 6 scale.
    frame_path: Mapped[str | None] = mapped_column(String)
    thumb_path: Mapped[str | None] = mapped_column(String)
    # NULL means "not scored yet"; the gate stores a real score on every frame,
    # admitted or not, so a decision can always be inspected.
    motion_score: Mapped[float | None] = mapped_column(Float)
    admitted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    source_type: Mapped[SegmentSourceType] = mapped_column(
        _enum_column(SegmentSourceType, "segment_source_type"), nullable=False
    )
    # The causal clip window Algorithm 1 records on an admitted frame,
    # [clip_start_s, clip_end_s] = [t-2Δ, t] (OMNI-304, pseudocode lines 7-8).
    # NULL on a frame that was not admitted. The window names a span of the
    # *source* video; slice 8 cuts the actual clip bytes from it when needed,
    # rather than this ticket writing one file per admitted frame.
    clip_start_s: Mapped[float | None] = mapped_column(Float)
    clip_end_s: Mapped[float | None] = mapped_column(Float)
    # Why the frame was admitted (OMNI-305): "motion" or "heartbeat". NULL on
    # a frame that was not admitted — there is nothing to name a reason for.
    admission_reason: Mapped[AdmissionReason | None] = mapped_column(
        _enum_column(AdmissionReason, "admission_reason")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CameraStats(Base):
    __tablename__ = "camera_stats"

    # One row per camera. Deleted with the camera: counters mean nothing without it.
    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), primary_key=True
    )
    # Frames decoded from the stream and offered to the pipeline, and of those the
    # ones dropped because it could not keep up (OMNI-314). Cumulative across every
    # capture session the camera has had.
    captured: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    dropped: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    # What the gate did with the frames it was shown (OMNI-501). A live camera
    # stores admitted frames only, so these are the only record of the discarded
    # ones. `captured = gated + dropped` and `gated = admitted_motion +
    # admitted_heartbeat + discarded`, for everything captured since these
    # columns were added.
    gated: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    admitted_motion: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    admitted_heartbeat: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    discarded: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    # When the newest frame was read from the stream.
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Everything below is bookkeeping for one capture session (OMNI-314). A live
    # worker reports its own running totals, not increments, and the consumer
    # adds to the counters above only what it has not already counted for that
    # worker, so a report delivered twice or late cannot count the same frames
    # twice.
    session_id: Mapped[str | None] = mapped_column(String)
    session_captured: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    session_dropped: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    session_gated: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    session_admitted_motion: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    session_admitted_heartbeat: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    session_discarded: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    # When the current session began; NULL once the worker has said it stopped.
    session_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Frames processed per second, as the worker last reported it, and when.
    fps_effective: Mapped[float | None] = mapped_column(Float)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
