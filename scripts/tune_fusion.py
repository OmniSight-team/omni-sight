"""Choose Algorithm 3's list depth and weights on the tuning set (D-40). Never reads SM-1's queries.

SM-1 (OMNI-713) showed the fused top 5 is always one list: the two lists of 5 hardly overlap, and with
`k0` 60 any weight above 0.516 takes all five places. So two things are tried here, on
`datasets/eval/sm1_dev_queries.csv` only:

- `depth`: how many candidates each list gives to the merge. The result stays 5
- the weights: C still decides whether a query is a scene or an action (`w_f` from its file at least
  0.5), and each kind gets a fixed `w_f` chosen here. `classifier` is C's own weights, as measured

`k0` stays B.3's 60. The archive, the labels and the exact search are `measure_sm1.py`'s. The winner is the
best overall recall on this set; among equals the better action recall, then the shallower list, then the
weights nearest 0.5. A choice among so many on 50 queries flatters itself: its number here is not a
result. The result is the one run on SM-1's own queries afterwards.

The text vectors come from ai_workers on the running stack, cached in `--vectors`, so this part runs
inside `query`; the rest reads Drive. Exploration on this laptop, from the repo root:

    docker compose up -d
    uv run python scripts/tune_fusion.py --vectors <file.npz> --out <file.json>
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "datasets" / "eval" / "sm1_dev_queries.csv"
DEPTHS = (5, 20, 50, 100, 200)
ACTION_W_F = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
SCENE_W_F = (0.5, 0.6, 0.7, 0.8, 0.9)


def _encode_inside(texts: list[str]) -> dict:
    """Inside `query`: each text's two vectors, from ai_workers' pinned encoders."""
    import httpx

    out = {"frame": [], "clip": []}
    for text in texts:
        for name, path in (("frame", "text"), ("clip", "clip-text")):
            response = httpx.post(f"http://ai-workers:8000/encode/{path}", json={"q": text}, timeout=300)
            response.raise_for_status()
            out[name].append(response.json()["vector"])
    return out


def encode(texts: list[str]) -> dict:
    return json.loads(subprocess.run(
        ["docker", "compose", "exec", "-T", "query", "uv", "run", "--package", "omnisight-query", "python", "-", "--inside", json.dumps(texts)],
        input=Path(__file__).read_bytes(), capture_output=True, check=True,
    ).stdout)


def ranked(vectors, query, depth: int) -> list[int]:
    """Every vector compared, best first, equal scores by row (as `measure_sm1._exact_top`)."""
    import numpy as np

    return [int(row) for row in np.argsort(-(vectors @ query), kind="stable")[:depth]]


def evaluate(rows: list[dict], depth: int, weights, sm1) -> dict:
    """Recall@5 of one setting. `weights(row)` is the query's `w_f`; each row holds both ranked lists."""
    from omnisight_common.fusion import fuse

    found = {"action": 0, "scene": 0}
    near = {"action": 0, "scene": 0}
    for row in rows:
        w_f = weights(row)
        hits = fuse(row["frame"][:depth], row["clip"][:depth], w_f, 1 - w_f, sm1.K)
        found[row["kind"]] += any(row["correct"][h.segment_id] for h in hits)
        near[row["kind"]] += any(row["near"][h.segment_id] for h in hits)
    n = {kind: sum(r["kind"] == kind for r in rows) for kind in found}
    return {
        "all": sum(found.values()) / len(rows),
        "action": found["action"] / n["action"],
        "scene": found["scene"] / n["scene"],
        "all_near": sum(near.values()) / len(rows),
        "action_near": near["action"] / n["action"],
    }


def single(rows: list[dict], list_name: str, sm1) -> dict:
    """One list alone, its top 5: the frame-only baseline, and clip only."""
    n = {kind: sum(r["kind"] == kind for r in rows) for kind in ("action", "scene")}
    found = {kind: sum(any(r["correct"][h] for h in r[list_name][:sm1.K]) for r in rows if r["kind"] == kind) for kind in n}
    near = sum(any(r["near"][h] for h in r[list_name][:sm1.K]) for r in rows)
    return {"all": sum(found.values()) / len(rows), "action": found["action"] / n["action"], "scene": found["scene"] / n["scene"], "all_near": near / len(rows)}


