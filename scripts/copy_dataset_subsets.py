"""Copy the dataset clips the product loads from Drive into the local mirror (OMNI-608, D-26).

Reads `datasets/hand_check/sample.csv` (the 60 clips of the hand-check sample) and
`datasets/demo/virat_sample.csv` (the 9 VIRAT demo videos, OMNI-702), the only dataset
footage loaded, and copies each file from the Drive folder, mounted locally by
Google Drive for desktop, to `data/<dataset>/<video_relpath>`, native paths kept. A file
already present with Drive's size is skipped, so the copy can be stopped and run again.
Each file is written under a `.part` name and renamed once its size equals Drive's.

From the repo root, Drive's `omnisight/data` folder as the argument:

  uv run python scripts/copy_dataset_subsets.py "G:/My Drive/omnisight/data"
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SAMPLES = (ROOT / "datasets" / "hand_check" / "sample.csv", ROOT / "datasets" / "demo" / "virat_sample.csv")


def main(drive: Path) -> int:
    rows = [ln.split(",") for sample in SAMPLES for ln in sample.read_text(encoding="utf-8").splitlines()[1:]]
    copied = skipped = 0
    bad: list[str] = []
    for dataset, _, relpath, *_ in rows:
        src, dst = drive / dataset / relpath, DATA / dataset / relpath
        size = src.stat().st_size
        if dst.is_file() and dst.stat().st_size == size:
            skipped += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        part = dst.with_name(dst.name + ".part")
        shutil.copyfile(src, part)
        if part.stat().st_size != size:
            bad.append(f"{dataset}/{relpath}: {part.stat().st_size} bytes, Drive has {size}")
            part.unlink()
            continue
        part.replace(dst)
        copied += 1
    print(f"{len(rows)} clips: copied {copied}, already there {skipped}, size mismatches {len(bad)}")
    for b in bad:
        print("  " + b)
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
