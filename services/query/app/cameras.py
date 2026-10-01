import logging
import os
from datetime import UTC, datetime
from email.utils import formatdate
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from omnisight_common import CameraStatus, Role
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_role
from app.ingestion_client import IngestionUnavailableError
from app.ingestion_client import list_workers as ingestion_list_workers
from app.ingestion_client import probe_stream as ingestion_probe_stream
from app.ingestion_client import start_worker as ingestion_start_worker
from app.ingestion_client import stop_worker as ingestion_stop_worker
from app.live_state import derive_state, newest_frame_at
from app.models import Camera, CameraStats, Segment, User, Video
from app.schemas import (
    CameraCreate,
    CameraCreateResponse,
    CameraFrameOut,
    CameraLiveOut,
    CameraOut,
    CameraStartResponse,
    CameraStatsOut,
    CameraStopResponse,
    CameraTestResponse,
    CameraUpdate,
)
from app.settings import settings
from app.videos import _thumb_url

logger = logging.getLogger("app.cameras")

router = APIRouter(prefix="/cameras", tags=["cameras"])

CAMERA_NOT_FOUND_MESSAGE = "camera not found"
CAMERA_DISABLED_MESSAGE = "camera is disabled"
CAMERA_ALREADY_CAPTURING_MESSAGE = "camera is already being captured"
INGESTION_UNAVAILABLE_MESSAGE = "ingestion service unavailable"

# The Cameras screen belongs to operators and admins (nav.py), and starting or
# stopping capture is an operational action, not a configuration one.
_operator_or_admin = require_role(Role.OPERATOR, Role.ADMIN)


def _stop_capture_quietly(camera_id: int) -> None:
    """Make sure a camera that is being disabled or removed has no worker.
    Best effort: if ingestion cannot be reached there is nothing running there
    to stop, or nothing that can be done from here, and the change the caller is
    making must still go through."""
    try:
        ingestion_stop_worker(camera_id)
    except IngestionUnavailableError as exc:
        logger.warning(
            "could not stop capture for a camera being disabled or removed",
            extra={"extra_fields": {"camera_id": camera_id, "error": str(exc)[:200]}},
        )


def _to_out(camera: Camera) -> CameraOut:
    return CameraOut(
        id=camera.id,
        name=camera.name,
        location=camera.location,
        group=camera.group_name,
        domain=camera.domain,
        status=camera.status,
        last_seen_at=camera.last_seen_at,
    )


@router.post("", response_model=CameraCreateResponse, status_code=status.HTTP_201_CREATED)
def create_camera(
    payload: CameraCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(Role.ADMIN)),
) -> CameraCreateResponse:
    # New cameras start at registered, never connected — nothing is
    # connected until the OMNI-204 test says so.
    camera = Camera(
        name=payload.name,
        rtsp_url=payload.rtsp_url,
        location=payload.location,
        group_name=payload.group,
        domain=payload.domain,
        status=CameraStatus.REGISTERED,
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return CameraCreateResponse(id=camera.id, status=camera.status)


@router.get("", response_model=list[CameraOut])
def list_cameras(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[CameraOut]:
    cameras = db.query(Camera).order_by(Camera.id).all()
    return [_to_out(camera) for camera in cameras]


@router.patch("/{camera_id}", response_model=CameraOut)
def update_camera(
    camera_id: int,
    payload: CameraUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(Role.ADMIN)),
) -> CameraOut:
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMERA_NOT_FOUND_MESSAGE)

    updates = payload.model_dump(exclude_unset=True)
    if "group" in updates:
        camera.group_name = updates.pop("group")
    for field, value in updates.items():
        setattr(camera, field, value)

    # A disabled camera must not keep capturing (OMNI-312), nor be resumed
    # (OMNI-504).
    if updates.get("status") == CameraStatus.DISABLED:
        camera.capture_enabled = False
        db.commit()
        _stop_capture_quietly(camera_id)

    db.commit()
    db.refresh(camera)
    return _to_out(camera)


@router.delete("/{camera_id}")
def delete_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(Role.ADMIN)),
) -> dict[str, object]:
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMERA_NOT_FOUND_MESSAGE)

    # Removing or disabling a camera ends its capture first (OMNI-312): a worker
    # left running would keep publishing frames for a camera that is gone. The
    # flag first, so it is not resumed in between (OMNI-504).
    camera.capture_enabled = False
    db.commit()
    _stop_capture_quietly(camera_id)

    # A video or a stored live frame already referencing this camera would be
    # orphaned by a hard delete (and the segments foreign key would reject it),
    # so the camera is disabled in place instead of removed.
    has_recordings = (
        db.query(Video.id).filter_by(camera_id=camera_id).first() is not None
        or db.query(Segment.id).filter_by(camera_id=camera_id).first() is not None
    )
    if has_recordings:
        camera.status = CameraStatus.DISABLED
        db.commit()
        return {"id": camera.id, "deleted": False, "status": camera.status}

    db.delete(camera)
    db.commit()
    return {"id": camera_id, "deleted": True}


