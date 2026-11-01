"""Backfill and check frame vectors (OMNI-705).

Frames stored before the embed queue existed (the 60 hand-check clips, the 9 VIRAT videos)
have no job. `queue` publishes one for every admitted frame that has no point of the pinned
model in `frame_vectors`; ai_workers works through them (about 9 s a frame on this laptop's
CPU, D-31). `check` compares the two sides. Qdrant has no host port, so both stages run
inside `query`; this script, run on the host, pipes itself in:

    docker compose up -d
    uv run python scripts/backfill_embeddings.py queue [--only virat,ccd] [--video ID] [--force]
    uv run python scripts/backfill_embeddings.py check [--video ID]     # read-only

`--video ID` limits either stage to one video's frames: the proof of the durable path
(OMNI-705) runs on one video, not the archive.

Jobs are queued group by group, in this order: `virat` (the demo sample, searched first),
`ccd`, `other` (uploads not from a dataset), `live` (camera frames), `ucf_crime` (30,701
frames, about 77 h on this CPU). `--only` queues just the groups named, in that order.

`queue` refuses to run while the embed queue still holds jobs (a second backfill would
queue the same frames again: harmless, one point each, but hours of encoding twice), unless
given `--force`.

`check` prints, from Postgres and Qdrant at one moment: admitted frames with a file; how
many have a point of the pinned model and how many do not (per video and camera); points of
the model whose id is no admitted segment (K-24); every point counted once per id, so
"exactly one point per frame" holds when missing = 0 and the model's point count equals the
frames with a point plus the orphans; and the embed queue's depth and dead letters.
Exit 0 only when nothing is missing and nothing is waiting.
"""

import subprocess
import sys
from pathlib import Path

# --- inside query ---------------------------------------------------------------------------


def _setup():
    import pika
    from app.db import SessionLocal
    from app.settings import settings
    from omnisight_common import connection_parameters
    from omnisight_common.frame_vectors import embedded_segment_ids, qdrant_client

    qdrant = qdrant_client(settings)
    embedded = embedded_segment_ids(qdrant, settings.frame_collection, settings.frame_model_id, settings.frame_model_revision)
    connection = pika.BlockingConnection(connection_parameters(settings))
    return settings, SessionLocal, qdrant, embedded, connection


def _depth(channel, queue: str) -> tuple[int, int]:
    """(jobs ready, consumers). Jobs a consumer holds unacknowledged (at most one batch)
    are not in `ready`; AMQP does not report them."""
    from omnisight_common.embed_queue import declare_embed_queue

    declare_embed_queue(channel, queue)
    ok = channel.queue_declare(queue, passive=True).method
    return ok.message_count, ok.consumer_count


GROUPS = ("virat", "ccd", "other", "live", "ucf_crime")


def _grouped(db, jobs, only: tuple[str, ...]) -> list:
    """The jobs of the groups in `only`, group by group in GROUPS' order."""
    from app.models import DatasetManifest
    from sqlalchemy import select

    dataset_of = dict(db.execute(select(DatasetManifest.video_id, DatasetManifest.dataset).where(DatasetManifest.video_id.is_not(None))).all())

    def group(job) -> str:
        if job.video_id is None:
            return "live"
        return dataset_of.get(job.video_id, "other")

    by_group: dict[str, list] = {name: [] for name in GROUPS}
    for job in jobs:
        by_group.setdefault(group(job), []).append(job)
    for name in GROUPS:
        if name in only:
            print(f"  {name}: {len(by_group[name])} jobs")
    return [job for name in GROUPS if name in only for job in by_group[name]]


def _queue(force: bool, only: tuple[str, ...], video: int | None) -> int:
    from app.embed_jobs import jobs_missing_from, publish_jobs
    from omnisight_common.segment_queue import dead_letter_queue

    settings, SessionLocal, qdrant, embedded, connection = _setup()
    channel = connection.channel()
    channel.confirm_delivery()
    ready, consumers = _depth(channel, settings.embed_queue)
    if ready and not force:
        print(f"{settings.embed_queue} still holds {ready} jobs; not queueing again (use --force)")
        return 1
    with SessionLocal() as db:
        missing = (job for job in jobs_missing_from(db, embedded) if video is None or job.video_id == video)
        jobs = _grouped(db, missing, only)
    published = publish_jobs(channel, settings.embed_queue, jobs)
    ready, consumers = _depth(channel, settings.embed_queue)
    dead = channel.queue_declare(dead_letter_queue(settings.embed_queue), passive=True).method.message_count
    print(f"frames already with a point: {len(embedded)}")
    print(f"jobs published: {published}")
    print(f"{settings.embed_queue}: {ready} ready, {consumers} consumer(s); dead letters: {dead}")
    connection.close()
    qdrant.close()
    return 0


