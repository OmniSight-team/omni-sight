"""`GET /search` (OMNI-707, OMNI-711): natural-language search over stored video, a ranked list
of the most relevant moments (Phase A FR-4).

    query text -> ai_workers (SigLIP 2 and / or InternVideo2 text, cached by exact text)
               -> Qdrant `frame_vectors` and / or `clip_vectors`: cosine, top k, camera and
                  date filtered inside the search, only vectors of the pinned model
               -> `fused`: Algorithm 3, the two lists merged by rank (`omnisight_common.fusion`)
               -> Postgres: each hit joined to its segment, video and camera

`mode=frame` and `mode=clip` score by cosine; `mode=fused` by B.3's reciprocal rank score,
which is on another scale.

A hit whose segment no longer exists or is no longer admitted (a deleted or re-gated
video's old point, K-24) is left out, counted in `dropped` and logged; the response then
holds fewer than `k` moments.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, status
from omnisight_common import Role
from omnisight_common.fusion import ModalityClassifier, fuse
from qdrant_client import QdrantClient, models
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai_workers_client
from app.db import get_db
from app.deps import require_role
from app.embeddings import get_qdrant
from app.models import Camera, Segment, User, Video
from app.schemas import SearchCameraOut, SearchHitOut, SearchOut, SearchTimingsOut
from app.settings import settings
from app.videos import _thumb_url

logger = logging.getLogger("app.search")
router = APIRouter(prefix="/search", tags=["search"])

MAX_K = 50
EMPTY_QUERY = "the query is empty"
ENCODER_UNAVAILABLE = "the text encoder (ai_workers) is unreachable"
WRONG_MODEL = "the text encoder runs another model than the stored vectors"
WRONG_CLASSIFIER = "the modality classifier was trained on another text encoder"
STORE_UNAVAILABLE = "the vector store is unreachable"
NOTHING_INDEXED = "nothing is indexed yet: no frame has a vector"


class SearchMode(StrEnum):
    FRAME = "frame"
    CLIP = "clip"
    FUSED = "fused"


@dataclass(frozen=True)
class Stream:
    """One of Algorithm 3's two sides: its text encoder and its index."""

    path: str
    collection: str
    model: str
    model_revision: str


FRAME = Stream(ai_workers_client.FRAME_TEXT, settings.frame_collection, settings.frame_model_id, settings.frame_model_revision)
CLIP = Stream(ai_workers_client.CLIP_TEXT, settings.clip_collection, settings.clip_model_id, settings.clip_model_revision)


@dataclass(frozen=True)
class RankedHit:
    segment_id: int
    score: float
    matched_by: str
    captured_at: str


def _ms(since: float) -> float:
    return round((time.perf_counter() - since) * 1000, 1)


def _utc(moment: datetime | None) -> datetime | None:
    """A time without a zone is read as UTC, the zone `captured_at` is stored in."""
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=UTC)


def _same_model(stream: Stream) -> list[models.FieldCondition]:
    return [
        models.FieldCondition(key="model", match=models.MatchValue(value=stream.model)),
        models.FieldCondition(key="model_revision", match=models.MatchValue(value=stream.model_revision)),
    ]


def _filter(
    stream: Stream, video_id: int | None, camera_id: int | None, start: datetime | None, end: datetime | None
) -> models.Filter:
    """Applied by Qdrant during the search (indexed payload, OMNI-703), so a video's or a
    camera's best match is found even when other footage ranks above it."""
    must = _same_model(stream)
    if video_id is not None:
        must.append(models.FieldCondition(key="video_id", match=models.MatchValue(value=video_id)))
    if camera_id is not None:
        must.append(models.FieldCondition(key="camera_id", match=models.MatchValue(value=camera_id)))
    if start is not None or end is not None:
        must.append(models.FieldCondition(key="captured_at", range=models.DatetimeRange(gte=start, lte=end)))
    return models.Filter(must=must)


def _text_vector(text: str, stream: Stream) -> tuple[list[float], bool]:
    try:
        return ai_workers_client.text_vector(text, path=stream.path, model=stream.model, model_revision=stream.model_revision)
    except ai_workers_client.AiWorkersUnavailableError as exc:
        logger.warning("search: text encoder unreachable", extra={"extra_fields": {"error": str(exc)}})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ENCODER_UNAVAILABLE) from exc
    except ai_workers_client.WrongModelError as exc:
        logger.error("search: text encoder model mismatch", extra={"extra_fields": {"error": str(exc)}})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=WRONG_MODEL) from exc


@lru_cache(maxsize=1)
def _classifier() -> ModalityClassifier:
    return ModalityClassifier.load(settings.frame_model_id, settings.frame_model_revision)


