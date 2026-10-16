"""The hand check's result: correct out of checked, per dataset and per source (OMNI-609).

Reads the verdicts given on the check screen (`/windows`, criterion D-27) from
`event_windows` for the 60 sampled windows, and prints: checked and correct per dataset and
per annotation source (UCF-Crime official / UCA, CCD), with a 95% Wilson interval (the
sample is small, so the rate is a range, not a point), then every window marked Wrong with
its reason. From the repo root, with the stack up:

  uv run --package omnisight-query python scripts/hand_check_report.py
"""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "query"))

from app.db import SessionLocal
from app.settings import settings
from app.windows import _sampled

# The sample file is mounted at /hand_check inside query; read the repo copy here.
settings.hand_check_sample_path = str(ROOT / "datasets" / "hand_check" / "sample.csv")

LABELS = {"ucf_crime_temporal": "UCF-Crime, official", "uca": "UCF-Crime, UCA", "ccd_binlabels": "CCD"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (centre - half, centre + half)


def main() -> None:
    with SessionLocal() as db:
        rows = db.execute(_sampled()).all()
    groups: dict[str, list] = {}
    for w, m, email in rows:
        groups.setdefault(m.annotation_source.value, []).append((w, m, email))
    groups["ucf_crime (both)"] = groups.get("ucf_crime_temporal", []) + groups.get("uca", [])

    print(f"{'group':22s} {'in sample':>9s} {'checked':>8s} {'correct':>8s} {'rate':>6s}  95% interval")
    for key in ("ucf_crime_temporal", "uca", "ucf_crime (both)", "ccd_binlabels"):
        g = groups.get(key, [])
        checked = [w for w, _, _ in g if w.verified is not None]
        correct = sum(1 for w in checked if w.verified)
        lo, hi = wilson(correct, len(checked))
        rate = f"{correct / len(checked):.0%}" if checked else "-"
        print(f"{LABELS.get(key, key):22s} {len(g):9d} {len(checked):8d} {correct:8d} {rate:>6s}  {lo:.0%}-{hi:.0%}")

    wrong = [(w, m, e) for w, m, e in rows if w.verified is False]
    print(f"\nWrong: {len(wrong)}")
    for w, m, email in sorted(wrong, key=lambda r: (r[1].dataset, r[1].clip_key)):
        print(f"  {m.dataset:9s} {m.clip_key:28s} {LABELS[m.annotation_source.value]:20s} "
              f"window {w.window_start_s:.1f}-{w.window_end_s:.1f} s: {w.verify_reason} ({email})")
    unchecked = sum(1 for w, _, _ in rows if w.verified is None)
    print(f"\nNot checked yet: {unchecked} of {len(rows)}")


if __name__ == "__main__":
    main()