@router.get("/live", response_model=list[CameraLiveOut])
def list_live_cameras(
    db: Session = Depends(get_db),
    _user: User = Depends(_operator_or_admin),
) -> list[CameraLiveOut]:
    """Every camera and what it is doing right now, for the camera wall
    (OMNI-504): live, frozen, offline or stopped, worked out from the worker
    ingestion is running and the age of the newest frame, never from a stored
    status (app/live_state.py). `last_frame_at` is the preview's write time.

    Ordered by group, then name, so a wall filtered to one group keeps its
    order."""
    try:
        workers = {w["camera_id"]: w.get("status") for w in ingestion_list_workers()}
        reachable = True
    except IngestionUnavailableError:
        workers, reachable = {}, False

    now = datetime.now(UTC)
    cameras = db.query(Camera).order_by(Camera.group_name, Camera.name, Camera.id).all()
    out = []
    for camera in cameras:
        last_frame_at = newest_frame_at(settings.previews_path, camera.id)
        state = derive_state(
            worker_status=workers.get(camera.id),
            ingestion_reachable=reachable,
            capture_enabled=camera.capture_enabled and camera.status != CameraStatus.DISABLED,
            last_frame_at=last_frame_at,
            now=now,
            stale_after_s=settings.live_stale_after_s,
        )
        out.append(
            CameraLiveOut(
                camera_id=camera.id,
                name=camera.name,
                location=camera.location,
                group_name=camera.group_name,
                state=state,
                last_frame_at=last_frame_at,
            )
        )
    return out


@router.post("/{camera_id}/test", response_model=CameraTestResponse)
def test_camera_connection(
    camera_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CameraTestResponse:
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMERA_NOT_FOUND_MESSAGE)

    try:
        result = ingestion_probe_stream(camera.rtsp_url)
    except IngestionUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="ingestion service unavailable"
        ) from exc

    if result["reachable"]:
        camera.status = CameraStatus.CONNECTED
        camera.last_seen_at = datetime.now(UTC)
    else:
        camera.status = CameraStatus.UNREACHABLE
    db.commit()

    return CameraTestResponse(
        reachable=result["reachable"],
        resolution=result.get("resolution"),
        fps=result.get("fps"),
        error=result.get("error"),
    )


@router.post("/{camera_id}/start", response_model=CameraStartResponse)
def start_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(_operator_or_admin),
) -> CameraStartResponse:
    """Start capturing a camera. Waits for its stream to deliver a first frame,
    so a camera that cannot be reached fails here, with the reason, instead of
    silently never producing anything."""
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMERA_NOT_FOUND_MESSAGE)
    if camera.status == CameraStatus.DISABLED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAMERA_DISABLED_MESSAGE)

    try:
        result = ingestion_start_worker(camera.id, camera.rtsp_url)
    except IngestionUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=INGESTION_UNAVAILABLE_MESSAGE
        ) from exc

    if result.get("already_running"):
        # It is being captured, which is what the caller wanted, so it should be
        # resumed after a restart too.
        camera.capture_enabled = True
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=CAMERA_ALREADY_CAPTURING_MESSAGE
        )
    if not result["ok"]:
        camera.status = CameraStatus.UNREACHABLE
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"could not start capture: {result.get('error') or 'unknown error'}",
        )

    camera.status = CameraStatus.CONNECTED
    camera.last_seen_at = datetime.now(UTC)
    # OMNI-504: from now on this camera is resumed whenever ingestion has no
    # worker for it. Only after a start that worked: a camera that never started
    # is not retried in the background.
    camera.capture_enabled = True
    db.commit()
    return CameraStartResponse(worker_id=result["worker_id"], status=result["status"])


@router.post("/{camera_id}/stop", response_model=CameraStopResponse)
def stop_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(_operator_or_admin),
) -> CameraStopResponse:
    """Stop capturing a camera and release its stream. Stopping a camera that is
    not being captured is not an error: the caller wanted it stopped, and it is."""
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMERA_NOT_FOUND_MESSAGE)

    # Cleared before ingestion is asked, and committed, so the resume check
    # (OMNI-504) never sees the worker gone while the flag still says "capture".
    camera.capture_enabled = False
    db.commit()
    try:
        result = ingestion_stop_worker(camera_id)
    except IngestionUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=INGESTION_UNAVAILABLE_MESSAGE
        ) from exc
    return CameraStopResponse(status=result["status"])


