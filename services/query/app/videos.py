import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from omnisight_common import VideoSource, VideoStatus
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.deps import get_current_user
from app.extraction import (
    GateError,
    remove_segment_files,
    run_extraction,
    run_gate,
    segment_file_paths,
)
from app.ingestion_client import IngestionUnavailableError
from app.ingestion_client import ensure_playback as ingestion_ensure_playback
from app.ingestion_client import probe_file as ingestion_probe_file
from app.models import Segment, User, Video
from app.schemas import (
    ExtractResponse,
    FrameOut,
    GateRequest,
    GateResponse,
    VideoDetailResponse,
    VideoUploadResponse,
)
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

    # created_at and retention_until come from one timestamp and go in with
    # the same INSERT, so no row ever exists without a retention date and the
    # gap between them is exactly the configured number of days.
    created_at = datetime.now(UTC)
    video = Video(
        filename=file.filename or stored_name,
        path=str(final_path),
        source=VideoSource.UPLOAD,
        size_bytes=total_bytes,
        status=VideoStatus.UPLOADED,
        created_at=created_at,
        retention_until=created_at + timedelta(days=settings.video_retention_days),
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
        _ensure_playback_copy(video, db)
        return None

    error = result.get("error") or "probe failed"
    logger.warning(
        "video probe failed",
        extra={"extra_fields": {"video_id": video.id, "error": error}},
    )
    video.status = VideoStatus.FAILED
    db.commit()
    return error


def _ensure_playback_copy(video: Video, db: Session) -> None:
    """A browser-playable H.264 copy, only if the original needs one
    (OMNI-308). Deliberately soft-fail: the original already proved
    decodable by the probe above, so a video is still `ready` and fully
    usable for extraction and gating even if this never succeeds — only the
    in-browser preview is worse off, logged, never raised."""
    try:
        result = ingestion_ensure_playback(video.path)
    except IngestionUnavailableError as exc:
        logger.warning(
            "playback copy skipped, ingestion unavailable",
            extra={"extra_fields": {"video_id": video.id, "error": str(exc)}},
        )
        return

    if not result["ok"]:
        logger.warning(
            "playback copy failed",
            extra={"extra_fields": {"video_id": video.id, "error": result.get("error")}},
        )
        return

    if result.get("playback_path"):
        video.playback_path = result["playback_path"]
        db.commit()


def _video_url(video: Video) -> str:
    """Whichever file actually plays in a browser — the playback copy if one
    was made, otherwise the original (already H.264, or playback generation
    hasn't run or hasn't succeeded yet). Same construction as `_thumb_url`
    (OMNI-307): strip the storage path, prepend the public URL prefix Nginx's
    `location /media/` block serves from."""
    path = video.playback_path or video.path
    return settings.video_url_prefix + path.removeprefix(settings.video_storage_path)


def _to_detail(video: Video, segments_count: int) -> VideoDetailResponse:
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
        error=video.error,
        retention_until=video.retention_until,
        created_at=video.created_at,
        segments_count=segments_count,
        playback_url=_video_url(video),
        gate_stride_s=video.gate_stride_s,
        gate_grid_size=video.gate_grid_size,
        gate_cell_threshold=video.gate_cell_threshold,
        gate_min_active_cells=video.gate_min_active_cells,
    )


VIDEO_NOT_FOUND_MESSAGE = "video not found"
EXTRACTION_RUNNING_MESSAGE = "an extraction is already running for this video"


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

    # One grouped query for the whole page, not one count per row.
    counts = dict(
        db.query(Segment.video_id, func.count(Segment.id))
        .filter(Segment.video_id.in_([video.id for video in videos]))
        .group_by(Segment.video_id)
        .all()
    )
    return [_to_detail(video, counts.get(video.id, 0)) for video in videos]


@router.get("/{video_id}", response_model=VideoDetailResponse)
def get_video(
    video_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> VideoDetailResponse:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=VIDEO_NOT_FOUND_MESSAGE)

    segments_count = db.query(func.count(Segment.id)).filter(Segment.video_id == video_id).scalar()
    return _to_detail(video, segments_count)


def _thumb_url(thumb_path: str | None) -> str | None:
    """A URL Nginx's `location /thumbs/` block (OMNI-307) can serve straight
    off the shared volume, never through this API. None when there is no
    file — most rows, since OMNI-303's rework only writes one for an admitted
    frame."""
    if thumb_path is None:
        return None
    return settings.thumb_url_prefix + thumb_path.removeprefix(settings.thumbs_path)


@router.get("/{video_id}/frames", response_model=list[FrameOut])
def list_frames(
    video_id: int,
    admitted: Literal["true", "false", "all"] = "all",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[FrameOut]:
    """List a video's gated frames — every one, not just admitted ones, so
    the threshold slider (OMNI-310) and a "discarded" view both have
    something to read. Filtering and ordering happen in the query, not after
    the rows are pulled into memory, the same rule OMNI-207 set for
    `GET /videos`."""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=VIDEO_NOT_FOUND_MESSAGE)

    query = db.query(Segment).filter(Segment.video_id == video_id)
    if admitted != "all":
        query = query.filter(Segment.admitted == (admitted == "true"))

    segments = query.order_by(Segment.timestamp_s).offset(offset).limit(limit).all()
    return [
        FrameOut(
            segment_id=segment.id,
            frame_index=segment.frame_index,
            timestamp_s=segment.timestamp_s,
            motion_score=segment.motion_score,
            admitted=segment.admitted,
            thumb_url=_thumb_url(segment.thumb_path),
            admission_reason=segment.admission_reason,
        )
        for segment in segments
    ]


