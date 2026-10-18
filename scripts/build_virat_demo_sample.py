"""Draw the VIRAT demo sample once and write `datasets/demo/virat_sample.csv` (OMNI-702, D-26).

One VIRAT video per scene among the videos under the upload limit (9 scenes), the only VIRAT
footage loaded into the product, so search has real surveillance footage to work on
(`omnisight_common.datasets.demo`). Reads the loader on the local mirror's listing and
annotations, the committed split, and each file's size from OMNI-608's probe of Drive
(`data/omni608_estimate.csv`); no database. Fixed like the hand-check sample: if the file
exists and the redraw differs, nothing is written. Prints the sample with each video's size,
frames and duration, the scenes left out, and the file's SHA-256. From the repo root:

  uv run python scripts/build_virat_demo_sample.py
"""

import csv
import hashlib
import sys
from pathlib import Path

from omnisight_common.datasets import virat
from omnisight_common.datasets.demo import MAX_BYTES, SEED, sample_csv, sample_virat

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "datasets" / "demo" / "virat_sample.csv"
PROBE = ROOT / "data" / "omni608_estimate.csv"


def main() -> int:
    split = {
        ln.split(",")[0]: ln.split(",")[2]
        for ln in (ROOT / "datasets" / "splits" / "virat.csv").read_text(encoding="utf-8").splitlines()[1:]
    }
    with PROBE.open(encoding="utf-8") as f:
        probe = {r["video_relpath"]: r for r in csv.DictReader(f) if r["dataset"] == "virat"}
    entries = virat.load(ROOT / "data" / "virat")
    picked = sample_virat(entries, {rel: int(r["size_bytes"]) for rel, r in probe.items()})
    data = sample_csv(picked, split)
    if OUT.exists() and OUT.read_bytes() != data:
        print(f"{OUT} exists and the redrawn sample differs: the sample is fixed. Nothing written.")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)

    left_out = sorted({e.attributes["scene"] for e in entries} - {e.attributes["scene"] for e in picked})
    print(f"seed {SEED}, {len(picked)} videos; scenes with no video under {MAX_BYTES // 2**20} MB: {left_out}")
    total_mb = total_frames = 0.0
    for e in sorted(picked, key=lambda e: e.clip_key):
        p = probe.get(e.video_relpath, {})
        mb = int(p.get("size_bytes") or 0) / 1e6
        frames = int(p.get("frames") or 0)
        total_mb, total_frames = total_mb + mb, total_frames + frames
        print(
            f"  {e.attributes['scene']}  {e.clip_key:34s} {mb:8.1f} MB {frames:7d} frames "
            f"{p.get('duration_s', '?'):>9s} s  {p.get('fps', '?')} fps  events {e.attributes['events']}"
        )
    print(f"  total {total_mb:.1f} MB, {int(total_frames)} frames")
    print(f"\n{OUT.relative_to(ROOT).as_posix()} sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
