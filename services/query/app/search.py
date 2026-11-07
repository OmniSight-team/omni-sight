"""`GET /search` (OMNI-707, OMNI-711): natural-language search over stored video, a ranked list
of the most relevant moments (Phase A FR-4).

    query text -> ai_workers (SigLIP 2 and / or InternVideo2 text, cached by exact text)
               -> Qdrant `frame_vectors` and / or `clip_vectors`: cosine, top k, video, camera,
                  source and date filtered inside the search, only vectors of the pinned model
               -> `fused`: Algorithm 3, the two lists merged by rank (`omnisight_common.fusion`)
               -> Postgres: each hit joined to its segment, video and camera

`mode=frame` and `mode=clip` score by cosine; `mode=fused` by B.3's reciprocal rank score,
which is on another scale.

`per_footage` (D-44, the Search page): at most that many moments of one video or camera.
Each vector search is then grouped by the payload's `footage` inside Qdrant (best groups,
best hits of each), `fused` merges those grouped lists by B.3's rule, and the merged list
keeps at most `per_footage` of each footage. Without it, nothing changes (B.3 as before).

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
from omnisight_common.box_prompts import prompts_for
from omnisight_common.fusion import ModalityClassifier, fuse, tuned_weights
from qdrant_client import QdrantClient, models
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai_workers_client
from app.db import get_db
from app.deps import require_role
from app.embeddings import get_qdrant
from app.models import Camera, Segment, User, Video
from app.schemas import SearchBoxOut, SearchCameraOut, SearchHitOut, SearchOut, SearchTimingsOut
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


class SearchSource(StrEnum):
    """D-43: where footage comes from. A dataset clip is stored as an upload; the payload's
    `dataset` (its name, or empty) is what tells the two apart."""

    CAMERA = "camera"
    UPLOAD = "upload"
    DATASET = "dataset"


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
    dataset: str | None
    footage: str | None


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


def _no_dataset() -> models.IsEmptyCondition:
    # Empty = no `dataset` key (a point from before D-43's backfill) or null: both mean "not a
    # dataset clip".
    return models.IsEmptyCondition(is_empty=models.PayloadField(key="dataset"))


def _source_condition(source: SearchSource) -> models.Filter:
    if source is SearchSource.CAMERA:
        return models.Filter(must=[models.FieldCondition(key="source_type", match=models.MatchValue(value="camera"))])
    if source is SearchSource.UPLOAD:
        return models.Filter(must=[
            models.FieldCondition(key="source_type", match=models.MatchValue(value="upload")),
            _no_dataset(),
        ])
    return models.Filter(must_not=[_no_dataset()])


def _filter(
    stream: Stream,
    video_id: int | None,
    camera_id: int | None,
    start: datetime | None,
    end: datetime | None,
    sources: list[SearchSource] | None = None,
) -> models.Filter:
    """Applied by Qdrant during the search (indexed payload, OMNI-703), so a video's or a
    camera's best match is found even when other footage ranks above it. Several sources
    are one condition that any of them satisfies (D-43)."""
    must: list = _same_model(stream)
    if video_id is not None:
        must.append(models.FieldCondition(key="video_id", match=models.MatchValue(value=video_id)))
    if camera_id is not None:
        must.append(models.FieldCondition(key="camera_id", match=models.MatchValue(value=camera_id)))
    if start is not None or end is not None:
        must.append(models.FieldCondition(key="captured_at", range=models.DatetimeRange(gte=start, lte=end)))
    if sources:
        must.append(models.Filter(should=[_source_condition(s) for s in dict.fromkeys(sources)]))
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
        return tuned_weights(_classifier().weights(frame_vector)[0])
    except ValueError as exc:
        logger.error("search: modality classifier mismatch", extra={"extra_fields": {"error": str(exc)}})
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=WRONG_CLASSIFIER) from exc


PAYLOAD = ["captured_at", "dataset", "footage"]


def _ranked_points(
    qdrant: QdrantClient, stream: Stream, vector: list[float], query_filter: models.Filter, k: int, per_footage: int | None
) -> list[models.ScoredPoint]:
    """One stream's ranked list. With `per_footage`, Qdrant groups by `footage`: the `k` best
    videos or cameras, each with up to `per_footage` of its best hits, by score (D-44)."""
    if per_footage is None:
        return qdrant.query_points(
            collection_name=stream.collection, query=vector, query_filter=query_filter, limit=k, with_payload=PAYLOAD
        ).points
    groups = qdrant.query_points_groups(
        collection_name=stream.collection, group_by="footage", query=vector, query_filter=query_filter,
        limit=k, group_size=per_footage, with_payload=PAYLOAD,
    ).groups
    return sorted((hit for group in groups for hit in group.hits), key=lambda hit: hit.score, reverse=True)


def _per_footage(ranked: list[RankedHit], per_footage: int | None, k: int) -> list[RankedHit]:
    """The first `k`, at most `per_footage` of each video or camera, in rank order."""
    if per_footage is None:
        return ranked[:k]
    kept: list[RankedHit] = []
    seen: dict[str | None, int] = {}
    for hit in ranked:
        if seen.get(hit.footage, 0) < per_footage:
            seen[hit.footage] = seen.get(hit.footage, 0) + 1
            kept.append(hit)
            if len(kept) == k:
                break
    return kept


@router.get("", response_model=SearchOut)
def search(
    q: str = Query(..., max_length=1000),
    mode: SearchMode = SearchMode.FRAME,
    k: int = Query(5, ge=1, le=MAX_K),
    video_id: int | None = None,
    camera_id: int | None = None,
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    # D-43: one or several, e.g. `?source=camera&source=dataset`; none means every source.
    source: list[SearchSource] | None = Query(None),
    # D-44: at most this many moments of one video or camera (the Search page); none = B.3 as is.
    per_footage: int | None = Query(None, ge=1, le=MAX_K),
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
            _ranked_points(qdrant, stream, vector, _filter(stream, video_id, camera_id, start, end, source), k, per_footage)
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
        payloads = {int(hit.id): hit.payload for hits in lists for hit in hits}
        # Grouped lists can be longer than k: everything is merged, then cut below.
        depth = k if per_footage is None else len(payloads)
        ranked = [
            RankedHit(
                hit.segment_id, hit.score, hit.matched_by, payloads[hit.segment_id]["captured_at"],
                payloads[hit.segment_id].get("dataset"), payloads[hit.segment_id].get("footage"),
            )
            for hit in fuse([int(h.id) for h in lists[0]], [int(h.id) for h in lists[1]], w_f, w_c, depth)
        ]
    else:
        ranked = [
            RankedHit(
                int(hit.id), hit.score, mode.value, hit.payload["captured_at"],
                hit.payload.get("dataset"), hit.payload.get("footage"),
            )
            for hit in lists[0]
        ]
    ranked = _per_footage(ranked, per_footage, k)
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
            dataset=hit.dataset,
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


@router.get("/boxes", response_model=dict[int, list[SearchBoxOut]])
def search_boxes(
    q: str = Query(..., max_length=1000),
    segment_ids: list[int] = Query(..., max_length=MAX_K),
    db: Session = Depends(get_db),
    _user: User = Depends(require_role(Role.OPERATOR, Role.ANALYST, Role.ADMIN)),
) -> dict[int, list[SearchBoxOut]]:
    """OMNI-X02 (D-42): where the searched thing is in each result's frame. Called by the screen
    after `GET /search` has answered, so search itself is unchanged (NFR-2). Every id asked for
    gets a list; it is empty when no box was found, the frame is not an admitted stored frame,
    or ai_workers cannot answer. Never an error for those."""
    text = q.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=EMPTY_QUERY)
    ids = list(dict.fromkeys(segment_ids))
    out: dict[int, list[SearchBoxOut]] = {segment_id: [] for segment_id in ids}
    paths = dict(
        db.execute(
            select(Segment.id, Segment.frame_path).where(
                Segment.id.in_(ids), Segment.admitted.is_(True), Segment.frame_path.is_not(None)
            )
        ).all()
    )
    if not paths:
        return out
    order = [segment_id for segment_id in ids if segment_id in paths]
    started = time.perf_counter()
    try:
        found = ai_workers_client.detect_boxes([paths[i] for i in order], prompts_for(text))
    except ai_workers_client.AiWorkersUnavailableError as exc:
        logger.warning("search boxes: detector unreachable", extra={"extra_fields": {"error": str(exc)[:300]}})
        return out
    for segment_id, boxes in zip(order, found, strict=True):
        out[segment_id] = [SearchBoxOut(**box) for box in boxes]
    logger.info(
        "search boxes",
        extra={"extra_fields": {"frames": len(order), "boxes": sum(map(len, found)), "elapsed_ms": _ms(started)}},
    )
    return out
