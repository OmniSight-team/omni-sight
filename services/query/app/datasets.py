"""Dataset footage in the product (OMNI-608).

What goes in (D-26): only the clips of the hand-check sample, 30 UCF-Crime and 30 CCD
(`datasets/hand_check/sample.csv`), because the window view (OMNI-609) plays them; and the
VIRAT demo sample, one video per loadable scene (9, `datasets/demo/virat_sample.csv`,
OMNI-702), so search has real surveillance footage to work on.
Training and every model measurement run on Colab, from Drive; real users never see
dataset footage.

`POST /datasets/{name}/load` is a loop, not a back door: each clip is read from the
mounted mirror and handed to `store_video`, the function behind `POST /videos/upload`
(same sniff, same storage, same probe), then extracted like any video, one clip at a
time. Only `source = dataset` and no retention date set it apart: research data never
expires.

Resumable: a clip is done when its video is `ready` with a finished extraction
(`gate_stride_s` set). Each call works through the clips not done yet, so after a
restart the same call picks up where the last one stopped — a clip already stored is
extracted, never stored twice. The manifest link (`video_id`) is written in the same
transaction as the video row.
"""

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from fastapi import APIRouter, Depends, HTTPException, status
from omnisight_common import Domain, Role, VideoSource, VideoStatus
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_db
from app.deps import get_current_user, require_role
from app.extraction import claim_extraction, run_extraction
from app.models import DatasetManifest, EventWindow, User, Video
from app.settings import settings
from app.videos import UploadRejected, _probe_and_finalize, store_video

logger = logging.getLogger("app.datasets")

router = APIRouter(prefix="/datasets", tags=["datasets"])

DOMAINS = {"ccd": Domain.TRAFFIC, "ucf_crime": Domain.SURVEILLANCE, "virat": Domain.SURVEILLANCE}

DATASET_NOT_FOUND_MESSAGE = "dataset not found"
LOAD_RUNNING_MESSAGE = "a dataset load is already running"


class DatasetOut(BaseModel):
    name: str
    domain: Domain
    videos_loaded: int
    total: int
    # Clips tried and not loaded: their video is `failed` (reason in `error`) or the
    # file was refused before a video existed (reason in the query log).
    failed: int
    status: str  # not_loaded / loading / partial / loaded
    # The running load, if this dataset has one: clips worked through out of those queued.
    load_done: int | None
    load_queued: int | None
    # OMNI-607's windows over the whole dataset (positive and negative), not only the
    # sample; the hand check (OMNI-609) gives a verdict on the sampled ones.
    windows_derived: int
    windows_checked: int
    windows_verified: int


class LoadRequest(BaseModel):
    limit: int = Field(..., ge=1)


class LoadResponse(BaseModel):
    queued: int


class ClipRefused(Exception):
    """The clip's file was refused before a video row existed (missing, not a
    video, over the size limit), so the reason has nowhere to live but here."""


@dataclass
class _Job:
    dataset: str
    manifest_ids: list[int]
    done: int = 0
    refused: dict[int, str] = field(default_factory=dict)  # manifest id -> reason


_lock = threading.Lock()
_job: _Job | None = None
# Clips refused before a video row existed, kept for the status; lost on restart, and
# tried again by the next load call.
_refused: dict[str, dict[int, str]] = {}


def sample_keys(dataset: str) -> list[str]:
    """The dataset's sampled clips: the clips that go into the product. VIRAT's are the
    demo sample; every other dataset's are the hand-check sample's (same columns)."""
    path = settings.demo_sample_path if dataset == "virat" else settings.hand_check_sample_path
    lines = Path(path).read_text(encoding="utf-8").splitlines()[1:]
    return [ln.split(",")[1] for ln in lines if ln.split(",")[0] == dataset]


def _in_subset(dataset: str):
    return and_(DatasetManifest.dataset == dataset, DatasetManifest.clip_key.in_(sample_keys(dataset)))


def _done():
    return and_(Video.status == VideoStatus.READY, Video.gate_stride_s.is_not(None))


def pending_clips(db: Session, dataset: str, limit: int) -> list[int]:
    """Manifest ids of clips in the subset not loaded yet, in clip order."""
    return list(
        db.scalars(
            select(DatasetManifest.id)
            .outerjoin(Video, Video.id == DatasetManifest.video_id)
            .where(_in_subset(dataset), ~func.coalesce(_done(), False))
            .order_by(DatasetManifest.clip_key)
            .limit(limit)
        )
    )


