"""Videos made ready on Colab, added to the system with their vectors (OMNI-X05).

The same idea as the VIRAT import (OMNI-708 `match_product`, OMNI-710, K-27): the same video,
gated by the same code with the same settings, keeps the same frames, so a vector made on
Colab belongs to the stored segment with the same frame index. What is new: any video.

Colab (`scripts/encode_uploads.py`) writes one folder per video, named by its fingerprint
(the SHA-256 of the file, D-47): the video file, `vectors.npz` (per admitted frame its index,
time, admission reason, SigLIP 2 vector and InternVideo2 vector) and `info.json` (the file's
name, the model pins and the extraction settings). `scripts/add_from_drive.py` copies a
folder from Drive into this container and calls `add_ready`:

- **not in the system yet:** the video is stored as an upload is (`store_video`), then
  extracted with the folder's vectors (`run_extraction(..., ready=...)`)
- **already in the system** (uploaded normally, under any name: the fingerprint is the
  same): extracted with the vectors if it never was, otherwise its vectors are imported

An extraction with vectors runs in two steps (`extraction._extract`):

1. **Before ingestion publishes** (`prepare`): refused if made with other pins or other
   settings. If usable, the video is marked `colab_vectors` and the consumer queues no CPU
   embed job for its frames
2. **Once every segment is stored** (`finish`): every admitted frame must match a row of
   `vectors.npz` (index, time, reason) and every row a frame. Then both vectors are
   upserted by segment id. Otherwise nothing is imported, the reason is logged, and the
   frames go to the CPU encoder: a video never ends up with no vectors

A frame or clip that already has a point of the pinned model is left alone, so adding the
same video twice changes nothing.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pika
from omnisight_common import VideoStatus, connection_parameters
from omnisight_common.clip_vectors import (
    CLIP_VECTOR_SIZE,
    clip_point,
    ensure_clip_collection,
)
from omnisight_common.frame_vectors import (
    FRAME_VECTOR_SIZE,
    ensure_frame_collection,
    frame_point,
    qdrant_client,
)
from qdrant_client import QdrantClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.embed_jobs import jobs_for_segments, publish_jobs
from app.ingestion_client import IngestionUnavailableError, extraction_settings
from app.models import Segment, Video
from app.settings import settings

logger = logging.getLogger("app.colab_vectors")

VECTORS = "vectors.npz"
INFO = "info.json"
PIN_NAMES = ("frame_model_id", "frame_model_revision", "clip_model_id", "clip_model_revision")
# A video's recorded gate parameters (set by extraction or a re-gate), by setting name.
VIDEO_GATE_COLUMNS = {
    "motion_stride_s": "gate_stride_s",
    "motion_grid_size": "gate_grid_size",
    "motion_cell_threshold": "gate_cell_threshold",
    "motion_min_active_cells": "gate_min_active_cells",
}
UNIT_TOLERANCE = 1e-3
TIME_TOLERANCE_S = 1e-6
BATCH = 100
CHUNK = 1 << 20


@dataclass
class ReadyVideo:
    """One ready folder: its video file and what is in `vectors.npz` and `info.json`."""

    folder: Path
    fingerprint: str
    file: str
    frame_index: np.ndarray
    timestamp_s: np.ndarray
    admission_reason: np.ndarray
    frame_vectors: np.ndarray
    clip_vectors: np.ndarray
    pins: dict
    gate: dict

    @property
    def video_path(self) -> Path:
        return self.folder / self.file


@dataclass
class ImportResult:
    segments: int
    file_rows: int
    unmatched: int
    frame_stored: int = 0
    clip_stored: int = 0

    @property
    def ok(self) -> bool:
        return self.unmatched == 0


def read_ready(folder: Path) -> ReadyVideo:
    info = json.loads((folder / INFO).read_text(encoding="utf-8"))
    with np.load(folder / VECTORS, allow_pickle=False) as data:
        return ReadyVideo(
            folder=folder,
            fingerprint=info["fingerprint"],
            file=info["file"],
            frame_index=data["frame_index"].astype(np.int64),
            timestamp_s=data["timestamp_s"].astype(np.float64),
            admission_reason=data["admission_reason"].astype(str),
            frame_vectors=data["frame_vectors"].astype(np.float32),
            clip_vectors=data["clip_vectors"].astype(np.float32),
            pins=info["pins"],
            gate=info["gate"],
        )


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


# --- checks: each returns the problem, or None ---------------------------------------------


def check_pins(ready: ReadyVideo) -> str | None:
    differ = [name for name in PIN_NAMES if ready.pins.get(name) != getattr(settings, name)]
    if differ:
        return "made with other model pins: " + ", ".join(f"{n}={ready.pins.get(n)}" for n in differ)
    return None


def check_settings(ready: ReadyVideo, used: dict) -> str | None:
    """`used`: the settings this video is (or was) extracted with, by ingestion's names."""
    differ = [
        name for name, value in used.items()
        if name not in ready.gate or float(ready.gate[name]) != float(value)
    ]
    if differ:
        return "made with other extraction settings: " + ", ".join(
            f"{n}={ready.gate.get(n)} (here {used[n]})" for n in differ
        )
    return None


