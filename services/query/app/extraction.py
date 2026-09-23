"""Frame extraction for a stored video, run in the background.

Query owns the database and ingestion owns the decoding, so this module is the
seam: it asks ingestion to cut the frames, then stores the result. A video
ends up with either all of its segments or none of them, and never stays
`extracting` — every way this can go wrong lands on `failed` with a reason.
"""

import logging
import shutil
from pathlib import Path

from omnisight_common import (
    AdmissionReason,
    SegmentSourceType,
    VideoSource,
    VideoStatus,
)
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.ingestion_client import IngestionUnavailableError
from app.ingestion_client import extract_file as ingestion_extract_file
from app.models import Segment, Video
from app.settings import settings

logger = logging.getLogger("app.extraction")

# Long enough for any real reason, short enough for a column people read.
MAX_ERROR_LENGTH = 500

INTERRUPTED_MESSAGE = "extraction was interrupted by a restart"


class GateError(Exception):
    """A re-gate attempt (OMNI-306) failed. Unlike a first extraction, a
    re-gate starts from segments that are already valid — a failed attempt to
    recompute them is not reason enough to lose access to what is already
    there, so the caller reverts the video to `ready` rather than `failed`."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def segment_file_paths(db: Session, video_id: int) -> list[Path]:
    """Every frame and thumbnail file the video's segment rows point at.

    Most rows have neither (OMNI-303 rework: only admitted frames get a
    JPEG), so None entries are skipped rather than turned into a path.
    """
    paths: list[Path] = []
    for frame_path, thumb_path in db.query(Segment.frame_path, Segment.thumb_path).filter_by(
        video_id=video_id
    ):
        paths.extend(Path(p) for p in (frame_path, thumb_path) if p is not None)
    return paths


def remove_segment_files(video_id: int, paths: list[Path]) -> None:
    """Remove a video's frame and thumbnail files, then its two folders.

    The folders are `{frames_path}/{video_id}` and `{thumbs_path}/{video_id}`,
    the layout ingestion writes, so removing them also catches files that never
    got a row (a crashed extraction). Failures are logged, never raised: this
    always runs after the database change it accompanies has been committed.
    """
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(
                "file could not be removed after its row was deleted",
                extra={"extra_fields": {"video_id": video_id, "path": str(path), "error": str(exc)}},
            )
    for root in (settings.frames_path, settings.thumbs_path):
        shutil.rmtree(Path(root) / str(video_id), ignore_errors=True)


def _segment_source_type(source: VideoSource) -> SegmentSourceType:
    # Segments only distinguish a stored file from a live camera; dataset
    # footage arrives through the upload path.
    return SegmentSourceType.CAMERA if source == VideoSource.CAMERA else SegmentSourceType.UPLOAD


def _fail(video_id: int, reason: str) -> None:
    reason = reason[:MAX_ERROR_LENGTH]
    logger.warning(
        "video extraction failed",
        extra={"extra_fields": {"video_id": video_id, "error": reason}},
    )
    with SessionLocal() as db:
        db.query(Video).filter_by(id=video_id).update(
            {"status": VideoStatus.FAILED, "error": reason}, synchronize_session=False
        )
        db.commit()


def run_extraction(video_id: int) -> None:
    """Replace a video's segments with a fresh extraction. Called as a
    background task after the video has been marked `extracting`."""
    try:
        _extract(video_id)
    except Exception as exc:  # noqa: BLE001 - nothing may leave a video stuck on `extracting`
        _fail(video_id, f"extraction failed: {exc}")


def _extract(video_id: int) -> None:
    with SessionLocal() as db:
        video = db.get(Video, video_id)
        if video is None:
            return
        path, source, camera_id = video.path, video.source, video.camera_id

        # Re-running replaces: the old rows and their files go first, so a
        # failure below leaves no segments rather than segments whose files
        # ingestion has already overwritten.
        old_paths = segment_file_paths(db, video_id)
        db.query(Segment).filter_by(video_id=video_id).delete(synchronize_session=False)
        db.commit()
    remove_segment_files(video_id, old_paths)

    try:
        result = ingestion_extract_file(video_id, path, _segment_source_type(source).value, camera_id)
    except IngestionUnavailableError as exc:
        _fail(video_id, "ingestion service unavailable")
        logger.warning(
            "extraction skipped, ingestion unavailable",
            extra={"extra_fields": {"video_id": video_id, "error": str(exc)}},
        )
        return

    if not result["ok"]:
        _fail(video_id, result.get("error") or "extraction failed")
        return

    try:
        with SessionLocal() as db:
            # One transaction: the rows and the status change land together.
            db.add_all(
                [
                    Segment(**{**segment, "source_type": SegmentSourceType(segment["source_type"])})
                    for segment in result["segments"]
                ]
            )
            db.query(Video).filter_by(id=video_id).update(
                {
                    "status": VideoStatus.READY,
                    "error": None,
                    # Recorded even for a plain extraction (default-parameter
                    # gating counts as one run of Algorithm 1 like any other)
                    # so "the parameters used" is always true of a `ready`
                    # video, not only one that has since been re-gated.
                    "gate_stride_s": result.get("stride_s"),
                    "gate_grid_size": result.get("grid_size"),
                    "gate_cell_threshold": result.get("cell_threshold"),
                    "gate_min_active_cells": result.get("min_active_cells"),
                },
                synchronize_session=False,
            )
            db.commit()
    except Exception:
        # The files are on disk but no row will ever point at them.
        remove_segment_files(video_id, [])
        raise


def run_gate(
    video_id: int,
    *,
    stride_s: float | None,
    grid_size: int | None,
    cell_threshold: float | None,
    min_active_cells: int | None,
) -> dict[str, int]:
    """Re-run Algorithm 1 against a video's source with new parameters,
    updating its existing segment rows **in place** — no row is ever deleted
    or created here, so a segment's own identity (its id, its created_at)
    survives being re-gated any number of times. Called synchronously (no
    background task): the ticket's own sketch of this endpoint returns counts
    directly, not a status to poll.

    Runs against a fresh decode of the source video, not the frames already
    on disk. Only admitted (and heartbeat) frames ever had a JPEG in the first
    place — re-scoring only those could never turn a previously discarded
    frame into an admitted one, since its pixels would already be gone. That
    asymmetry would make a threshold slider (OMNI-310) work in one direction
    only. Re-decoding costs the same time a first extraction does but is the
    only option that keeps a downward-sliding threshold meaningful.

    The route is what claims the video (status -> extracting) before calling
    this, and what reverts it back to `ready` on a `GateError` — kept there,
    not here, so this function's only job is the ingestion call and the
    update.
    """
    with SessionLocal() as db:
        video = db.get(Video, video_id)
        path, source, camera_id = video.path, video.source, video.camera_id

    try:
        result = ingestion_extract_file(
            video_id,
            path,
            _segment_source_type(source).value,
            camera_id,
            stride_s=stride_s,
            grid_size=grid_size,
            cell_threshold=cell_threshold,
            min_active_cells=min_active_cells,
        )
    except IngestionUnavailableError as exc:
        raise GateError("ingestion service unavailable") from exc

    if not result["ok"]:
        raise GateError(result.get("error") or "gating failed")

    segments = result["segments"]
    admitted = 0
    with SessionLocal() as db:
        rows = {row.frame_index: row for row in db.query(Segment).filter_by(video_id=video_id).all()}
        if {segment["frame_index"] for segment in segments} != set(rows):
            # The source file changed shape since the last extraction (or
            # never had one) — updating a mismatched set of rows would silently
            # corrupt the video's segments rather than fail cleanly.
            raise GateError("frame count changed since the last extraction — re-extract before re-gating")

        for segment in segments:
            row = rows[segment["frame_index"]]
            row.motion_score = segment["motion_score"]
            row.admitted = segment["admitted"]
            row.clip_start_s = segment["clip_start_s"]
            row.clip_end_s = segment["clip_end_s"]
            row.admission_reason = (
                AdmissionReason(segment["admission_reason"]) if segment["admission_reason"] else None
            )
            row.frame_path = segment["frame_path"]
            row.thumb_path = segment["thumb_path"]
            if segment["admitted"]:
                admitted += 1

        db.query(Video).filter_by(id=video_id).update(
            {
                "status": VideoStatus.READY,
                "gate_stride_s": result["stride_s"],
                "gate_grid_size": result["grid_size"],
                "gate_cell_threshold": result["cell_threshold"],
                "gate_min_active_cells": result["min_active_cells"],
            },
            synchronize_session=False,
        )
        db.commit()

    return {"admitted": admitted, "discarded": len(segments) - admitted}


def mark_interrupted_extractions() -> int:
    """Called at startup. A video still `extracting` when the service starts had
    its background task killed with the previous process, so it would stay in
    that state forever. Returns how many were reset."""
    with SessionLocal() as db:
        count = (
            db.query(Video)
            .filter_by(status=VideoStatus.EXTRACTING)
            .update({"status": VideoStatus.FAILED, "error": INTERRUPTED_MESSAGE}, synchronize_session=False)
        )
        db.commit()
    if count:
        logger.warning(
            "extractions interrupted by a restart marked failed",
            extra={"extra_fields": {"count": count}},
        )
    return count
