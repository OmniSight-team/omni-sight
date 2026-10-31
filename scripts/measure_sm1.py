"""SM-1 on VIRAT (OMNI-713): recall@5 of `datasets/eval/sm1_queries.csv` over the VIRAT archive.

Phase A: the correct clip in the top 5 for at least 85% of queries, with a lift on action queries
over a frame-only baseline.

Run from `notebooks/sm1_gpu.ipynb` on Colab's GPU (D-26): the notebook clones the repo and imports
this file. Every query of the fixed set, over all of the archive's vectors (OMNI-708), compared
exactly, in four modes:

- `frame`: SigLIP 2 only, the baseline
- `clip`: InternVideo2 only
- `fused`: Algorithm 3 with the classifier's weights, `omnisight_common.fusion` as in the product,
  `K` = 5 both for each list and for the result (D-38)
- `fused_equal`: the same with weights 0.5 / 0.5, so the classifier's own effect shows

A query is found when any of its 5 hits meets its `answer_rule`: `event_type=N`, a frame inside an
annotated event of that type; `scene=NNNN`, a frame of that scene. `chance` is the recall@5 of five
frames drawn at random (OMNI-709). Nothing here chooses queries, weights or thresholds.

Pass: `fused` at least 85% overall, and `fused` above `frame` on action queries.

The labels, with no model and no search, from the repo root (they must give OMNI-709's 25.1%,
11.7% and 38.5%):

  uv run python scripts/measure_sm1.py --check-labels

Locally (correctness only, stand-in encoders): `uv run pytest scripts/tests/test_measure_sm1.py`.
"""

import argparse
import csv
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from omnisight_common.datasets import virat
from omnisight_common.fusion import ModalityClassifier, fuse

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "datasets" / "eval" / "sm1_queries.csv"
ARCHIVE = Path("G:/My Drive/omnisight/embeddings/virat")
K = 5
TARGET = 0.85
MODES = ("frame", "clip", "fused", "fused_equal")


@dataclass(frozen=True)
class Archive:
    clip_keys: np.ndarray
    frame_index: np.ndarray
    timestamp_s: np.ndarray
    # None with `vectors=False`: the labels need no vectors.
    frame_vectors: np.ndarray | None
    clip_vectors: np.ndarray | None
    # One boolean per frame, per answer rule.
    correct: dict[str, np.ndarray]

    def __len__(self) -> int:
        return len(self.frame_index)


def read_queries(path: Path = QUERIES) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def answer_mask(rule: str, clip_key: str, events: list[virat.Event], frame_index: np.ndarray) -> np.ndarray:
    """Which of one video's frames meet a rule. An event's frames include both ends, as in
    `virat_event_coverage.py`."""
    name, value = rule.split("=")
    if name == "scene":
        return np.full(len(frame_index), virat.scene_of(clip_key) == value)
    if name != "event_type":
        raise ValueError(f"unknown answer rule {rule}")
    mask = np.zeros(len(frame_index), bool)
    for event in events:
        if event.event_type == int(value):
            mask |= (frame_index >= event.start_frame) & (frame_index <= event.end_frame)
    return mask


def load_archive(keys: list[str], archive_dir: Path, dataset_dir: Path, rules: set[str], *, pins: dict | None = None, vectors: bool = True) -> Archive:
    """Every video of `keys`, in that order. Refuses an archive that is not whole, or that was
    made with other checkpoints than `pins`: a number from either would not be SM-1."""
    manifest = json.loads((archive_dir / "manifest.json").read_text())
    if pins is not None and manifest["pins"] != pins:
        raise RuntimeError(f"the archive was made with {manifest['pins']}, not {pins}")
    missing = [k for k in keys if k not in manifest["videos"]]
    if missing or manifest.get("failed"):
        raise RuntimeError(f"the archive is not whole: {len(missing)} videos missing, failed {manifest.get('failed')}")

    names, frames, times, frame_rows, clip_rows = [], [], [], [], []
    masks: dict[str, list[np.ndarray]] = {rule: [] for rule in rules}
    for key in keys:
        with np.load(archive_dir / f"{key}.npz") as data:
            frame_index = data["frame_index"]
            names.append(np.full(len(frame_index), key))
            frames.append(frame_index)
            times.append(data["timestamp_s"])
            if vectors:
                frame_rows.append(data["frame_vectors"])
                clip_rows.append(data["clip_vectors"])
        if len(frame_index) != manifest["videos"][key]["admitted"]:
            raise RuntimeError(f"{key}: the manifest says {manifest['videos'][key]['admitted']} frames, the file holds {len(frame_index)}")
        events = virat.read_events(dataset_dir, key)
        for rule in rules:
            masks[rule].append(answer_mask(rule, key, events, frame_index))

    correct = {rule: np.concatenate(parts) for rule, parts in masks.items()}
    empty = sorted(rule for rule, mask in correct.items() if not mask.any())
    if empty:
        raise RuntimeError(f"rules no frame of the archive meets: {empty}")
    return Archive(
        np.concatenate(names),
        np.concatenate(frames),
        np.concatenate(times),
        np.concatenate(frame_rows) if vectors else None,
        np.concatenate(clip_rows) if vectors else None,
        correct,
    )


