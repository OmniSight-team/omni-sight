"""Derive the lead-up windows, export them for Colab and write `event_windows` (OMNI-607, D-24).

Inputs, all from the local mirror and the repo:
- the loaders' manifest entries (`omnisight_common.datasets`)
- the committed split, `datasets/splits/{dataset}.csv` (D-22): windows take their clip's split
- each video's probe, `data/{dataset}/video_probe.csv`, made on Drive by
  `scripts/probe_dataset_videos.py` (fps and duration read from every file, never assumed)

Writes `datasets/windows/{dataset}.csv` (one row per window) and
`datasets/windows/{dataset}_skipped.csv` (one row per event and length that has no window,
with the reason). Like the split, the windows are fixed once: when a file exists and the
rebuild differs, the script stops and writes nothing. Then inserts the windows into
`event_windows` (existing rows, and their hand-check verdicts, are left alone) and prints
the counts per class, split and length, the shortened and skipped counts, every video not
at its labels' frame rate, and each file's SHA-256.

Needs Postgres up with the manifest built and split (`build_dataset_manifest.py`,
`build_dataset_split.py`). From the repo root:

  uv run python scripts/build_event_windows.py
"""

import hashlib
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "query"))

from app.db import SessionLocal
from app.models import DatasetManifest, EventWindow
from omnisight_common.datasets import ccd, ucf_crime
from omnisight_common.datasets.windows import (
    DERIVERS,
    LABEL_FPS,
    SEED,
    off_rate,
    read_probes,
    skipped_csv,
    windows_csv,
)
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

DATA = ROOT / "data"
SPLITS = ROOT / "datasets" / "splits"
WINDOWS = ROOT / "datasets" / "windows"
LOADERS = {"ucf_crime": ucf_crime.load, "ccd": ccd.load}


def read_split(dataset: str) -> dict[str, str]:
    lines = (SPLITS / f"{dataset}.csv").read_text(encoding="utf-8").splitlines()[1:]
    return {k: s for k, _, s in (ln.split(",") for ln in lines)}


def length_label(w) -> str:
    return "as is" if w.nominal_length_s is None else f"{w.nominal_length_s:g} s"


def report(dataset: str, entries, probes, windows, skipped) -> None:
    print(f"\n=== {dataset}: {len(windows)} windows, {len(skipped)} skipped rows")
    per = Counter((w.kind, w.event_class, w.split, length_label(w)) for w in windows)
    splits = ("train", "validation", "held_out")
    print(f"  {'kind':9s}{'class':15s}{'length':8s}" + "".join(f"{s:>11s}" for s in splits) + f"{'total':>8s}")
    for kind, cls, length in sorted({(k, c, ln) for k, c, _, ln in per}):
        counts = [per[(kind, cls, s, length)] for s in splits]
        print(f"  {kind:9s}{cls:15s}{length:8s}" + "".join(f"{n:11d}" for n in counts) + f"{sum(counts):8d}")

    shortened = Counter((w.kind, length_label(w)) for w in windows if w.shortened)
    print("  shortened (kind, length): " + (", ".join(f"{k} {ln}: {n}" for (k, ln), n in sorted(shortened.items())) or "none"))
    skip = Counter((k.interval, "as is" if k.nominal_length_s is None else f"{k.nominal_length_s:g} s", k.reason) for k in skipped)
    print("  skipped (interval, length, reason):")
    for (i, ln, r), n in sorted(skip.items()):
        print(f"    {i}  {ln:6s} {n:5d}  {r}")
    lengths = sorted(w.length_s for w in windows if w.kind == "positive")
    if lengths:
        print(f"  positive length: min {lengths[0]:.3f} s, median {lengths[len(lengths) // 2]:.3f} s, max {lengths[-1]:.3f} s")

    off = off_rate(entries, probes, dataset)
    print(f"  videos not at {LABEL_FPS[dataset]:g} fps: {len(off)}")
    rates = Counter(round(f, 3) for _, f in off)
    for f, n in sorted(rates.items()):
        print(f"    {f:g} fps: {n}")
    for k, f in off[:20]:
        print(f"    {k}  {f:g}")


def main() -> int:
    built = {}
    for dataset, load in LOADERS.items():
        entries = load(DATA / dataset)
        probes = read_probes(DATA / dataset)
        windows, skipped = DERIVERS[dataset](entries, read_split(dataset), probes)
        built[dataset] = (entries, probes, windows, skipped)

    files = {}
    for dataset, (_, _, windows, skipped) in built.items():
        files[WINDOWS / f"{dataset}.csv"] = windows_csv(windows)
        files[WINDOWS / f"{dataset}_skipped.csv"] = skipped_csv(skipped)
    for path, data in files.items():
        if path.exists() and path.read_bytes() != data:
            print(f"{path} exists and the rebuilt windows differ: windows are fixed once. Nothing written.")
            return 1
    WINDOWS.mkdir(parents=True, exist_ok=True)
    for path, data in files.items():
        path.write_bytes(data)

    with SessionLocal() as session:
        for dataset, (_, _, windows, _) in built.items():
            ids = dict(
                session.execute(
                    select(DatasetManifest.clip_key, DatasetManifest.id).where(DatasetManifest.dataset == dataset)
                ).all()
            )
            rows = [
                {
                    "manifest_id": ids[w.clip_key], "kind": w.kind, "nominal_length_s": w.nominal_length_s,
                    "window_start_s": w.window_start_s, "window_end_s": w.window_end_s, "length_s": w.length_s,
                    "shortened": w.shortened, "event_class": w.event_class, "domain": w.domain, "split": w.split,
                }
                for w in windows
            ]
            for i in range(0, len(rows), 1000):
                session.execute(
                    insert(EventWindow).values(rows[i : i + 1000]).on_conflict_do_nothing(constraint="uq_event_windows_window")
                )
        session.commit()
        in_db = dict(
            session.execute(
                select(DatasetManifest.dataset, func.count())
                .join(EventWindow, EventWindow.manifest_id == DatasetManifest.id)
                .group_by(DatasetManifest.dataset)
            ).all()
        )

    print(f"seed {SEED}")
    for dataset, (entries, probes, windows, skipped) in built.items():
        report(dataset, entries, probes, windows, skipped)
    print("\nFiles:")
    for path, data in files.items():
        n = len(data.splitlines()) - 1
        print(f"  {path.relative_to(ROOT).as_posix():40s} {n:6d} rows  sha256 {hashlib.sha256(data).hexdigest()}")
    print("\nevent_windows rows: " + ", ".join(f"{d} {n}" for d, n in sorted(in_db.items())))
    ok = all(in_db.get(d) == len(b[2]) for d, b in built.items())
    print("rows in the table equal the CSVs" if ok else "MISMATCH between the table and the CSVs")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
