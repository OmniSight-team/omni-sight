"""`GET /search` (OMNI-707): natural-language search over stored video, a ranked list of the
most relevant moments (Phase A FR-4).

    query text -> ai_workers (SigLIP 2 text, cached by exact text)
               -> Qdrant `frame_vectors`: cosine, top k, camera and date filtered inside
                  the search, only vectors of the pinned model
               -> Postgres: each hit joined to its segment, video and camera

`mode` is part of the API from the start: `frame` works now; `clip` and `fused` need the
clip index (OMNI-710) and Algorithm 3 (OMNI-711), and until then answer that the clip index
is not ready.

A hit whose segment no longer exists or is no longer admitted (a deleted or re-gated
video's old point, K-24) is left out, counted in `dropped` and logged; the response then
holds fewer than `k` moments.
"""

import logging
import time
from datetime import UTC, datetime
from enum import StrEnum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from omnisight_common import Role
from qdrant_client import QdrantClient, models
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai_workers_client
from app.db import get_db
from app.deps import require_role
from app.embeddings import get_qdrant
from app.models import Camera, Segment, User
from app.schemas import SearchCameraOut, SearchHitOut, SearchOut, SearchTimingsOut
from app.settings import settings
from app.videos import _thumb_url

logger = logging.getLogger("app.search")
router = APIRouter(prefix="/search", tags=["search"])

MAX_K = 50
EMPTY_QUERY = "the query is empty"
CLIP_INDEX_NOT_READY = "the clip index is not ready yet: only mode=frame can search for now"
ENCODER_UNAVAILABLE = "the text encoder (ai_workers) is unreachable"
WRONG_MODEL = "the text encoder runs another model than the stored vectors"
STORE_UNAVAILABLE = "the vector store is unreachable"
NOTHING_INDEXED = "nothing is indexed yet: no frame has a vector"


class SearchMode(StrEnum):
    FRAME = "frame"
    CLIP = "clip"
    FUSED = "fused"


def _ms(since: float) -> float:
    return round((time.perf_counter() - since) * 1000, 1)


def _utc(moment: datetime | None) -> datetime | None:
    """A time without a zone is read as UTC, the zone `captured_at` is stored in."""
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=UTC)


def _same_model() -> list[models.FieldCondition]:
    return [
        models.FieldCondition(key="model", match=models.MatchValue(value=settings.frame_model_id)),
        models.FieldCondition(key="model_revision", match=models.MatchValue(value=settings.frame_model_revision)),
    ]


def _filter(camera_id: int | None, start: datetime | None, end: datetime | None) -> models.Filter:
    """Applied by Qdrant during the search (indexed payload, OMNI-703), so a camera's best
    match is found even when other cameras' frames rank above it."""
    must = _same_model()
    if camera_id is not None:
        must.append(models.FieldCondition(key="camera_id", match=models.MatchValue(value=camera_id)))
    if start is not None or end is not None:
        must.append(models.FieldCondition(key="captured_at", range=models.DatetimeRange(gte=start, lte=end)))
    return models.Filter(must=must)


@router.get("", response_model=SearchOut)
def search(
    q: str = Query(..., max_length=1000),
    mode: SearchMode = SearchMode.FRAME,
    k: int = Query(5, ge=1, le=MAX_K),
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
    if mode is not SearchMode.FRAME:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=CLIP_INDEX_NOT_READY)

    step = time.perf_counter()
    try:
        vector, cached = ai_workers_client.text_vector(
            text,
            path=ai_workers_client.FRAME_TEXT,
            model=settings.frame_model_id,
            model_revision=settings.frame_model_revision,
        )
    except ai_workers_client.AiWorkersUnavailableError as exc:
        logger.warning("search: text encoder unreachable", extra={"extra_fields": {"error": str(exc)}})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=ENCODER_UNAVAILABLE) from exc
    except ai_workers_client.WrongModelError as exc:
        logger.error("search: text encoder model mismatch", extra={"extra_fields": {"error": str(exc)}})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=WRONG_MODEL) from exc
    encode_ms = _ms(step)

    step = time.perf_counter()
    try:
        hits = qdrant.query_points(
            collection_name=settings.frame_collection,
            query=vector,
            query_filter=_filter(camera_id, start, end),
            limit=k,
            with_payload=["captured_at"],
        ).points
        indexed = bool(hits) or qdrant.count(
            settings.frame_collection, count_filter=models.Filter(must=_same_model()), exact=False
        ).count > 0
    except Exception as exc:  # noqa: BLE001 - any Qdrant failure means the same to the caller
        logger.warning("search: vector store unreachable", extra={"extra_fields": {"error": str(exc)}})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=STORE_UNAVAILABLE) from exc
    search_ms = _ms(step)

    step = time.perf_counter()
    ids = [int(hit.id) for hit in hits]
    rows = {
        row.id: row
        for row in db.execute(
            select(Segment.id, Segment.video_id, Segment.timestamp_s, Segment.thumb_path, Camera.id.label("camera_id"), Camera.name)
            .outerjoin(Camera, Camera.id == Segment.camera_id)
            .where(Segment.id.in_(ids), Segment.admitted.is_(True))
        )
    }
    results = []
    for hit in hits:
        row = rows.get(int(hit.id))
        if row is None:
            continue
        results.append(SearchHitOut(
            segment_id=row.id,
            video_id=row.video_id,
            camera=None if row.camera_id is None else SearchCameraOut(id=row.camera_id, name=row.name),
            timestamp_s=row.timestamp_s,
            captured_at=hit.payload["captured_at"],
            score=hit.score,
            matched_by=SearchMode.FRAME.value,
            thumb_url=_thumb_url(row.thumb_path),
        ))
    dropped = len(hits) - len(results)
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
        timings=SearchTimingsOut(encode_ms=encode_ms, search_ms=search_ms, join_ms=join_ms, encode_cached=cached),
        total=len(results),
        dropped=dropped,
        message=None if indexed else NOTHING_INDEXED,
    )
