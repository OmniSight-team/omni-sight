"""Lead-up windows on screen, and the hand check (OMNI-609, D-27).

The hand check looks at one window per clip of the sample (`datasets/hand_check/sample.csv`,
D-26): on UCF-Crime the 30 s window (the 60 s one ends at the same event start), on CCD
the clip's only window. A verdict is "correct" or "wrong with a reason", stored on the
window with who gave it and when. The criterion is D-27's, written before any check.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from omnisight_common import Role
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.datasets import sample_keys
from app.db import get_db
from app.deps import get_current_user, require_role
from app.models import DatasetManifest, EventWindow, User, Video
from app.videos import _video_url

router = APIRouter(prefix="/windows", tags=["windows"])

SAMPLE_DATASETS = ("ucf_crime", "ccd")
CHECKED_LENGTH_S = 30.0  # UCF-Crime; CCD windows have no nominal length
WINDOW_NOT_FOUND_MESSAGE = "window not found"
REASONS = ("ends too late", "ends too early", "wrong event", "cannot tell")


class WindowOut(BaseModel):
    id: int
    dataset: str
    clip_key: str
    event_class: str
    annotation_source: str
    split: str
    window_start_s: float
    window_end_s: float
    length_s: float
    nominal_length_s: float | None
    shortened: bool
    verified: bool | None
    verify_reason: str | None
    verified_by: str | None
    verified_at: datetime | None


class WindowDetail(WindowOut):
    event_start_s: float
    event_end_s: float | None
    video_id: int | None
    video_duration_s: float | None
    playback_url: str | None


class VerdictIn(BaseModel):
    correct: bool
    reason: str | None = Field(None, max_length=500)

    @model_validator(mode="after")
    def wrong_needs_a_reason(self):
        if not self.correct and not (self.reason and self.reason.strip()):
            raise ValueError("a window marked wrong needs a reason")
        return self


def _sampled():
    """The checked window of every sampled clip."""
    clips = or_(*(
        (DatasetManifest.dataset == d) & DatasetManifest.clip_key.in_(sample_keys(d)) for d in SAMPLE_DATASETS
    ))
    length = or_(EventWindow.nominal_length_s == CHECKED_LENGTH_S, EventWindow.nominal_length_s.is_(None))
    return (
        select(EventWindow, DatasetManifest, User.email)
        .join(DatasetManifest, DatasetManifest.id == EventWindow.manifest_id)
        .outerjoin(User, User.id == EventWindow.verified_by)
        .where(clips, EventWindow.kind == "positive", length)
    )


def _out(w: EventWindow, m: DatasetManifest, email: str | None) -> dict:
    return {
        "id": w.id, "dataset": m.dataset, "clip_key": m.clip_key, "event_class": w.event_class,
        "annotation_source": m.annotation_source.value, "split": w.split,
        "window_start_s": w.window_start_s, "window_end_s": w.window_end_s, "length_s": w.length_s,
        "nominal_length_s": w.nominal_length_s, "shortened": w.shortened, "verified": w.verified,
        "verify_reason": w.verify_reason, "verified_by": email, "verified_at": w.verified_at,
    }


@router.get("", response_model=list[WindowOut])
def list_sample_windows(db: Session = Depends(get_db), _user: User = Depends(get_current_user)) -> list[WindowOut]:
    rows = db.execute(_sampled().order_by(DatasetManifest.dataset.desc(), DatasetManifest.clip_key)).all()
    return [WindowOut(**_out(w, m, email)) for w, m, email in rows]


def _detail(db: Session, window_id: int) -> WindowDetail:
    row = db.execute(_sampled().where(EventWindow.id == window_id)).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=WINDOW_NOT_FOUND_MESSAGE)
    w, m, email = row
    video = db.get(Video, m.video_id) if m.video_id is not None else None
    return WindowDetail(
        **_out(w, m, email),
        event_start_s=m.event_start_s,
        event_end_s=m.event_end_s,
        video_id=video.id if video else None,
        video_duration_s=video.duration_s if video else None,
        playback_url=_video_url(video) if video else None,
    )


@router.get("/{window_id}", response_model=WindowDetail)
def get_window(window_id: int, db: Session = Depends(get_db), _user: User = Depends(get_current_user)) -> WindowDetail:
    return _detail(db, window_id)


@router.post("/{window_id}/verdict", response_model=WindowDetail)
def set_verdict(
    window_id: int,
    payload: VerdictIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(Role.ANALYST, Role.ADMIN)),
) -> WindowDetail:
    """Record the hand check's verdict on one window. Checking again replaces it."""
    _detail(db, window_id)  # 404 unless it is a sampled window
    window = db.get(EventWindow, window_id)
    window.verified = payload.correct
    window.verify_reason = None if payload.correct else payload.reason.strip()
    window.verified_by = user.id
    window.verified_at = datetime.now(UTC)
    db.commit()
    return _detail(db, window_id)
