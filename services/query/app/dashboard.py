"""The Operations Dashboard's figures (OMNI-610, FR-9).

`segments` holds a row per decoded frame of every file (D-5), so nothing here counts it.
Segment counts and frame bytes come from `segment_hourly`, which the triggers on
`segments` keep in the same transaction as the rows (D-28); everything else comes from
tables that stay small (cameras, videos). Alerts do not exist before slice 9, so their
figures are None, never a made-up 0.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from omnisight_common import VideoSource
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cameras import live_cameras
from app.db import get_db
from app.deps import get_current_user
from app.live_state import LiveState
from app.models import SegmentHourly, User, Video
from app.schemas import DashboardActivityOut, DashboardSummaryOut
from app.settings import settings

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

BYTES_PER_GB = 1_000_000_000


@router.get("/summary", response_model=DashboardSummaryOut)
def dashboard_summary(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DashboardSummaryOut:
    """The state of the whole system at a glance. Every role sees the dashboard (nav.py)."""
    cameras = live_cameras(db)
    videos, video_bytes, oldest = db.execute(
        select(
            func.count(Video.id),
            func.coalesce(func.sum(Video.size_bytes), 0),
            # Dataset footage never expires (OMNI-608), so it is not what the horizon is about.
            func.min(Video.created_at).filter(Video.source != VideoSource.DATASET),
        )
    ).one()
    segments, file_bytes = db.execute(
        select(
            func.coalesce(func.sum(SegmentHourly.segments), 0),
            func.coalesce(func.sum(SegmentHourly.file_bytes), 0),
        )
    ).one()
    return DashboardSummaryOut(
        cameras_online=sum(1 for camera in cameras if camera.state == LiveState.LIVE),
        cameras_total=len(cameras),
        videos=videos,
        segments=int(segments),
        alerts_today=None,
        storage_gb=round(int(video_bytes + file_bytes) / BYTES_PER_GB, 3),
        retention_days=settings.video_retention_days,
        oldest_recording_at=oldest,
    )


@router.get("/activity", response_model=list[DashboardActivityOut])
def dashboard_activity(
    hours: int = Query(24, ge=1, le=168),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[DashboardActivityOut]:
    """Segments stored per hour over the last `hours` hours, oldest first, ending with the
    current hour. An hour with no row in the rollup stored nothing, so it reads 0."""
    current = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    first = current - timedelta(hours=hours - 1)
    stored = dict(
        db.execute(
            select(SegmentHourly.hour, func.sum(SegmentHourly.segments))
            .where(SegmentHourly.hour >= first)
            .group_by(SegmentHourly.hour)
        ).all()
    )
    out = []
    for i in range(hours):
        hour = first + timedelta(hours=i)
        out.append(DashboardActivityOut(hour=hour, segments=int(stored.get(hour, 0)), alerts=None))
    return out
