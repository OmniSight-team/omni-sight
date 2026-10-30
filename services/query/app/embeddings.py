"""How far encoding has got (OMNI-705): admitted frames in Postgres against their points in
Qdrant, per video and per camera.

`frames_embedded` and `clips_embedded` (OMNI-710) count the admitted frames whose segment id has a point made by the
pinned model, not the points carrying a video id: a point left behind by a deleted or
re-gated video's old segments (K-24) is not a frame of the video as it is now, and would
otherwise make a video look further along than it is.
"""

from collections import Counter
from collections.abc import Iterator
from contextlib import closing

from fastapi import APIRouter, Depends, HTTPException, status
from omnisight_common.frame_vectors import embedded_segment_ids, qdrant_client
from qdrant_client import QdrantClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Segment, User
from app.schemas import EmbeddingStatusOut
from app.settings import settings

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


def get_qdrant() -> Iterator[QdrantClient]:
    with closing(qdrant_client(settings)) as client:
        yield client


@router.get("/status", response_model=list[EmbeddingStatusOut])
def embeddings_status(
    db: Session = Depends(get_db),
    qdrant: QdrantClient = Depends(get_qdrant),
    _user: User = Depends(get_current_user),
) -> list[EmbeddingStatusOut]:
    """One row per video with admitted frames (its camera too, if it has one), then one per
    camera with live admitted frames (no video)."""
    try:
        embedded = embedded_segment_ids(
            qdrant, settings.frame_collection, settings.frame_model_id, settings.frame_model_revision
        )
        clips = embedded_segment_ids(
            qdrant, settings.clip_collection, settings.clip_model_id, settings.clip_model_revision
        )
    except Exception as exc:  # noqa: BLE001 - any Qdrant failure means the same to the caller
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="the vector store is unreachable") from exc

    total: Counter[tuple[int | None, int | None]] = Counter()
    done: Counter[tuple[int | None, int | None]] = Counter()
    clips_done: Counter[tuple[int | None, int | None]] = Counter()
    frames = db.execute(
        select(Segment.id, Segment.video_id, Segment.camera_id).where(
            Segment.admitted.is_(True), Segment.frame_path.is_not(None)
        )
    )
    for segment_id, video_id, camera_id in frames:
        key = (video_id, camera_id)
        total[key] += 1
        if segment_id in embedded:
            done[key] += 1
        if segment_id in clips:
            clips_done[key] += 1

    def order(key: tuple[int | None, int | None]) -> tuple:
        video_id, camera_id = key
        return (video_id is None, video_id or 0, camera_id or 0)

    return [
        EmbeddingStatusOut(
            video_id=video_id,
            camera_id=camera_id,
            frames_total=total[(video_id, camera_id)],
            frames_embedded=done[(video_id, camera_id)],
            clips_embedded=clips_done[(video_id, camera_id)],
            model=settings.frame_model_id,
        )
        for video_id, camera_id in sorted(total, key=order)
    ]