def chance_at_5(correct: np.ndarray) -> float:
    return float(1 - (1 - correct.mean()) ** K)


def _exact_top(vectors: np.ndarray, query: np.ndarray) -> tuple[list[int], np.ndarray]:
    """Every vector compared, best first; equal scores by row, so a rerun gives the same list."""
    scores = vectors @ query
    return [int(row) for row in np.argsort(-scores, kind="stable")[:K]], scores


def _scored(archive: Archive, rule: str, rows: list[int], scores: list[float]) -> dict:
    mask = archive.correct[rule]
    hits = [
        {
            "clip_key": str(archive.clip_keys[row]),
            "frame_index": int(archive.frame_index[row]),
            "timestamp_s": float(archive.timestamp_s[row]),
            "score": float(score),
            "correct": bool(mask[row]),
        }
        for row, score in zip(rows, scores, strict=True)
    ]
    first = next((rank for rank, hit in enumerate(hits, 1) if hit["correct"]), None)
    return {"found": first is not None, "first_correct_rank": first, "hits": hits}


def measure_query(query: dict, frame_text: np.ndarray, clip_text: np.ndarray, archive: Archive, classifier: ModalityClassifier) -> dict:
    rule = query["answer_rule"]
    frame_rows, frame_scores = _exact_top(archive.frame_vectors, frame_text)
    clip_rows, clip_scores = _exact_top(archive.clip_vectors, clip_text)
    w_f, w_c = classifier.weights(frame_text.tolist())
    fused = fuse(frame_rows, clip_rows, w_f, w_c, K)
    equal = fuse(frame_rows, clip_rows, 0.5, 0.5, K)
    return {
        "query_id": query["query_id"],
        "text": query["text"],
        "kind": query["kind"],
        "answer_rule": rule,
        "w_f": w_f,
        "w_c": w_c,
        "frames_correct": int(archive.correct[rule].sum()),
        "chance": chance_at_5(archive.correct[rule]),
        "modes": {
            "frame": _scored(archive, rule, frame_rows, [frame_scores[r] for r in frame_rows]),
            "clip": _scored(archive, rule, clip_rows, [clip_scores[r] for r in clip_rows]),
            "fused": _scored(archive, rule, [h.segment_id for h in fused], [h.score for h in fused]),
            "fused_equal": _scored(archive, rule, [h.segment_id for h in equal], [h.score for h in equal]),
        },
    }


def _recalls(rows: list[dict]) -> dict:
    recalls = {mode: sum(row["modes"][mode]["found"] for row in rows) / len(rows) for mode in MODES}
    return {**recalls, "chance": sum(row["chance"] for row in rows) / len(rows), "n_queries": len(rows)}


def summarise(rows: list[dict]) -> dict:
    overall = _recalls(rows)
    by_kind = {kind: _recalls([row for row in rows if row["kind"] == kind]) for kind in ("scene", "action")}
    lift = by_kind["action"]["fused"] - by_kind["action"]["frame"]
    return {
        "recall_at_5": overall["fused"],
        "baseline": overall["frame"],
        "n_queries": len(rows),
        "overall": overall,
        "by_kind": by_kind,
        "action_lift": lift,
        "target": TARGET,
        "passed": overall["fused"] >= TARGET and lift > 0,
    }


def measure(queries: list[dict], archive: Archive, frame_encoder, clip_encoder, classifier: ModalityClassifier) -> dict:
    """Every query, in every mode. `measured_at` and the run's conditions go in beside it."""
    texts = [query["text"] for query in queries]
    frame_text, clip_text = frame_encoder.encode_texts(texts), clip_encoder.encode_texts(texts)
    rows = [measure_query(q, f, c, archive, classifier) for q, f, c in zip(queries, frame_text, clip_text, strict=True)]
    return {
        **summarise(rows),
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "frames": len(archive),
        "videos": len(set(archive.clip_keys.tolist())),
        "queries": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-labels", action="store_true", required=True)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--annotations", type=Path, default=ROOT / "data" / "virat")
    args = parser.parse_args()

    with open(ROOT / "datasets" / "splits" / "virat.csv", newline="") as f:
        keys = [row["clip_key"] for row in csv.DictReader(f) if row["split"] == "evaluation"]
    queries = read_queries()
    archive = load_archive(keys, args.archive, args.annotations, {q["answer_rule"] for q in queries}, vectors=False)
    chance = {q["query_id"]: chance_at_5(archive.correct[q["answer_rule"]]) for q in queries}
    print(f"{len(keys)} videos, {len(archive)} frames, {len(queries)} queries")
    print("rule            frames")
    for rule, mask in sorted(archive.correct.items()):
        print(f"{rule:14s}  {int(mask.sum()):6d}")
    for kind in ("scene", "action"):
        values = [chance[q["query_id"]] for q in queries if q["kind"] == kind]
        print(f"chance recall@5, {kind}: {sum(values) / len(values):.1%}")
    print(f"chance recall@5, all: {sum(chance.values()) / len(chance):.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
