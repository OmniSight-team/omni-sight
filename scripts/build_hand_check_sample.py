"""Draw the hand-check sample once and write `datasets/hand_check/sample.csv` (OMNI-608, D-26).

The 60 clips OMNI-609 checks by eye (`omnisight_common.datasets.hand_check`), and the only
dataset clips loaded into the product. Reads the loaders, the committed split and the
committed windows (no database). Like the split, the sample is fixed: if the file exists
and the redraw differs, nothing is written. Prints the sample per class and source, and the
file's SHA-256. From the repo root:

  uv run python scripts/build_hand_check_sample.py
"""

import hashlib
import sys
from collections import Counter
from pathlib import Path

from omnisight_common.datasets import ccd, ucf_crime
from omnisight_common.datasets.hand_check import SAMPLERS, SEED, sample_csv

ROOT = Path(__file__).resolve().parents[1]
LOADERS = {"ucf_crime": ucf_crime.load, "ccd": ccd.load}
OUT = ROOT / "datasets" / "hand_check" / "sample.csv"


def rows(path: Path) -> list[list[str]]:
    return [ln.split(",") for ln in path.read_text(encoding="utf-8").splitlines()[1:]]


def main() -> int:
    picked, split = {}, {}
    for dataset, load in LOADERS.items():
        split[dataset] = {r[0]: r[2] for r in rows(ROOT / "datasets" / "splits" / f"{dataset}.csv")}
        windowed = {r[0] for r in rows(ROOT / "datasets" / "windows" / f"{dataset}.csv") if r[2] == "positive"}
        picked[dataset] = SAMPLERS[dataset](load(ROOT / "data" / dataset), windowed)
    data = sample_csv(picked, split)
    if OUT.exists() and OUT.read_bytes() != data:
        print(f"{OUT} exists and the redrawn sample differs: the sample is fixed. Nothing written.")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(data)

    print(f"seed {SEED}")
    for dataset, entries in picked.items():
        per = Counter((e.event_class, e.annotation_source.value, split[dataset][e.clip_key]) for e in entries)
        print(f"\n{dataset}: {len(entries)} clips")
        for (cls, src, sp), n in sorted(per.items()):
            print(f"  {cls:14s} {src:20s} {sp:11s} {n}")
    print(f"\n{OUT.relative_to(ROOT).as_posix()} sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
