"""Import the product's clip vectors from Drive into `clip_vectors` (OMNI-710).

`embeddings/product/{video_id}.npz` holds, by segment id, the clip vectors OMNI-708 made on
Colab for the product's VIRAT videos. Each is upserted by segment id with the same payload as
its frame, so a rerun changes nothing. Refused if the archive was made with another clip model
than the pinned one, or if a vector is not a unit vector of the right size. A segment id with
no admitted frame in Postgres is reported and not stored.

Reports, per video, the file's rows, the admitted segments and the points of the pinned model;
exits non-zero unless all three agree.

Qdrant has no host port, so the import runs inside `query`; this script, run on the host, copies
the files in, pipes itself in and removes the copies:

    docker compose up -d
    uv run python scripts/import_clip_vectors.py
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

DRIVE = Path("G:/My Drive/omnisight/embeddings")
INSIDE = "/tmp/omni710"
BATCH = 100
UNIT_TOLERANCE = 1e-3


def check_vectors(video: str, ids: np.ndarray, vectors: np.ndarray, size: int) -> None:
    if vectors.ndim != 2 or vectors.shape != (len(ids), size):
        raise ValueError(f"{video}: {len(ids)} ids and vectors of shape {vectors.shape}, expected size {size}")
    if len(set(ids.tolist())) != len(ids):
        raise ValueError(f"{video}: a segment id appears twice")
    if not np.isfinite(vectors).all():
        raise ValueError(f"{video}: a vector is not finite")
    norms = np.linalg.norm(vectors, axis=1)
    if len(norms) and np.abs(norms - 1).max() > UNIT_TOLERANCE:
        raise ValueError(f"{video}: a vector is not unit length (norm {norms.min()} to {norms.max()})")


def check_pins(pins: dict, model: str, revision: str) -> None:
    if (pins["clip_model_id"], pins["clip_model_revision"]) != (model, revision):
        raise ValueError(f"the archive was made with {pins['clip_model_id']}@{pins['clip_model_revision']}, not {model}@{revision}")


def upsert_vectors(client, collection: str, ids: np.ndarray, vectors: np.ndarray, jobs: dict, model: str, revision: str) -> list[int]:
    """Upsert every vector whose segment has a job; returns the ids that have none."""
    from omnisight_common.clip_vectors import clip_point

    unknown = [int(i) for i in ids if int(i) not in jobs]
    points = [
        clip_point(jobs[int(i)].payload(model, revision), vector.tolist())
        for i, vector in zip(ids, vectors, strict=True)
        if int(i) in jobs
    ]
    for start in range(0, len(points), BATCH):
        client.upsert(collection, points[start : start + BATCH], wait=True)
    return unknown


# --- inside query ---------------------------------------------------------------------------


def _import() -> int:
    sys.path.insert(0, "/workspace/services/query")
    from app.db import SessionLocal
    from app.embed_jobs import jobs_for_segments
    from app.models import Segment
    from app.settings import settings
    from omnisight_common.clip_vectors import CLIP_VECTOR_SIZE, ensure_clip_collection
    from omnisight_common.frame_vectors import embedded_segment_ids, qdrant_client
    from sqlalchemy import func, select

    folder = Path(INSIDE)
    model, revision = settings.clip_model_id, settings.clip_model_revision
    check_pins(json.loads((folder / "manifest.json").read_text())["pins"], model, revision)
    client = qdrant_client(settings)
    ensure_clip_collection(client, settings.clip_collection)

    ok = True
    files = sorted(folder.glob("*.npz"), key=lambda p: int(p.stem))
    with SessionLocal() as db:
        for path in files:
            with np.load(path) as data:
                ids, vectors = data["segment_id"], data["clip_vectors"]
            check_vectors(path.name, ids, vectors, CLIP_VECTOR_SIZE)
            jobs = jobs_for_segments(db, [int(i) for i in ids])
            unknown = upsert_vectors(client, settings.clip_collection, ids, vectors, jobs, model, revision)
            if unknown:
                ok = False
                print(f"{path.stem}: {len(unknown)} ids with no admitted frame, first {unknown[:5]}")
        points = embedded_segment_ids(client, settings.clip_collection, model, revision)
        total_rows = total_admitted = total_points = 0
        for path in files:
            video_id = int(path.stem)
            with np.load(path) as data:
                rows = len(data["segment_id"])
            admitted = set(db.scalars(
                select(Segment.id).where(Segment.video_id == video_id, Segment.admitted.is_(True), Segment.frame_path.is_not(None))
            ))
            stored = len(admitted & points)
            print(f"{video_id}: file {rows}, admitted {len(admitted)}, points {stored}")
            ok &= rows == len(admitted) == stored
            total_rows, total_admitted, total_points = total_rows + rows, total_admitted + len(admitted), total_points + stored
        admitted_elsewhere = db.scalar(
            select(func.count()).select_from(Segment).where(Segment.admitted.is_(True), Segment.frame_path.is_not(None))
        ) - total_admitted
    print(f"total: file {total_rows}, admitted {total_admitted}, points {total_points}")
    print(f"collection holds {client.count(settings.clip_collection, exact=True).count} points")
    print(f"admitted segments of other videos and cameras, not imported: {admitted_elsewhere}")
    client.close()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


# --- on the host ----------------------------------------------------------------------------


def _compose(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *args], **kwargs)


def main() -> int:
    files = sorted((DRIVE / "product").glob("*.npz"))
    if not files:
        sys.exit(f"no files in {DRIVE / 'product'}: is Google Drive for desktop running?")
    _compose("exec", "-T", "query", "mkdir", "-p", INSIDE, check=True)
    try:
        for path in [*files, DRIVE / "virat" / "manifest.json"]:
            _compose("cp", str(path), f"query:{INSIDE}/{path.name}", check=True, capture_output=True)
        return _compose(
            "exec", "-T", "query", "uv", "run", "--package", "omnisight-query", "python", "-", "--inside",
            input=Path(__file__).read_bytes(), check=False,
        ).returncode
    finally:
        _compose("exec", "-T", "query", "rm", "-rf", INSIDE, check=False)


if __name__ == "__main__":
    sys.exit(_import() if sys.argv[1:] == ["--inside"] else main())
