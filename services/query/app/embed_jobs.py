"""Embed jobs from stored segments (OMNI-705), for the consumer, the backfill and the status.

A job carries the frame's whole payload (`FramePayload` minus the model), so ai_workers
needs no database: everything it stores next to the vector comes from here.

The domain is not on a segment. It is taken from, in order: the frame's camera (a live
frame), the video's camera, the dataset the video was loaded from (`dataset_manifest`),
and otherwise `surveillance` (D-34): a plain upload with no camera has no domain recorded.
"""

from collections.abc import Iterable, Iterator

import pika
from omnisight_common import Domain
from omnisight_common.embed_queue import EmbedJob, declare_embed_queue
from omnisight_common.frame_vectors import captured_at
from omnisight_common.segment_queue import PERSISTENT
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, aliased

from app.models import Camera, DatasetManifest, Segment, Video

UNKNOWN_DOMAIN = Domain.SURVEILLANCE


def _jobs_query() -> Select:
    """Every admitted frame with a stored file, with what its payload needs."""
    frame_camera = aliased(Camera)
    video_camera = aliased(Camera)
    manifest_domain = (
        select(DatasetManifest.domain)
        .where(DatasetManifest.video_id == Segment.video_id)
        .limit(1)
        .scalar_subquery()
    )
    return (
        select(
            Segment.id,
            Segment.video_id,
            Segment.camera_id,
            Segment.source_type,
            Segment.timestamp_s,
            Segment.frame_path,
            Segment.thumb_path,
            Video.created_at.label("uploaded_at"),
            func.coalesce(frame_camera.domain, video_camera.domain, manifest_domain).label("domain"),
        )
        .outerjoin(Video, Video.id == Segment.video_id)
        .outerjoin(frame_camera, frame_camera.id == Segment.camera_id)
        .outerjoin(video_camera, video_camera.id == Video.camera_id)
        .where(Segment.admitted.is_(True), Segment.frame_path.is_not(None))
    )


def _job(row) -> EmbedJob:
    return EmbedJob(
        segment_id=row.id,
        video_id=row.video_id,
        camera_id=row.camera_id,
        source_type=row.source_type,
        domain=row.domain or UNKNOWN_DOMAIN,
        timestamp_s=row.timestamp_s,
        captured_at=captured_at(row.source_type, row.timestamp_s, row.uploaded_at),
        frame_path=row.frame_path,
        thumb_path=row.thumb_path,
    )


def job_for_frame(db: Session, *, video_id: int | None, camera_id: int | None,
                  frame_index: int, timestamp_s: float) -> EmbedJob | None:
    """The job for one stored segment, found by the key the consumer stores it under
    (a video's frame index, or a live camera's moment). None if it is not an admitted
    frame with a file, or not stored."""
    query = _jobs_query()
    if video_id is not None:
        query = query.where(Segment.video_id == video_id, Segment.frame_index == frame_index)
    else:
        query = query.where(
            Segment.video_id.is_(None), Segment.camera_id == camera_id, Segment.timestamp_s == timestamp_s
        )
    row = db.execute(query).one_or_none()
    return None if row is None else _job(row)


def jobs_missing_from(db: Session, embedded: set[int]) -> Iterator[EmbedJob]:
    """A job for every admitted frame whose id is not in `embedded` (the backfill)."""
    for row in db.execute(_jobs_query().order_by(Segment.id)).yield_per(1000):
        if row.id not in embedded:
            yield _job(row)


def jobs_for_segments(db: Session, segment_ids: list[int]) -> dict[int, EmbedJob]:
    """The jobs of these segments, by id: the payload of a vector made elsewhere (OMNI-710).
    A segment that is not an admitted frame with a file has none."""
    rows = db.execute(_jobs_query().where(Segment.id.in_(segment_ids)))
    return {row.id: _job(row) for row in rows}


def publish_jobs(channel, queue: str, jobs: Iterable[EmbedJob]) -> int:
    """Persistent and, on a channel in confirm mode, confirmed one by one, like a segment
    (OMNI-311). Raises on any failure: a job neither queued nor reported is a frame that
    silently never gets a vector."""
    declare_embed_queue(channel, queue)
    published = 0
    for job in jobs:
        channel.basic_publish(
            exchange="",
            routing_key=queue,
            body=job.model_dump_json().encode(),
            properties=pika.BasicProperties(delivery_mode=PERSISTENT, content_type="application/json"),
            mandatory=True,
        )
        published += 1
    return published
