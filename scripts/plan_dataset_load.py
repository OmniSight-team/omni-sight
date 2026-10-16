"""List the footage OMNI-608 loads into the product, from the manifest's own rule.

CCD: all 4,500 clips. VIRAT: the 275 with events (the whole VIRAT manifest). UCF-Crime: the
290 held-out videos (the official test list, D-22). Training stays on Colab, from Drive.

Reads the loaders and the committed split (no database). Writes `omni608_subsets.txt`,
one `dataset,video_relpath` per line, to the path given (default: the repo root's
`data/`). From the repo root:

  uv run python scripts/plan_dataset_load.py
"""

import sys
from pathlib import Path

from omnisight_common.datasets import ccd, ucf_crime, virat

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def subsets() -> list[tuple[str, str]]:
    split = {
        k: s
        for k, _, s in (ln.split(",") for ln in (ROOT / "datasets" / "splits" / "ucf_crime.csv").read_text().splitlines()[1:])
    }
    out = [("ccd", e.video_relpath) for e in ccd.load(DATA / "ccd")]
    out += [("virat", e.video_relpath) for e in virat.load(DATA / "virat")]
    out += [("ucf_crime", e.video_relpath) for e in ucf_crime.load(DATA / "ucf_crime") if split[e.clip_key] == "held_out"]
    return sorted(out)


def main(path: Path) -> None:
    rows = subsets()
    path.write_text("".join(f"{d},{rel}\n" for d, rel in rows), encoding="utf-8")
    for d in ("ccd", "virat", "ucf_crime"):
        print(f"{d}: {sum(1 for x, _ in rows if x == d)}")
    print(f"wrote {path}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DATA / "omni608_subsets.txt")