def _check(video: int | None) -> int:
    from collections import Counter

    from app.models import Segment
    from omnisight_common.segment_queue import dead_letter_queue
    from sqlalchemy import select

    settings, SessionLocal, qdrant, embedded, connection = _setup()
    with SessionLocal() as db:
        frames = db.execute(
            select(Segment.id, Segment.video_id, Segment.camera_id).where(
                Segment.admitted.is_(True), Segment.frame_path.is_not(None)
            )
        ).all()
    if video is not None:
        frames = [row for row in frames if row.video_id == video]
        print(f"video {video} only")
    admitted = {row.id for row in frames}
    missing = Counter((row.video_id, row.camera_id) for row in frames if row.id not in embedded)
    orphans = embedded - admitted
    if video is not None:
        # Points of other videos are not this video's orphans; count its own only.
        own = qdrant.count(
            settings.frame_collection,
            count_filter={"must": [
                {"key": "video_id", "match": {"value": video}},
                {"key": "model", "match": {"value": settings.frame_model_id}},
                {"key": "model_revision", "match": {"value": settings.frame_model_revision}},
            ]},
            exact=True,
        ).count
    model_points = own if video is not None else qdrant.count(
        settings.frame_collection,
        count_filter={"must": [
            {"key": "model", "match": {"value": settings.frame_model_id}},
            {"key": "model_revision", "match": {"value": settings.frame_model_revision}},
        ]},
        exact=True,
    ).count
    all_points = qdrant.count(settings.frame_collection, exact=True).count
    channel = connection.channel()
    ready, consumers = _depth(channel, settings.embed_queue)
    dead = channel.queue_declare(dead_letter_queue(settings.embed_queue), passive=True).method.message_count

    with_point = len(admitted & embedded)
    print(f"admitted frames with a file: {len(admitted)}")
    print(f"  with a point ({settings.frame_model_id}@{settings.frame_model_revision[:8]}): {with_point}")
    print(f"  missing: {sum(missing.values())}")
    for (video_id, camera_id), count in sorted(missing.items(), key=lambda kv: (kv[0][0] is None, kv[0][0] or 0, kv[0][1] or 0)):
        print(f"    video {video_id} camera {camera_id}: {count}")
    if video is not None:
        orphans = set()
    print(f"points of the model: {model_points} (= {with_point} frames + {len(orphans)} orphans: "
          f"{'yes' if model_points == with_point + len(orphans) else 'NO'})")
    print(f"points in {settings.frame_collection}, any model: {all_points}")
    print(f"{settings.embed_queue}: {ready} ready, {consumers} consumer(s); dead letters: {dead}")
    connection.close()
    qdrant.close()
    complete = not missing and ready == 0 and model_points == with_point + len(orphans)
    print("COMPLETE" if complete else "NOT COMPLETE")
    return 0 if complete else 1


# --- on the host ----------------------------------------------------------------------------


def _in_query(args: list[str]) -> int:
    source = Path(__file__).read_bytes()
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "query", "uv", "run", "--package", "omnisight-query", "python", "-", "--inside", *args],
        input=source,
    ).returncode


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["--inside"]:
        sys.path.insert(0, "/workspace/services/query")
        stage, force = args[1], "--force" in args
        only = GROUPS
        if "--only" in args:
            only = tuple(args[args.index("--only") + 1].split(","))
            unknown = set(only) - set(GROUPS)
            if unknown:
                sys.exit(f"unknown groups {sorted(unknown)}; known: {', '.join(GROUPS)}")
        video = int(args[args.index("--video") + 1]) if "--video" in args else None
        sys.exit(_queue(force, only, video) if stage == "queue" else _check(video))
    if not args or args[0] not in ("queue", "check"):
        sys.exit(__doc__)
    sys.exit(_in_query(args))