def load_clip(manifest_id: int) -> str | None:
    """Store (if not stored yet) and extract one clip. Returns why it failed, or None."""
    with SessionLocal() as db:
        clip = db.get(DatasetManifest, manifest_id)
        video = db.get(Video, clip.video_id) if clip.video_id is not None else None
        if video is None:
            path = Path(settings.datasets_path) / clip.dataset / clip.video_relpath
            try:
                with open(path, "rb") as f:
                    video, error = store_video(
                        f,
                        PurePosixPath(clip.video_relpath).name,
                        db,
                        source=VideoSource.DATASET,
                        on_insert=lambda v: setattr(clip, "video_id", v.id),
                    )
            except (UploadRejected, OSError) as exc:
                raise ClipRefused(str(exc)) from exc
        elif video.status == VideoStatus.UPLOADED:
            # Stored, but never probed (ingestion was down): the same probe the upload runs.
            error = _probe_and_finalize(video, db)
        else:
            error = None

        if video.status == VideoStatus.UPLOADED:
            return error or "not probed"
        if video.status == VideoStatus.FAILED and video.duration_s is None:
            # The probe refused the file: extraction would fail the same way.
            if error and not video.error:
                video.error = error
                db.commit()
            return video.error or error or "probe failed"
        video_id = video.id
        extraction_id = claim_extraction(db, video_id)
    if extraction_id is None:
        return "video could not be claimed for extraction"

    run_extraction(video_id, extraction_id)
    with SessionLocal() as db:
        video = db.get(Video, video_id)
        return None if video.status == VideoStatus.READY else (video.error or video.status.value)


def _run(job: _Job) -> None:
    global _job
    try:
        for manifest_id in job.manifest_ids:
            try:
                problem = load_clip(manifest_id)
            except ClipRefused as exc:
                problem = job.refused[manifest_id] = str(exc)
            except Exception as exc:  # noqa: BLE001 - one bad clip must not stop the rest
                problem = f"load failed: {exc}"
            if problem is not None:
                logger.warning(
                    "dataset clip not loaded",
                    extra={"extra_fields": {"dataset": job.dataset, "manifest_id": manifest_id, "error": problem}},
                )
            job.done += 1
    finally:
        with _lock:
            _refused[job.dataset] = dict(job.refused)
            _job = None
        logger.info(
            "dataset load finished",
            extra={"extra_fields": {"dataset": job.dataset, "clips": job.done, "not_loaded": len(job.refused)}},
        )


@router.get("", response_model=list[DatasetOut])
def list_datasets(db: Session = Depends(get_db), _user: User = Depends(get_current_user)) -> list[DatasetOut]:
    out = []
    for name, domain in DOMAINS.items():
        total = db.scalar(select(func.count()).select_from(DatasetManifest).where(_in_subset(name)))
        loaded, failed = db.execute(
            select(
                func.count().filter(_done()),
                func.count().filter(Video.status == VideoStatus.FAILED),
            )
            .select_from(DatasetManifest)
            .join(Video, Video.id == DatasetManifest.video_id)
            .where(_in_subset(name))
        ).one()
        derived, checked, verified = db.execute(
            select(
                func.count(),
                func.count().filter(EventWindow.verified.is_not(None)),
                func.count().filter(EventWindow.verified.is_(True)),
            )
            .select_from(EventWindow)
            .join(DatasetManifest, DatasetManifest.id == EventWindow.manifest_id)
            .where(DatasetManifest.dataset == name)
        ).one()
        with _lock:
            job = _job if _job is not None and _job.dataset == name else None
            running = job is not None
            failed += len(_refused.get(name, {}))
        if running:
            state = "loading"
        elif loaded == 0:
            state = "not_loaded"
        else:
            state = "loaded" if loaded == total else "partial"
        out.append(
            DatasetOut(
                name=name, domain=domain, videos_loaded=loaded, total=total, failed=failed, status=state,
                load_done=job.done if job else None, load_queued=len(job.manifest_ids) if job else None,
                windows_derived=derived, windows_checked=checked, windows_verified=verified,
            )
        )
    return out


@router.post("/{name}/load", response_model=LoadResponse, status_code=status.HTTP_202_ACCEPTED)
def load_dataset(
    name: str,
    payload: LoadRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(Role.ADMIN)),
) -> LoadResponse:
    """Queue up to `limit` clips not loaded yet and work through them in the
    background, one at a time. Poll `GET /datasets` for progress."""
    global _job
    if name not in DOMAINS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=DATASET_NOT_FOUND_MESSAGE)
    with _lock:
        if _job is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=LOAD_RUNNING_MESSAGE)
        ids = pending_clips(db, name, payload.limit)
        _refused.pop(name, None)
        if not ids:
            return LoadResponse(queued=0)
        _job = _Job(dataset=name, manifest_ids=ids)
        threading.Thread(target=_run, args=(_job,), name=f"dataset-load-{name}", daemon=True).start()
    return LoadResponse(queued=len(ids))
