"""TC-4 on the VIRAT archive (OMNI-715): latency and recall@5 of the SM-1 queries, measured together.

Phase A: both collections pre-loaded with at least 100,000 embeddings, natural-language queries over scenes
and actions, latency and recall@5 measured together. D-37 revised the size: every admitted frame of the 275
VIRAT evaluation videos (OMNI-708, 35,704 frames), no distractors. The pass rule stays: fused recall@5 at
least 85% and every query under 3 s.

What runs: the archive's frame and clip vectors are loaded into scratch collections `frame_vectors_tc4` and
`clip_vectors_tc4` of the local Qdrant (point id = the frame's row in the archive, the payload the product's
`FramePayload`). Each of the 50 queries of `datasets/eval/sm1_queries.csv` then goes through the product's own
search code: the text from `ai_workers` (`search._text_vector`), both HNSW searches with the product's filter,
`tuned_weights` and `fuse`, as `app/search.py` does them. Only the Postgres join is left out: archive frames
have no `segments` row. Three modes (frame, clip, fused), 3 rounds. Recall@5 is judged by the same answer rules
as SM-1 (`scripts/measure_sm1.py`). The scratch collections are dropped afterwards.

Qdrant has no host port, so the measuring runs inside `query`; this script, run on the host, builds the labels,
copies the archive in, pipes itself in and removes the copies. From the repo root, with the stack up and
Google Drive for desktop running (`G:`):

    docker compose up -d
    uv run python scripts/measure_tc4.py --out <file.json>

`--keep` leaves the scratch collections in place. Latency is this laptop's: the text encode is the CPU's
(D-31 judges the GPU's text encode separately, see NFR-2).
"""

import argparse
import csv
import json
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DRIVE = Path("G:/My Drive/omnisight/embeddings/virat")
INSIDE = "/tmp/omni715"
FRAME_SCRATCH, CLIP_SCRATCH = "frame_vectors_tc4", "clip_vectors_tc4"
K = 5
TARGET = 0.85
LIMIT_S = 3.0
ROUNDS = 3
BATCH = 500
MODES = ("frame", "clip", "fused")


def percentile(values: list[float], q: float) -> float:
    """Nearest rank: the smallest value with at least q of the values at or below it."""
    ordered = sorted(values)
    return ordered[max(0, int(np.ceil(q * len(ordered))) - 1)]


def latency_stats(values: list[float]) -> dict:
    return {"n": len(values), "p50": percentile(values, 0.5), "p95": percentile(values, 0.95), "max": max(values)}


def recall(found: list[bool]) -> float:
    return sum(found) / len(found)


def verdict(fused_recall: float, slowest_s: float) -> bool:
    return fused_recall >= TARGET and slowest_s < LIMIT_S


# --- inside query ---------------------------------------------------------------------------


def _load(folder: Path) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray, dict]:
    labels = np.load(folder / "labels.npz")
    keys = labels["keys"].tolist()
    frames, clips, indexes, times = [], [], [], []
    for key in keys:
        with np.load(folder / "virat" / f"{key}.npz") as data:
            frames.append(data["frame_vectors"])
            clips.append(data["clip_vectors"])
            indexes.append(data["frame_index"])
            times.append(data["timestamp_s"])
    frame_index = np.concatenate(indexes)
    if not np.array_equal(frame_index, labels["frame_index"]):
        raise RuntimeError("the archive's frames are not the ones the labels were made for")
    correct = {name[len("rule:") :]: labels[name] for name in labels.files if name.startswith("rule:")}
    return keys, np.concatenate(frames), np.concatenate(clips), np.concatenate(times), correct