def check_vectors(ready: ReadyVideo) -> str | None:
    n = len(ready.frame_index)
    if ready.frame_vectors.shape != (n, FRAME_VECTOR_SIZE) or ready.clip_vectors.shape != (n, CLIP_VECTOR_SIZE):
        return f"{n} frames, vectors of shape {ready.frame_vectors.shape} and {ready.clip_vectors.shape}"
    if len(set(ready.frame_index.tolist())) != n:
        return "a frame index appears twice"
    for name, vectors in (("frame", ready.frame_vectors), ("clip", ready.clip_vectors)):
        if not np.isfinite(vectors).all():
            return f"a {name} vector is not finite"
        norms = np.linalg.norm(vectors, axis=1)
        if n and np.abs(norms - 1).max() > UNIT_TOLERANCE:
            return f"a {name} vector is not unit length (norm {norms.min()} to {norms.max()})"
    return None


def usable(ready: ReadyVideo, used: dict) -> str | None:
    return check_pins(ready) or check_settings(ready, used) or check_vectors(ready)


def video_settings(video: Video, ingestion: dict) -> dict:
    """The settings the video's current segments were made with: ingestion's, with the gate
    parameters the video records (a re-gate may have changed them, OMNI-306)."""
    used = dict(ingestion)
    for name, column in VIDEO_GATE_COLUMNS.items():
        value = getattr(video, column)
        if value is not None:
            used[name] = value
    return used


def match(ready: ReadyVideo, segments: list) -> tuple[dict[int, int], int]:
    """(segment id -> row of `vectors.npz`, how many do not match). `segments` are the
    video's admitted frames with a file: `(id, frame_index, timestamp_s, admission_reason)`.
    A frame matches when the file has its index with the same time and reason; a row whose
    index is no admitted frame counts too."""
    row_of = {int(i): r for r, i in enumerate(ready.frame_index)}
    rows: dict[int, int] = {}
    unmatched = len(set(row_of) - {int(s[1]) for s in segments})
    for segment_id, frame_index, timestamp_s, reason in segments:
        r = row_of.get(int(frame_index))
        if (
            r is None
            or abs(float(ready.timestamp_s[r]) - float(timestamp_s)) > TIME_TOLERANCE_S
            or str(ready.admission_reason[r]) != (getattr(reason, "value", reason) or "")
        ):
            unmatched += 1
            continue
        rows[int(segment_id)] = r
    return rows, unmatched


# --- the import ------------------------------------------------------------------------------


def admitted_segments(db: Session, video_id: int) -> list:
    return db.execute(
        select(Segment.id, Segment.frame_index, Segment.timestamp_s, Segment.admission_reason)
        .where(Segment.video_id == video_id, Segment.admitted.is_(True), Segment.frame_path.is_not(None))
        .order_by(Segment.frame_index)
    ).all()