def _weights(frame_vector: list[float]) -> tuple[float, float]:
    try:
        return _classifier().weights(frame_vector)
    except ValueError as exc:
        logger.error("search: modality classifier mismatch", extra={"extra_fields": {"error": str(exc)}})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=WRONG_CLASSIFIER) from exc


@router.get("", response_model=SearchOut)
def search(
    q: str = Query(..., max_length=1000),
    mode: SearchMode = SearchMode.FRAME,
    k: int = Query(5, ge=1, le=MAX_K),
    video_id: int | None = None,
    camera_id: int | None = None,
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
    qdrant: QdrantClient = Depends(get_qdrant),
    # Phase A: operators and analysts search (§3.4, use cases); admins can do everything.
    _user: User = Depends(require_role(Role.OPERATOR, Role.ANALYST, Role.ADMIN)),
) -> SearchOut:
    started = time.perf_counter()
    text = q.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=EMPTY_QUERY)
    start, end = _utc(start), _utc(end)
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="`from` is after `to`")
    streams = {SearchMode.FRAME: [FRAME], SearchMode.CLIP: [CLIP], SearchMode.FUSED: [FRAME, CLIP]}[mode]

    step = time.perf_counter()
    encoded = [_text_vector(text, stream) for stream in streams]
    cached = all(from_cache for _, from_cache in encoded)
    encode_ms = _ms(step)

    step = time.perf_counter()
    try:
        lists = [
            qdrant.query_points(
                collection_name=stream.collection,
                query=vector,
                query_filter=_filter(stream, video_id, camera_id, start, end),
                limit=k,
                with_payload=["captured_at"],
            ).points
            for stream, (vector, _) in zip(streams, encoded, strict=True)
        ]
        indexed = any(lists) or any(
            qdrant.count(stream.collection, count_filter=models.Filter(must=_same_model(stream)), exact=False).count > 0
            for stream in streams
        )
    except Exception as exc:  # noqa: BLE001 - any Qdrant failure means the same to the caller
        logger.warning("search: vector store unreachable", extra={"extra_fields": {"error": str(exc)}})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=STORE_UNAVAILABLE) from exc
    search_ms = _ms(step)

    step = time.perf_counter()
    if mode is SearchMode.FUSED:
        w_f, w_c = _weights(encoded[0][0])
        captured = {int(hit.id): hit.payload["captured_at"] for hits in lists for hit in hits}
        ranked = [
            RankedHit(hit.segment_id, hit.score, hit.matched_by, captured[hit.segment_id])
            for hit in fuse([int(h.id) for h in lists[0]], [int(h.id) for h in lists[1]], w_f, w_c, k)
        ]
    else:
        ranked = [RankedHit(int(hit.id), hit.score, mode.value, hit.payload["captured_at"]) for hit in lists[0]]
    fusion_ms = _ms(step)

    step = time.perf_counter()
    ids = [hit.segment_id for hit in ranked]
    rows = {
        row.id: row
        for row in db.execute(
            select(Segment.id, Segment.video_id, Segment.timestamp_s, Segment.thumb_path, Camera.id.label("camera_id"), Camera.name, Video.filename)
            .outerjoin(Camera, Camera.id == Segment.camera_id)
            .outerjoin(Video, Video.id == Segment.video_id)
            .where(Segment.id.in_(ids), Segment.admitted.is_(True))
        )
    }
    results = []
    for hit in ranked:
        row = rows.get(hit.segment_id)
        if row is None:
            continue
        results.append(SearchHitOut(
            segment_id=row.id,
            video_id=row.video_id,
            filename=row.filename,
            camera=None if row.camera_id is None else SearchCameraOut(id=row.camera_id, name=row.name),
            timestamp_s=row.timestamp_s,
            captured_at=hit.captured_at,
            score=hit.score,
            matched_by=hit.matched_by,
            thumb_url=_thumb_url(row.thumb_path),
            frame_url=f"/cameras/{row.camera_id}/frames/{row.id}/image" if row.video_id is None else None,
        ))
    dropped = len(ranked) - len(results)
    if dropped:
        logger.warning(
            "search: hits without an admitted segment dropped",
            extra={"extra_fields": {"dropped": dropped, "segment_ids": sorted(set(ids) - set(rows))}},
        )
    join_ms = _ms(step)

    return SearchOut(
        results=results,
        mode=mode.value,
        elapsed_ms=_ms(started),
        timings=SearchTimingsOut(
            encode_ms=encode_ms, search_ms=search_ms, fusion_ms=fusion_ms, join_ms=join_ms, encode_cached=cached
        ),
        total=len(results),
        dropped=dropped,
        message=None if indexed else NOTHING_INDEXED,
    )