def _fill(client, name: str, vectors: np.ndarray, times: np.ndarray, model: str, revision: str) -> None:
    from datetime import UTC, datetime, timedelta

    from omnisight_common.domain import Domain
    from omnisight_common.frame_vectors import FramePayload, ensure_collection
    from omnisight_common.segment_source_type import SegmentSourceType
    from qdrant_client import models

    if client.collection_exists(name):
        client.delete_collection(name)
    ensure_collection(client, name, vectors.shape[1])
    origin = datetime(2000, 1, 1, tzinfo=UTC)
    for start in range(0, len(vectors), BATCH):
        points = []
        for row in range(start, min(start + BATCH, len(vectors))):
            payload = FramePayload(
                segment_id=row, video_id=None, camera_id=None, source_type=SegmentSourceType.UPLOAD,
                domain=Domain.SURVEILLANCE, timestamp_s=float(times[row]),
                captured_at=(origin + timedelta(seconds=row)).isoformat().replace("+00:00", "Z"),
                frame_path="", thumb_path=None, model=model, model_revision=revision,
            )
            points.append(models.PointStruct(id=row, vector=vectors[row].tolist(), payload=payload.model_dump(mode="json")))
        client.upsert(name, points, wait=True)
    print(f"{name}: {client.count(name, exact=True).count} points", file=sys.stderr)


def _query_once(text: str, mode: str, client, search) -> dict:
    """What `app/search.py` does for one request, up to the join."""
    from omnisight_common.fusion import fuse

    streams = {"frame": [search.FRAME], "clip": [search.CLIP], "fused": [search.FRAME, search.CLIP]}[mode]
    started = time.perf_counter()
    encoded = [search._text_vector(text, stream) for stream in streams]
    encode_s = time.perf_counter() - started

    step = time.perf_counter()
    lists = [
        client.query_points(
            collection_name=stream.collection, query=vector,
            query_filter=search._filter(stream, None, None, None, None), limit=K, with_payload=["captured_at"],
        ).points
        for stream, (vector, _) in zip(streams, encoded, strict=True)
    ]
    search_s = time.perf_counter() - step

    step = time.perf_counter()
    if mode == "fused":
        w_f, w_c = search._weights(encoded[0][0])
        rows = [hit.segment_id for hit in fuse([int(h.id) for h in lists[0]], [int(h.id) for h in lists[1]], w_f, w_c, K)]
    else:
        rows = [int(hit.id) for hit in lists[0]]
    fusion_s = time.perf_counter() - step
    return {
        "rows": rows, "encode_s": encode_s, "search_s": search_s, "fusion_s": fusion_s,
        "total_s": time.perf_counter() - started, "encode_cached": all(cached for _, cached in encoded),
    }


def _measure() -> int:
    sys.path.insert(0, "/workspace/services/query")
    from app import search
    from app.settings import settings
    from omnisight_common.frame_vectors import qdrant_client

    folder = Path(INSIDE)
    keys, frame_vectors, clip_vectors, times, correct = _load(folder)
    queries = list(csv.DictReader(open(folder / "sm1_queries.csv", newline="", encoding="utf-8")))
    client = qdrant_client(settings)
    search.FRAME = replace(search.FRAME, collection=FRAME_SCRATCH)
    search.CLIP = replace(search.CLIP, collection=CLIP_SCRATCH)
    try:
        load_started = time.perf_counter()
        _fill(client, FRAME_SCRATCH, frame_vectors, times, search.FRAME.model, search.FRAME.model_revision)
        _fill(client, CLIP_SCRATCH, clip_vectors, times, search.CLIP.model, search.CLIP.model_revision)
        load_s = time.perf_counter() - load_started

        rows = []
        for number, query in enumerate(queries, 1):
            mask = correct[query["answer_rule"]]
            entry = {"query_id": query["query_id"], "text": query["text"], "kind": query["kind"], "answer_rule": query["answer_rule"], "modes": {}}
            for mode in MODES:
                runs = [_query_once(query["text"], mode, client, search) for _ in range(ROUNDS)]
                first = runs[0]["rows"]
                entry["modes"][mode] = {
                    "found": bool(mask[first].any()),
                    "hits": first,
                    "same_hits_every_round": all(run["rows"] == first for run in runs),
                    "runs": [{key: run[key] for key in ("encode_s", "search_s", "fusion_s", "total_s", "encode_cached")} for run in runs],
                }
            rows.append(entry)
            print(f"{number}/{len(queries)} {query['query_id']}", file=sys.stderr)
        collection_counts = {name: client.count(name, exact=True).count for name in (FRAME_SCRATCH, CLIP_SCRATCH)}
    finally:
        if "--keep" not in sys.argv:
            for name in (FRAME_SCRATCH, CLIP_SCRATCH):
                if client.collection_exists(name):
                    client.delete_collection(name)
        client.close()
    print(json.dumps({
        "videos": len(keys), "frames": len(frame_vectors), "points": collection_counts, "load_s": load_s,
        "dropped_afterwards": "--keep" not in sys.argv, "queries": rows,
    }))
    return 0