@router.get("/{camera_id}/frames", response_model=list[CameraFrameOut])
def list_camera_frames(
    camera_id: int,
    since: float | None = Query(None, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: User = Depends(_operator_or_admin),
) -> list[CameraFrameOut]:
    """A camera's stored live frames, oldest first.

    With `since` (a `timestamp_s` already seen): the frames captured after it, up
    to `limit`, so a client that keeps the last timestamp it saw can poll for
    what is new. Without it: the newest `limit` frames.

    Live frames only: a recording made from this camera is a video, listed
    through /videos/{id}/frames. And only admitted frames, the ones with a
    thumbnail.
    """
    if db.get(Camera, camera_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMERA_NOT_FOUND_MESSAGE)

    query = db.query(Segment).filter(
        Segment.camera_id == camera_id,
        Segment.video_id.is_(None),
        Segment.admitted.is_(True),
        Segment.thumb_path.is_not(None),
    )
    if since is not None:
        segments = (
            query.filter(Segment.timestamp_s > since)
            .order_by(Segment.timestamp_s.asc())
            .limit(limit)
            .all()
        )
    else:
        segments = query.order_by(Segment.timestamp_s.desc()).limit(limit).all()
        segments.reverse()

    return [
        CameraFrameOut(
            segment_id=segment.id,
            timestamp_s=segment.timestamp_s,
            thumb_url=_thumb_url(segment.thumb_path),
        )
        for segment in segments
    ]


def _is_capturing(stats: CameraStats | None, now: datetime) -> bool:
    """Whether a worker is capturing the camera, by what it last reported: a
    session that has not said it stopped, and a report recent enough to believe."""
    return (
        stats is not None
        and stats.session_started_at is not None
        and stats.reported_at is not None
        and (now - stats.reported_at).total_seconds() <= settings.camera_stats_stale_s
    )


NO_PREVIEW_MESSAGE = "no preview yet: the camera has not delivered a frame"
NOT_CAPTURING_MESSAGE = "camera is not being captured"


@router.get(
    "/{camera_id}/preview",
    response_class=Response,
    responses={200: {"content": {"image/jpeg": {}}}, 304: {"description": "unchanged since the ETag sent"}},
)
def camera_preview(
    camera_id: int,
    if_none_match: str | None = Header(None),
    db: Session = Depends(get_db),
    _user: User = Depends(_operator_or_admin),
) -> Response:
    """The camera's current frame, a small JPEG, cheap to poll (OMNI-503).

    A camera wall asks for this about once a second per tile instead of holding a
    video stream open. The ETag is the file's write time: a poll that sends it
    back in `If-None-Match` and finds the same file gets a 304 and no image.
    `Last-Modified` says when the frame was written, so a client can show its
    age. 404, with the reason, when there is no frame yet or the camera is not
    being captured: an old frame is never served as if it were current.
    """
    if db.get(Camera, camera_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMERA_NOT_FOUND_MESSAGE)
    if not _is_capturing(db.get(CameraStats, camera_id), datetime.now(UTC)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NOT_CAPTURING_MESSAGE)

    path = Path(settings.previews_path) / f"camera-{camera_id}.jpg"
    try:
        # Opened first and measured through the open file, so the ETag and the
        # bytes belong to the same frame even if the worker replaces the file
        # between the two (the rename swaps the name, not this open file).
        with open(path, "rb") as handle:
            written_ns = os.fstat(handle.fileno()).st_mtime_ns
            etag = f'"{written_ns}"'
            headers = {
                "ETag": etag,
                "Cache-Control": "no-cache",
                "Last-Modified": formatdate(written_ns / 1e9, usegmt=True),
            }
            if if_none_match is not None and etag in (tag.strip() for tag in if_none_match.split(",")):
                return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
            body = handle.read()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_PREVIEW_MESSAGE) from exc
    return Response(content=body, media_type="image/jpeg", headers=headers)


@router.get("/{camera_id}/stats", response_model=CameraStatsOut)
def camera_stats(
    camera_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(_operator_or_admin),
) -> CameraStatsOut:
    """How a live camera is keeping up: how many frames were captured, how many
    of those had to be dropped, what the gate did with the rest (admitted for
    motion, admitted as a heartbeat, discarded), and how fast frames are actually
    being gated.

    Read from what the worker last reported, not from the worker: the counters
    are the stored totals, and `uptime_s` and `fps_effective` come from the
    latest report. A camera that has stopped, or whose worker has not reported
    for `camera_stats_stale_s`, reads as zero for both rather than showing a
    frozen last value as if it were current.
    """
    if db.get(Camera, camera_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=CAMERA_NOT_FOUND_MESSAGE)

    stats = db.get(CameraStats, camera_id)
    if stats is None:
        return CameraStatsOut(captured=0, dropped=0, fps_effective=0.0, uptime_s=0.0)

    now = datetime.now(UTC)
    running = _is_capturing(stats, now)
    return CameraStatsOut(
        captured=stats.captured,
        dropped=stats.dropped,
        gated=stats.gated,
        admitted=stats.admitted_motion + stats.admitted_heartbeat,
        admitted_motion=stats.admitted_motion,
        admitted_heartbeat=stats.admitted_heartbeat,
        discarded=stats.discarded,
        fps_effective=(stats.fps_effective or 0.0) if running else 0.0,
        uptime_s=(now - stats.session_started_at).total_seconds() if running else 0.0,
    )

