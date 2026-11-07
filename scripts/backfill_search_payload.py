"""Set the Search page's payload fields on points stored before them, in `frame_vectors` and `clip_vectors`.

- **`dataset`** (D-43): a dataset clip is stored as an upload; only `dataset_manifest.video_id` in Postgres says
  which dataset it came from. The page's `source` filter runs inside Qdrant, so each point needs that name: the
  dataset's name for a dataset clip, nothing for a plain upload or a camera frame
- **`footage`** (D-44): `video:{id}` or `camera:{id}`, the key the page's results are grouped on

New points get both when they are written (`FramePayload`, `app/embed_jobs.py`); this sets them on the ones already
there. Only these fields are set (Qdrant's `set_payload`); vectors and every other field are left as they are. A point
that already holds the right values is not touched, so a second run changes none. qdrant-client drops `None` values
from a payload it sends, so Qdrant never stores a null: "no dataset" is a missing key, and a missing key is already
right for a plain upload or a camera frame (the filter's `IsEmpty` reads it as empty). It also asks for the
collections' payload indexes.

Reports, per collection, the points read and the points changed. Qdrant has no host port, so it runs inside `query`;
on the host:

    docker compose up -d
    uv run python scripts/backfill_search_payload.py
"""

import subprocess
import sys
from pathlib import Path

SCROLL = 10_000


def wanted(payload: dict, dataset_of: dict[int, str]) -> dict:
    """The fields this point should hold. A missing `video_id` or `camera_id` is null (see above)."""
    video_id = payload.get("video_id")
    if video_id is not None:
        return {"dataset": dataset_of.get(int(video_id)), "footage": f"video:{int(video_id)}"}
    return {"dataset": None, "footage": f"camera:{payload.get('camera_id')}"}


def changes(points: list[tuple[int, dict]], dataset_of: dict[int, str]) -> dict[tuple, list[int]]:
    """Which points need which values, grouped by the values: {((field, value), ...): [point ids]}.

    `points` are (id, payload with `video_id`, `camera_id` and maybe `dataset`, `footage`). A missing key counts
    as null.
    """
    todo: dict[tuple, list[int]] = {}
    for point_id, payload in points:
        want = wanted(payload, dataset_of)
        if any(payload.get(field) != value for field, value in want.items()):
            todo.setdefault(tuple(sorted(want.items())), []).append(point_id)
    return todo


def apply(values: dict) -> tuple[dict, list[str]]:
    """(fields to set, keys to delete): a null is a deleted key, since a null sent is dropped."""
    return {k: v for k, v in values.items() if v is not None}, [k for k, v in values.items() if v is None]


def applied(payload: dict, values: dict) -> dict:
    """The payload after `apply(values)`: what Qdrant holds after the backfill."""
    to_set, to_delete = apply(values)
    return {k: v for k, v in {**payload, **to_set}.items() if k not in to_delete}


# --- inside query ---------------------------------------------------------------------------


def _backfill() -> int:
    sys.path.insert(0, "/workspace/services/query")
    from app.db import SessionLocal
    from app.models import DatasetManifest
    from app.settings import settings
    from omnisight_common.clip_vectors import CLIP_VECTOR_SIZE
    from omnisight_common.frame_vectors import (
        FRAME_VECTOR_SIZE,
        ensure_collection,
        qdrant_client,
    )
    from sqlalchemy import select

    with SessionLocal() as db:
        rows = db.execute(
            select(DatasetManifest.video_id, DatasetManifest.dataset).where(DatasetManifest.video_id.is_not(None))
        )
        dataset_of = {int(video_id): dataset for video_id, dataset in rows}
    print(f"dataset videos in the manifest: {len(dataset_of)}")

    client = qdrant_client(settings)
    for name, size in ((settings.frame_collection, FRAME_VECTOR_SIZE), (settings.clip_collection, CLIP_VECTOR_SIZE)):
        ensure_collection(client, name, size)
        points: list[tuple[int, dict]] = []
        offset = None
        while True:
            batch, offset = client.scroll(
                collection_name=name, limit=SCROLL, offset=offset,
                with_payload=["video_id", "camera_id", "dataset", "footage"], with_vectors=False,
            )
            points.extend((int(p.id), p.payload or {}) for p in batch)
            if offset is None:
                break
        todo = changes(points, dataset_of)
        for values, ids in todo.items():
            to_set, to_delete = apply(dict(values))
            for start in range(0, len(ids), SCROLL):
                chunk = ids[start : start + SCROLL]
                client.set_payload(name, payload=to_set, points=chunk, wait=True)
                if to_delete:
                    client.delete_payload(name, keys=to_delete, points=chunk, wait=True)
        changed = sum(len(ids) for ids in todo.values())
        print(f"{name}: read {len(points)}, changed {changed}")
    client.close()
    return 0


# --- on the host ----------------------------------------------------------------------------


def main() -> int:
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "query", "uv", "run", "--package", "omnisight-query", "python", "-", "--inside"],
        input=Path(__file__).read_bytes(), check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(_backfill() if sys.argv[1:] == ["--inside"] else main())