def order(item: dict) -> tuple:
    return (
        -item["all"], -item["action"], item["depth"],
        abs((item["action_w_f"] or 0.0) - 0.5) + abs((item["scene_w_f"] or 0.0) - 0.5),
    )


def grid(rows: list[dict], sm1) -> list[dict]:
    results = []
    for depth in DEPTHS:
        results.append({"depth": depth, "action_w_f": None, "scene_w_f": None, **evaluate(rows, depth, lambda r: r["w_f"], sm1)})
        for action_w_f in ACTION_W_F:
            for scene_w_f in SCENE_W_F:
                results.append({
                    "depth": depth, "action_w_f": action_w_f, "scene_w_f": scene_w_f,
                    **evaluate(rows, depth, lambda r: scene_w_f if r["w_f"] >= 0.5 else action_w_f, sm1),  # noqa: B023
                })
    return sorted(results, key=order)


def main() -> int:
    import csv

    import numpy as np
    from omnisight_common.fusion import ModalityClassifier
    from omnisight_common.settings import CommonSettings

    sys.path.insert(0, str(ROOT / "scripts"))
    import measure_sm1 as sm1

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--archive", type=Path, default=sm1.ARCHIVE)
    parser.add_argument("--annotations", type=Path, default=ROOT / "data" / "virat")
    args = parser.parse_args()

    queries = sm1.read_queries(DEV)
    if not args.vectors.is_file():
        encoded = encode([q["text"] for q in queries])
        np.savez(args.vectors, frame=np.asarray(encoded["frame"], np.float32), clip=np.asarray(encoded["clip"], np.float32))
    with np.load(args.vectors) as data:
        frame_text, clip_text = data["frame"], data["clip"]
    print(f"{len(queries)} tuning queries encoded", flush=True)

    with open(ROOT / "datasets" / "splits" / "virat.csv", newline="") as f:
        keys = [row["clip_key"] for row in csv.DictReader(f) if row["split"] == "evaluation"]
    pins = {name: CommonSettings.model_fields[name].default for name in ("frame_model_id", "frame_model_revision", "clip_model_id", "clip_model_revision")}
    archive = sm1.load_archive(keys, args.archive, args.annotations, {q["answer_rule"] for q in queries}, pins=pins)
    print(f"{len(archive)} frames loaded", flush=True)
    classifier = ModalityClassifier.load(pins["frame_model_id"], pins["frame_model_revision"])

    rows = []
    for query, frame, clip in zip(queries, frame_text, clip_text, strict=True):
        rows.append({
            "query_id": query["query_id"],
            "kind": query["kind"],
            "w_f": classifier.weights(frame.tolist())[0],
            "frame": ranked(archive.frame_vectors, frame, max(DEPTHS)),
            "clip": ranked(archive.clip_vectors, clip, max(DEPTHS)),
            "correct": archive.correct[query["answer_rule"]],
            "near": archive.correct_near[query["answer_rule"]],
        })

    result = {
        "frame_only": single(rows, "frame", sm1),
        "clip_only": single(rows, "clip", sm1),
        "classifier_as_measured": {"depth": 5, **evaluate(rows, 5, lambda r: r["w_f"], sm1)},
        "classifier_wrong_kind": [r["query_id"] for r in rows if (r["w_f"] >= 0.5) != (r["kind"] == "scene")],
        "grid": grid(rows, sm1),
    }
    args.out.write_text(json.dumps(result, indent=1))
    print("frame only     ", result["frame_only"])
    print("clip only      ", result["clip_only"])
    print("as measured    ", result["classifier_as_measured"])
    print("classifier wrong on", result["classifier_wrong_kind"])
    print("best per depth, classifier's own weights and the grid's:")
    for depth in DEPTHS:
        own = next(r for r in result["grid"] if r["depth"] == depth and r["action_w_f"] is None)
        best = next(r for r in result["grid"] if r["depth"] == depth and r["action_w_f"] is not None)
        print(" own ", own)
        print(" best", best)
    print("top 10:")
    for item in result["grid"][:10]:
        print(item)
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--inside"]:
        sys.stdout.write(json.dumps(_encode_inside(json.loads(sys.argv[2]))))
        sys.exit(0)
    sys.exit(main())