def _have(client: QdrantClient, collection: str, ids: list[int], model: str, revision: str) -> set[int]:
    """Which of `ids` already have a point of this model."""
    have: set[int] = set()
    if not client.collection_exists(collection):
        return have
    for start in range(0, len(ids), 1000):
        for point in client.retrieve(
            collection, ids=ids[start : start + 1000], with_payload=["model", "model_revision"], with_vectors=False
        ):
            if (point.payload or {}).get("model") == model and point.payload.get("model_revision") == revision:
                have.add(int(point.id))
    return have


def import_vectors(db: Session, client: QdrantClient, video_id: int, ready: ReadyVideo) -> ImportResult:
    """Every admitted frame matched, or nothing imported."""
    segments = admitted_segments(db, video_id)
    rows, unmatched = match(ready, segments)
    result = ImportResult(segments=len(segments), file_rows=len(ready.frame_index), unmatched=unmatched)
    if unmatched:
        return result
    ensure_frame_collection(client, settings.frame_collection)
    ensure_clip_collection(client, settings.clip_collection)
    ids = sorted(rows)
    jobs = jobs_for_segments(db, ids)
    sides = (
        (settings.frame_collection, settings.frame_model_id, settings.frame_model_revision, ready.frame_vectors, frame_point),
        (settings.clip_collection, settings.clip_model_id, settings.clip_model_revision, ready.clip_vectors, clip_point),
    )
    stored = []
    for collection, model, revision, vectors, make_point in sides:
        have = _have(client, collection, ids, model, revision)
        points = [
            make_point(jobs[i].payload(model, revision), vectors[rows[i]].tolist())
            for i in ids if i not in have
        ]
        for start in range(0, len(points), BATCH):
            client.upsert(collection, points[start : start + BATCH], wait=True)
        stored.append(len(points))
    result.frame_stored, result.clip_stored = stored
    return result


# --- an extraction's two steps ---------------------------------------------------------------


def prepare(video_id: int, ready: ReadyVideo | None) -> ReadyVideo | None:
    """Before ingestion publishes: `ready` if its vectors can be used, else None. Marks the
    video either way, so the consumer knows whether to queue CPU jobs for its frames. A
    normal upload passes None: encoded on the CPU, as before."""
    if ready is not None:
        try:
            problem = usable(ready, extraction_settings())
        except IngestionUnavailableError as exc:
            problem = f"ingestion's settings could not be read: {exc}"[:300]
        if problem:
            logger.warning(
                "drive vectors refused, encoding on the CPU",
                extra={"extra_fields": {"video_id": video_id, "fingerprint": ready.fingerprint, "problem": problem}},
            )
            ready = None
    with SessionLocal() as db:
        db.query(Video).filter_by(id=video_id).update({"colab_vectors": ready is not None}, synchronize_session=False)
        db.commit()
    return ready


def finish(video_id: int, ready: ReadyVideo) -> ImportResult | None:
    """After every segment is stored: import, or fall back to the CPU encode."""
    try:
        client = qdrant_client(settings)
        try:
            with SessionLocal() as db:
                result = import_vectors(db, client, video_id, ready)
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001 - whatever happens, the frames get vectors
        fall_back(video_id, f"import failed: {exc!r}"[:300])
        return None
    if not result.ok:
        fall_back(video_id, f"{result.unmatched} frames do not match ({result.segments} admitted, {result.file_rows} in the file)")
        return result
    logger.info(
        "drive vectors imported",
        extra={"extra_fields": {
            "video_id": video_id, "frames": result.segments,
            "frame_stored": result.frame_stored, "clip_stored": result.clip_stored,
        }},
    )
    return result


def fall_back(video_id: int, reason: str) -> None:
    """Nothing imported: the video's frames are queued for the CPU encoder, as a normal
    upload's are."""
    logger.warning(
        "drive vectors not imported, encoding on the CPU",
        extra={"extra_fields": {"video_id": video_id, "reason": reason}},
    )
    with SessionLocal() as db:
        db.query(Video).filter_by(id=video_id).update({"colab_vectors": False}, synchronize_session=False)
        db.commit()
        jobs = jobs_for_segments(db, [row.id for row in admitted_segments(db, video_id)])
    connection = pika.BlockingConnection(connection_parameters(settings))
    try:
        channel = connection.channel()
        channel.confirm_delivery()
        publish_jobs(channel, settings.embed_queue, [jobs[i] for i in sorted(jobs)])
    finally:
        connection.close()