@router.post(
    "/{video_id}/extract", response_model=ExtractResponse, status_code=status.HTTP_202_ACCEPTED
)
def extract_video(
    video_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> ExtractResponse:
    """Start extracting frames from a stored video. Returns at once; the video
    is `extracting` until the background job finishes, then `ready` (with its
    segments) or `failed` (with the reason in `error`). Poll GET /videos/{id}."""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=VIDEO_NOT_FOUND_MESSAGE)

    # The status check and the change to `extracting` are one UPDATE, so two
    # requests at once cannot both start an extraction. The same UPDATE names
    # this run (OMNI-311): from this moment a queued segment from any earlier
    # run no longer matches the video, so the consumer drops it.
    extraction_id = uuid.uuid4().hex
    claimed = (
        db.query(Video)
        .filter(Video.id == video_id, Video.status.in_([VideoStatus.READY, VideoStatus.FAILED]))
        .update(
            {"status": VideoStatus.EXTRACTING, "error": None, "extraction_id": extraction_id},
            synchronize_session=False,
        )
    )
    db.commit()
    if not claimed:
        db.refresh(video)
        detail = (
            EXTRACTION_RUNNING_MESSAGE
            if video.status == VideoStatus.EXTRACTING
            else f"video is {video.status.value}, so it cannot be extracted yet"
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    background_tasks.add_task(run_extraction, video_id, extraction_id)
    return ExtractResponse(video_id=video_id, status=VideoStatus.EXTRACTING)


NOT_READY_FOR_GATING_MESSAGE = "video must be ready (already extracted) before it can be re-gated"


def _revert_to_ready(video_id: int) -> None:
    with SessionLocal() as db:
        db.query(Video).filter_by(id=video_id).update(
            {"status": VideoStatus.READY}, synchronize_session=False
        )
        db.commit()


@router.post("/{video_id}/gate", response_model=GateResponse)
def gate_video(
    video_id: int,
    payload: GateRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> GateResponse:
    """Re-run Algorithm 1 against a video's existing segments with new
    parameters and return the new counts immediately — unlike /extract, this
    is synchronous, matching the ticket's own `-> {admitted, discarded}`
    response shape. No row is created or deleted; existing rows are updated
    in place (OMNI-306's own acceptance criterion)."""
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=VIDEO_NOT_FOUND_MESSAGE)

    # Only claimable from `ready` — a video with no completed extraction has
    # no segments to re-gate yet (unlike /extract, which also accepts
    # `failed` as a starting point, since that ticket is instead building the
    # first set of segments from nothing).
    claimed = (
        db.query(Video)
        .filter(Video.id == video_id, Video.status == VideoStatus.READY)
        .update({"status": VideoStatus.EXTRACTING}, synchronize_session=False)
    )
    db.commit()
    if not claimed:
        db.refresh(video)
        detail = (
            EXTRACTION_RUNNING_MESSAGE
            if video.status == VideoStatus.EXTRACTING
            else NOT_READY_FOR_GATING_MESSAGE
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    try:
        counts = run_gate(
            video_id,
            stride_s=payload.stride_s,
            grid_size=payload.grid_size,
            cell_threshold=payload.cell_threshold,
            min_active_cells=payload.min_active_cells,
        )
    except GateError as exc:
        # The video's existing segments were never touched — put it back
        # exactly where it was, not `failed`, which would claim something is
        # wrong with data that is actually still fine.
        _revert_to_ready(video_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.reason) from exc
    except Exception:
        _revert_to_ready(video_id)
        raise

    return GateResponse(**counts)


@router.delete("/{video_id}")
def delete_video(
    video_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, object]:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=VIDEO_NOT_FOUND_MESSAGE)

    if video.status == VideoStatus.EXTRACTING:
        # The background job would write frames for a video that no longer exists.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=EXTRACTION_RUNNING_MESSAGE)

    # The segment rows go with the video (ON DELETE CASCADE), but the frame and
    # thumbnail files they point at do not — the paths have to be read before
    # the rows disappear.
    segment_paths = segment_file_paths(db, video_id)
    # The original, plus the playback copy (OMNI-308) if one was ever made —
    # two files can point back at one video now, not just one.
    file_paths = [Path(video.path)]
    if video.playback_path:
        file_paths.append(Path(video.playback_path))

    # The database rows are the source of truth every other endpoint reads
    # from, so they're deleted (and committed) first. Only once that succeeds
    # are the files removed — the failure mode this ordering avoids is a row
    # that claims a video exists while its file is already gone; an
    # orphaned file with no row is wasted disk, not a data-integrity bug.
    db.delete(video)
    db.commit()

    for file_path in file_paths:
        try:
            file_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                "video file could not be removed after its row was deleted",
                extra={"extra_fields": {"video_id": video_id, "path": str(file_path), "error": str(exc)}},
            )
    remove_segment_files(video_id, segment_paths)

    return {"id": video_id, "deleted": True}