# --- on the host ----------------------------------------------------------------------------


def _compose(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *args], **kwargs)


def _labels(path: Path) -> list[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import measure_sm1

    with open(ROOT / "datasets" / "splits" / "virat.csv", newline="") as f:
        keys = [row["clip_key"] for row in csv.DictReader(f) if row["split"] == "evaluation"]
    queries = measure_sm1.read_queries()
    archive = measure_sm1.load_archive(keys, DRIVE, ROOT / "data" / "virat", {q["answer_rule"] for q in queries}, vectors=False)
    np.savez(path, keys=np.array(keys), frame_index=archive.frame_index, **{f"rule:{rule}": mask for rule, mask in archive.correct.items()})
    return keys


def _summary(report: dict) -> dict:
    rows = report["queries"]
    out: dict = {"frames": report["frames"], "videos": report["videos"], "points": report["points"], "n_queries": len(rows), "modes": {}}
    for mode in MODES:
        modes = [row["modes"][mode] for row in rows]
        runs = [run for m in modes for run in m["runs"]]
        out["modes"][mode] = {
            "recall_at_5": recall([m["found"] for m in modes]),
            "recall_scene": recall([row["modes"][mode]["found"] for row in rows if row["kind"] == "scene"]),
            "recall_action": recall([row["modes"][mode]["found"] for row in rows if row["kind"] == "action"]),
            "total_s": latency_stats([run["total_s"] for run in runs]),
            "uncached_total_s": latency_stats([run["total_s"] for run in runs if not run["encode_cached"]] or [0.0]),
            "search_and_fusion_s": latency_stats([run["search_s"] + run["fusion_s"] for run in runs]),
            "unstable_queries": sum(not m["same_hits_every_round"] for m in modes),
        }
    fused = out["modes"]["fused"]
    out["slowest_s"] = max(run["total_s"] for row in rows for mode in MODES for run in row["modes"][mode]["runs"])
    out["passed"] = verdict(fused["recall_at_5"], out["slowest_s"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    if not (DRIVE / "manifest.json").exists():
        sys.exit(f"no archive in {DRIVE}: is Google Drive for desktop running?")
    labels = args.out.with_suffix(".labels.npz")
    keys = _labels(labels)
    print(f"labels for {len(keys)} videos", file=sys.stderr)
    _compose("exec", "-T", "query", "mkdir", "-p", INSIDE, check=True)
    try:
        for source, target in [(labels, "labels.npz"), (ROOT / "datasets" / "eval" / "sm1_queries.csv", "sm1_queries.csv")]:
            _compose("cp", str(source), f"query:{INSIDE}/{target}", check=True, capture_output=True)
        _compose("cp", str(DRIVE), f"query:{INSIDE}/", check=True, capture_output=True)
        with open(args.out, "wb") as out:
            done = _compose(
                "exec", "-T", "query", "uv", "run", "--package", "omnisight-query", "python", "-", "--inside",
                *(["--keep"] if args.keep else []), input=Path(__file__).read_bytes(), stdout=out, check=False,
            )
    finally:
        _compose("exec", "-T", "query", "rm", "-rf", INSIDE, check=False)
        labels.unlink(missing_ok=True)
    if done.returncode:
        return done.returncode
    summary = _summary(json.loads(args.out.read_text()))
    args.out.with_suffix(".summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(_measure() if "--inside" in sys.argv else main())