# --- add_from_drive.py's two calls -----------------------------------------------------------


def status(fingerprints: list[str]) -> dict[str, dict]:
    """Per fingerprint: the video already holding it (the oldest), if any, and whether its
    admitted frames all have both vectors."""
    out: dict[str, dict] = {}
    client = qdrant_client(settings)
    try:
        with SessionLocal() as db:
            for fp in fingerprints:
                video = db.query(Video).filter_by(fingerprint=fp).order_by(Video.id).first()
                if video is None:
                    out[fp] = {"video_id": None}
                    continue
                out[fp] = {"video_id": video.id, **counts(db, client, video.id)}
    finally:
        client.close()
    return out


def counts(db: Session, client: QdrantClient, video_id: int) -> dict:
    video = db.get(Video, video_id)
    ids = [row.id for row in admitted_segments(db, video_id)]
    return {
        "status": video.status.value,
        "admitted": len(ids),
        "frame_vectors": len(_have(client, settings.frame_collection, ids, settings.frame_model_id, settings.frame_model_revision)),
        "clip_vectors": len(_have(client, settings.clip_collection, ids, settings.clip_model_id, settings.clip_model_revision)),
    }


def add_ready(folder: Path) -> dict:
    """Add one ready folder (copied into this container): store and extract the video with
    its vectors, or import them into the video that already holds the same file."""
    # Here, not at the top: app.videos imports app.extraction, which imports this module.
    from app.extraction import claim_extraction, run_extraction
    from app.videos import store_video

    ready = read_ready(folder)
    if fingerprint(ready.video_path) != ready.fingerprint:
        return {"result": "refused", "problem": "the video file is not the one its vectors were made from"}
    with SessionLocal() as db:
        video = db.query(Video).filter_by(fingerprint=ready.fingerprint).order_by(Video.id).first()
        if video is None:
            with open(ready.video_path, "rb") as f:
                video, probe_error = store_video(f, ready.file, db)
            if probe_error is not None:
                return {"result": "failed", "video_id": video.id, "problem": probe_error}
            action = "added"
        else:
            action = "existing"
        video_id = video.id
        extracted = db.query(Segment.id).filter_by(video_id=video_id).first() is not None

    if not extracted:
        with SessionLocal() as db:
            extraction_id = claim_extraction(db, video_id)
        if extraction_id is None:
            return {"result": "busy", "video_id": video_id, "problem": "the video is not ready to extract (still extracting?)"}
        run_extraction(video_id, extraction_id, ready)
        with SessionLocal() as db:
            video = db.get(Video, video_id)
            if video.status != VideoStatus.READY:
                return {"result": "failed", "video_id": video_id, "problem": video.error}
            imported = video.colab_vectors
        problem = None if imported else "vectors refused or frames did not match: encoding on the CPU (see query's log)"
    else:
        with SessionLocal() as db:
            video = db.get(Video, video_id)
            if video.status != VideoStatus.READY:
                return {"result": "busy", "video_id": video_id, "problem": f"the video is {video.status.value}"}
            problem = usable(ready, video_settings(video, extraction_settings()))
            if problem is None:
                client = qdrant_client(settings)
                try:
                    result = import_vectors(db, client, video_id, ready)
                finally:
                    client.close()
                if result.ok:
                    video.colab_vectors = True
                    db.commit()
                else:
                    problem = f"{result.unmatched} frames do not match ({result.segments} admitted, {result.file_rows} in the file)"

    client = qdrant_client(settings)
    try:
        with SessionLocal() as db:
            report = counts(db, client, video_id)
    finally:
        client.close()
    return {"result": "refused" if problem else action, "video_id": video_id, "problem": problem, **report}
