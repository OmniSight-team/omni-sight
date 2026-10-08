"""Fix the train / validation / held-out split and write it to the manifest (OMNI-605, D-22).

Builds the split from the three loaders (`omnisight_common.datasets.split`) and writes
`datasets/splits/{dataset}.csv`. The split is fixed once and never moves: when a CSV already
exists, the rebuilt bytes must equal it, otherwise the script stops and writes nothing.
Then sets `dataset_manifest.split` from the CSVs and prints the counts per split per class
and each file's SHA-256.

Needs Postgres up and the manifest built (`scripts/build_dataset_manifest.py`). From the
repo root:

  uv run python scripts/build_dataset_split.py
"""

import hashlib
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "query"))

from app.db import SessionLocal
from app.models import DatasetManifest
from omnisight_common.datasets import ccd, ucf_crime, virat
from omnisight_common.datasets.split import SEED, split_csv
from sqlalchemy import bindparam, func, select, update

DATA = ROOT / "data"
SPLITS = ROOT / "datasets" / "splits"
LOADERS = {"ucf_crime": ucf_crime.load, "ccd": ccd.load, "virat": virat.load}


def main() -> int:
    built = {d: split_csv(d, load(DATA / d)) for d, load in LOADERS.items()}
    for d, data in built.items():
        path = SPLITS / f"{d}.csv"
        if path.exists() and path.read_bytes() != data:
            print(f"{path} exists and the rebuilt split differs: the split never moves. Nothing written.")
            return 1

    SPLITS.mkdir(parents=True, exist_ok=True)
    for d, data in built.items():
        (SPLITS / f"{d}.csv").write_bytes(data)

    with SessionLocal() as session:
        for d, data in built.items():
            rows = [ln.split(",") for ln in data.decode("utf-8").splitlines()[1:]]
            session.connection().execute(
                update(DatasetManifest.__table__)
                .where(DatasetManifest.dataset == d, DatasetManifest.clip_key == bindparam("k"))
                .values(split=bindparam("s")),
                [{"k": k, "s": s} for k, _, s in rows],
            )
        session.commit()
        missing = session.scalar(select(func.count()).where(DatasetManifest.split.is_(None)))

    print(f"seed {SEED}")
    for d, data in built.items():
        rows = [ln.split(",") for ln in data.decode("utf-8").splitlines()[1:]]
        print(f"\n{d}: {len(rows)} clips, sha256 {hashlib.sha256(data).hexdigest()}")
        per = Counter((c or "-", s) for _, c, s in rows)
        splits = sorted({s for _, s in per})
        print(f"  {'class':14s}" + "".join(f"{s:>12s}" for s in splits))
        for c in sorted({c for c, _ in per}):
            print(f"  {c:14s}" + "".join(f"{per[(c, s)]:12d}" for s in splits))
        totals = Counter(s for _, _, s in rows)
        print(f"  {'total':14s}" + "".join(f"{totals[s]:12d}" for s in splits))
    print(f"\nmanifest rows without a split: {missing}")
    return 0 if missing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
