import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from omnisight_common import VideoSource, VideoStatus
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import User, Video
from app.schemas import VideoUploadResponse
from app.settings import settings

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

    return VideoUploadResponse(
        id=video.id,
        filename=video.filename,
        duration_s=video.duration_s,
        size_mb=round(video.size_bytes / (1024 * 1024), 2),
        fps=video.fps,
        status=video.status,
    )
