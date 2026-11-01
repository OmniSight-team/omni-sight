"""Export the product's VIRAT segments for the archive match (OMNI-708, step 6).

Colab has no product database, so the archive is keyed by VIRAT's own names. This writes
what the match needs, one entry per admitted segment of the product's VIRAT videos: segment
id, video id, `clip_key`, `frame_index`, `timestamp_s`, `admission_reason`, and the laptop's
own SigLIP 2 vector of the frame where `frame_vectors` has one (OMNI-705), for the agreement
check. Each video also lists the gate settings it was extracted with (`gate_*`, set only
after a re-gate, OMNI-306), so a difference from the archive's gate shows.

Qdrant has no host port, so the reading runs inside `query`; this script, run on the host,
pipes itself in and writes the file:

    docker compose up -d
    uv run python scripts/export_segments_for_colab.py "G:/My Drive/omnisight/embeddings/product/segments.json"

Then the notebook's match cell (`encode_virat_archive.match_product`) reads it.
"""

import json
import subprocess
import sys
from pathlib import Path

# --- inside query ---------------------------------------------------------------------------


def _export() -> dict:
    from app.db import SessionLocal
    from app.models import DatasetManifest, Segment, Video
    from app.settings import settings
    from omnisight_common.frame_vectors import qdrant_client
    from qdrant_client import models
    from sqlalchemy import select

    with SessionLocal() as db:
        videos = db.execute(
            select(Video.id, DatasetManifest.clip_key, Video.fps, Video.gate_stride_s, Video.gate_grid_size,
                   Video.gate_cell_threshold, Video.gate_min_active_cells)
            .join(DatasetManifest, DatasetManifest.video_id == Video.id)
            .where(DatasetManifest.dataset == "virat")
            .order_by(Video.id)
        ).all()
        key_of = {v.id: v.clip_key for v in videos}
        rows = db.execute(
            select(Segment.id, Segment.video_id, Segment.frame_index, Segment.timestamp_s, Segment.admission_reason)
            .where(Segment.video_id.in_(key_of), Segment.admitted.is_(True))
            .order_by(Segment.video_id, Segment.frame_index)
        ).all()

    qdrant = qdrant_client(settings)
    same_model = models.Filter(must=[
        models.FieldCondition(key="model", match=models.MatchValue(value=settings.frame_model_id)),
        models.FieldCondition(key="model_revision", match=models.MatchValue(value=settings.frame_model_revision)),
    ])
    laptop: dict[int, list[float]] = {}
    ids = [r.id for r in rows]
    for start in range(0, len(ids), 500):
        points, _ = qdrant.scroll(
            collection_name=settings.frame_collection,
            scroll_filter=models.Filter(must=[*same_model.must, models.HasIdCondition(has_id=ids[start:start + 500])]),
            limit=500,
            with_payload=False,
            with_vectors=True,
        )
        laptop.update({int(p.id): p.vector for p in points})
    qdrant.close()

    return {
        "frame_model": [settings.frame_model_id, settings.frame_model_revision],
        "videos": [
            {"video_id": v.id, "clip_key": v.clip_key, "fps": v.fps,
             "gate": {"stride_s": v.gate_stride_s, "grid_size": v.gate_grid_size,
                      "cell_threshold": v.gate_cell_threshold, "min_active_cells": v.gate_min_active_cells}}
            for v in videos
        ],
        "segments": [
            {"segment_id": r.id, "video_id": r.video_id, "clip_key": key_of[r.video_id], "frame_index": r.frame_index,
             "timestamp_s": r.timestamp_s, "admission_reason": r.admission_reason.value,
             "laptop_frame_vector": laptop.get(r.id)}
            for r in rows
        ],
    }


# --- on the host ----------------------------------------------------------------------------


def _in_query() -> bytes:
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "query", "uv", "run", "--package", "omnisight-query", "python", "-", "--inside"],
        input=Path(__file__).read_bytes(),
        capture_output=True,
        check=True,
    ).stdout


if __name__ == "__main__":
    if sys.argv[1:] == ["--inside"]:
        sys.path.insert(0, "/workspace/services/query")
        sys.stdout.write(json.dumps(_export()))
        sys.exit(0)
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = Path(sys.argv[1])
    data = json.loads(_in_query())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data))
    with_vector = sum(s["laptop_frame_vector"] is not None for s in data["segments"])
    print(f"{len(data['videos'])} VIRAT videos, {len(data['segments'])} admitted segments, {with_vector} with a laptop frame vector -> {out}")
    for v in data["videos"]:
        n = sum(s["video_id"] == v["video_id"] for s in data["segments"])
        print(f"  {v['video_id']} {v['clip_key']}: {n} segments, gate overrides {v['gate']}")
