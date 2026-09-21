from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from omnisight_common import CameraStatus, Role
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_role
from app.ingestion_client import IngestionUnavailableError
from app.ingestion_client import probe_stream as ingestion_probe_stream
from app.models import Camera, Segment, User, Video
from app.schemas import (
    CameraCreate,
    CameraCreateResponse,
    CameraOut,
    CameraTestResponse,
    CameraUpdate,
)

router = APIRouter(prefix="/cameras", tags=["cameras"])

CAMERA_NOT_FOUND_MESSAGE = "camera not found"


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
