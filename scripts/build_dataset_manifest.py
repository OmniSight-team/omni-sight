"""Build `dataset_manifest` from the three loaders and check the counts (OMNI-604).

Reads the local mirror under `data/` (annotation files plus each dataset's
`video_files.txt`, made on Drive by `scripts/list_dataset_videos.py`), so it covers every
clip whether or not its video is local. Upserts on `(dataset, clip_key)`: labels are
refreshed, `split` and `video_id` are never touched. Then compares the counts with the
audited ones in `docs/dataset-layout.md` and exits non-zero on any difference.

Needs Postgres up with migrations applied (`docker compose up -d`). From the repo root:

  uv run python scripts/build_dataset_manifest.py
"""

import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "query"))

from app.db import SessionLocal
from app.models import DatasetManifest
from omnisight_common.datasets import ccd, ucf_crime, virat
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

DATA = ROOT / "data"
LOADERS = {"ucf_crime": ucf_crime.load, "ccd": ccd.load, "virat": virat.load}
LABEL_COLUMNS = ("domain", "event_class", "event_start_s", "event_end_s", "annotation_source", "video_relpath", "attributes")

# Audited in docs/dataset-layout.md (2026-09-20 / 21).
EXPECTED = {
    ("ucf_crime", "total"): 1900,
    ("ccd", "Crash"): 1500,
    ("ccd", "Normal"): 3000,
    ("virat", "total"): 275,
}


def upsert(entries) -> None:
    rows = [asdict(e) for e in entries]
    with SessionLocal() as session:
        for i in range(0, len(rows), 1000):
            stmt = insert(DatasetManifest).values(rows[i : i + 1000])
            stmt = stmt.on_conflict_do_update(
                constraint="uq_dataset_manifest_clip",
                set_={c: getattr(stmt.excluded, c) for c in LABEL_COLUMNS},
            )
            session.execute(stmt)
        session.commit()


def main() -> int:
    for dataset, load in LOADERS.items():
        entries = load(DATA / dataset)
        upsert(entries)
        print(f"{dataset}: {len(entries)} clips loaded")

    with SessionLocal() as session:
        by_class = Counter(
            {
                (d, c, s): n
                for d, c, s, n in session.execute(
                    select(
                        DatasetManifest.dataset,
                        DatasetManifest.event_class,
                        DatasetManifest.annotation_source,
                        func.count(),
                    ).group_by(DatasetManifest.dataset, DatasetManifest.event_class, DatasetManifest.annotation_source)
                )
            }
        )
    print("\nIn the manifest (dataset, class, annotation source):")
    for (d, c, s), n in sorted(by_class.items(), key=lambda kv: (kv[0][0], str(kv[0][1]), kv[0][2])):
        print(f"  {d:10s} {c!s:14s} {s:20s} {n:5d}")

    got = {
        ("ucf_crime", "total"): sum(n for (d, _, _), n in by_class.items() if d == "ucf_crime"),
        ("ccd", "Crash"): sum(n for (d, c, _), n in by_class.items() if d == "ccd" and c == "Crash"),
        ("ccd", "Normal"): sum(n for (d, c, _), n in by_class.items() if d == "ccd" and c == "Normal"),
        ("virat", "total"): sum(n for (d, _, _), n in by_class.items() if d == "virat"),
    }
    print("\nAgainst docs/dataset-layout.md:")
    ok = True
    for key, want in EXPECTED.items():
        mark = "OK" if got[key] == want else "MISMATCH"
        ok &= got[key] == want
        print(f"  {key[0]:10s} {key[1]:7s} expected {want:5d}  got {got[key]:5d}  {mark}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
