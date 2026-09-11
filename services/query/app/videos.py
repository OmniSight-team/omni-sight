import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from omnisight_common import VideoSource, VideoStatus
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.ingestion_client import IngestionUnavailableError
from app.ingestion_client import probe_file as ingestion_probe_file
from app.models import User, Video
from app.schemas import VideoDetailResponse, VideoUploadResponse
from app.settings import settings

logger = logging.getLogger("app.videos")

router = APIRouter(prefix="/videos", tags=["videos"])

# Read in fixed-size chunks so an upload is never held in memory all at once,
# no matter how large the file is.
CHUNK_SIZE = 1024 * 1024

NOT_A_VIDEO_MESSAGE = "file is not a recognized video format"


def _max_upload_bytes() -> int:
    return settings.max_upload_size_mb * 1024 * 1024


def _size_limit_message() -> str:
    return f"file exceeds the {settings.max_upload_size_mb} MB upload limit"


def _detect_video_extension(header: bytes) -> str | None:
    """Identify a video container from its own bytes, never from the
    client-supplied filename — a `.txt` renamed to `.mp4` must still fail
    this check for the upload to be rejected."""
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return ".mp4"
    if len(header) >= 4 and header[0:4] == b"\x1a\x45\xdf\xa3":
        return ".webm"
    if len(header) >= 12 and header[0:4] == b"RIFF" and header[8:12] == b"AVI ":
        return ".avi"
    return None


@router.post("/upload", response_model=VideoUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_video(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> VideoUploadResponse:
    # A plain (not async def) route: FastAPI runs it in its threadpool, so
    # the blocking chunk-by-chunk disk writes below never stall the event
    # loop the way they would inside an async handler.
    max_bytes = _max_upload_bytes()

    content_length = request.headers.get("content-length")
    if content_length is not None and int(content_length) > max_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=_size_limit_message())

    source = file.file
    header = source.read(64)
    extension = _detect_video_extension(header)
    if extension is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NOT_A_VIDEO_MESSAGE)

    storage_dir = Path(settings.video_storage_path)
    stored_name = f"{uuid.uuid4().hex}{extension}"
    final_path = storage_dir / stored_name
    # Written under a .part name and only renamed into place once the whole
    # file is down — a crash mid-upload leaves an orphan .part file, never a
    # database row pointing at a partial one.
    staging_path = storage_dir / f"{stored_name}.part"

    total_bytes = len(header)
    try:
        with open(staging_path, "wb") as out:
            out.write(header)
            while chunk := source.read(CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=_size_limit_message()
                    )
                out.write(chunk)
    except Exception:
        staging_path.unlink(missing_ok=True)
        raise
    finally:
        file.file.close()

    staging_path.replace(final_path)

    video = Video(
        filename=file.filename or stored_name,
        path=str(final_path),
        source=VideoSource.UPLOAD,
        size_bytes=total_bytes,
        status=VideoStatus.UPLOADED,
    )
    db.add(video)
    db.commit()
    db.refresh(video)

    probe_error = _probe_and_finalize(video, db)

    return VideoUploadResponse(
        id=video.id,
        filename=video.filename,
        duration_s=video.duration_s,
        size_mb=round(video.size_bytes / (1024 * 1024), 2),
        fps=video.fps,
        status=video.status,
        error=probe_error,
    )


def _probe_and_finalize(video: Video, db: Session) -> str | None:
    """Probe the file that's already safely on disk and update the row from
    the result. A file ingestion can't decode is a real, permanent failure
    (status -> failed); ingestion itself being unreachable is not — the
    video stays `uploaded` so a later retry has something to retry."""
    try:
        result = ingestion_probe_file(video.path)
    except IngestionUnavailableError as exc:
        logger.warning(
            "video probe skipped, ingestion unavailable",
            extra={"extra_fields": {"video_id": video.id, "error": str(exc)}},
        )
        return "ingestion service unavailable"

    if result["ok"]:
        video.duration_s = result["duration_s"]
        video.fps = result["fps"]
        video.width = result["width"]
        video.height = result["height"]
        video.status = VideoStatus.READY
        db.commit()
        return None

    error = result.get("error") or "probe failed"
    logger.warning(
        "video probe failed",
        extra={"extra_fields": {"video_id": video.id, "error": error}},
    )
    video.status = VideoStatus.FAILED
    db.commit()
    return error


def _to_detail(video: Video) -> VideoDetailResponse:
    return VideoDetailResponse(
        id=video.id,
        filename=video.filename,
        camera_id=video.camera_id,
        source=video.source,
        duration_s=video.duration_s,
        fps=video.fps,
        width=video.width,
        height=video.height,
        size_bytes=video.size_bytes,
        status=video.status,
        retention_until=video.retention_until,
        created_at=video.created_at,
        segments_count=0,
    )


VIDEO_NOT_FOUND_MESSAGE = "video not found"


@router.get("", response_model=list[VideoDetailResponse])
def list_videos(
    source: VideoSource | None = None,
    camera_id: int | None = None,
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[VideoDetailResponse]:
    # Every filter and the pagination itself are applied to the query before
    # it runs — the WHERE clauses do the filtering, not a Python loop over
    # rows already pulled into memory. By slice 6 this table holds thousands
    # of dataset rows; a client- or app-side filter would not survive that.
    query = db.query(Video)
    if source is not None:
        query = query.filter(Video.source == source)
    if camera_id is not None:
        query = query.filter(Video.camera_id == camera_id)
    if from_ is not None:
        query = query.filter(Video.created_at >= from_)
    if to is not None:
        query = query.filter(Video.created_at <= to)

    videos = query.order_by(Video.created_at.desc()).offset(offset).limit(limit).all()
    return [_to_detail(video) for video in videos]


@router.get("/{video_id}", response_model=VideoDetailResponse)
def get_video(
    video_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> VideoDetailResponse:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=VIDEO_NOT_FOUND_MESSAGE)

    return _to_detail(video)


@router.delete("/{video_id}")
def delete_video(
    video_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, object]:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=VIDEO_NOT_FOUND_MESSAGE)

    file_path = Path(video.path)
    # The database row is the source of truth every other endpoint reads
    # from, so it's deleted (and committed) first. Only once that succeeds
    # is the file removed — the failure mode this ordering avoids is a row
    # that claims a video exists while its file is already gone; an
    # orphaned file with no row is wasted disk, not a data-integrity bug.
    db.delete(video)
    db.commit()

    try:
        file_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning(
            "video file could not be removed after its row was deleted",
            extra={"extra_fields": {"video_id": video_id, "path": str(file_path), "error": str(exc)}},
        )

    return {"id": video_id, "deleted": True}
