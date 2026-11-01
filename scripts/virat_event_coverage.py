"""How much of VIRAT's annotated events the gate kept (OMNI-709, K-23).

Search can only find frames the gate admitted. Over the 275 evaluation videos, the archive's
admitted frames (OMNI-708, `frame_index` and `admission_reason` of each `.npz`) against the
events in `annotations/` (`read_events`, frames both ends included):

- per event type: the share of events holding at least one admitted frame, and at least one
  admitted for motion. A type with none is dropped from the SM-1 query set
- per event type and per scene: the share of all admitted frames that a query's answer rule
  counts as correct, and the recall@5 five frames drawn at random would get, `1 - (1 - p)^5`.
  What SM-1's number has to be read against

Reads Drive through Google Drive for desktop (or wherever `--archive` points); nothing is
written but `--out`. From the repo root:

  uv run python scripts/virat_event_coverage.py --out "G:/My Drive/omnisight/results/omni709_coverage.json"
"""

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from omnisight_common.datasets import virat

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = Path("G:/My Drive/omnisight/embeddings/virat")


@dataclass
class TypeCount:
    events: int = 0
    with_admitted: int = 0
    with_motion: int = 0
    frames_correct: int = 0


@dataclass
class Coverage:
    types: dict[int, TypeCount] = field(default_factory=dict)
    frames_per_scene: Counter = field(default_factory=Counter)
    frames: int = 0

    def add_video(self, name: str, events: list[virat.Event], frame_index: np.ndarray, reasons: np.ndarray) -> None:
        """One video: its events against its admitted frames."""
        motion = frame_index[reasons == "motion"]
        inside_any: dict[int, np.ndarray] = {}
        for e in events:
            count = self.types.setdefault(e.event_type, TypeCount())
            count.events += 1
            inside = (frame_index >= e.start_frame) & (frame_index <= e.end_frame)
            count.with_admitted += bool(inside.any())
            count.with_motion += bool(((motion >= e.start_frame) & (motion <= e.end_frame)).any())
            inside_any[e.event_type] = inside_any.get(e.event_type, np.zeros_like(inside)) | inside
        # A frame inside two events of a type is one correct answer, not two.
        for event_type, inside in inside_any.items():
            self.types[event_type].frames_correct += int(inside.sum())
        self.frames_per_scene[virat.scene_of(name)] += len(frame_index)
        self.frames += len(frame_index)


def chance_at_5(correct: int, total: int) -> float:
    """The recall@5 of five frames drawn at random, with replacement."""
    return 1 - (1 - correct / total) ** 5


def report(coverage: Coverage) -> dict:
    types = {
        t: {
            "name": virat.EVENT_TYPES[t],
            "events": c.events,
            "with_admitted": c.with_admitted,
            "with_motion": c.with_motion,
            "frames_correct": c.frames_correct,
            "share_of_frames": c.frames_correct / coverage.frames,
            "chance_at_5": chance_at_5(c.frames_correct, coverage.frames),
        }
        for t, c in sorted(coverage.types.items())
    }
    scenes = {
        s: {"frames": n, "share_of_frames": n / coverage.frames, "chance_at_5": chance_at_5(n, coverage.frames)}
        for s, n in sorted(coverage.frames_per_scene.items())
    }
    return {"frames": coverage.frames, "types": types, "types_without_events": sorted(set(virat.EVENT_TYPES) - set(types)), "scenes": scenes}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ARCHIVE)
    parser.add_argument("--annotations", type=Path, default=ROOT / "data" / "virat")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    with open(ROOT / "datasets" / "splits" / "virat.csv", newline="") as f:
        keys = [row["clip_key"] for row in csv.DictReader(f) if row["split"] == "evaluation"]
    coverage = Coverage()
    for n, key in enumerate(keys, 1):
        with np.load(args.archive / f"{key}.npz") as data:
            coverage.add_video(key, virat.read_events(args.annotations, key), data["frame_index"], data["admission_reason"])
        if n % 25 == 0:
            print(f"{n} of {len(keys)} videos", flush=True)

    result = report(coverage)
    print(f"\n{len(keys)} videos, {result['frames']} admitted frames")
    print("type  events  with admitted  with motion  frames correct  share  chance@5  name")
    for t, c in result["types"].items():
        print(
            f"{t:4d}  {c['events']:6d}  {c['with_admitted']:5d} {c['with_admitted'] / c['events']:6.1%}"
            f"  {c['with_motion']:4d} {c['with_motion'] / c['events']:6.1%}"
            f"  {c['frames_correct']:14d}  {c['share_of_frames']:5.1%}  {c['chance_at_5']:7.1%}  {c['name']}"
        )
    print(f"types with no event: {result['types_without_events']}")
    print("scene  frames  share  chance@5")
    for s, c in result["scenes"].items():
        print(f"{s}  {c['frames']:6d}  {c['share_of_frames']:5.1%}  {c['chance_at_5']:7.1%}")
    if args.out:
        args.out.write_text(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
