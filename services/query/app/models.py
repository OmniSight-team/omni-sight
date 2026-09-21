from datetime import datetime

from omnisight_common import (
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
    frame_path: Mapped[str] = mapped_column(String, nullable=False)
    thumb_path: Mapped[str] = mapped_column(String, nullable=False)
    # NULL means "not scored yet"; the gate stores a real score on every frame,
    # admitted or not, so a decision can always be inspected.
    motion_score: Mapped[float | None] = mapped_column(Float)
    admitted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    source_type: Mapped[SegmentSourceType] = mapped_column(
        _enum_column(SegmentSourceType, "segment_source_type"), nullable=False
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
    captured: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    dropped: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    last_frame_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
