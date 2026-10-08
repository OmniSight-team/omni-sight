"""CCD's pre-event footage, and the SM-3 target from the D-23 rule (OMNI-606).

Pre-event footage of a crash clip = seconds from its first frame to its first accident frame
= index of the first `1` in `Crash-1500.txt`'s `binlabels` / 10 fps (the CCD loader's
`event_start_s`). The split comes from the committed `datasets/splits/ccd.csv` (D-22).

Reports, for all 1,500 crash clips and per split: mean, median, p10, p25, p75, p90, min,
max, how many have under 1 s, and a histogram in 0.5 s bins. Then applies D-23:
target = half the median over the held-out crash clips. Percentiles are linear
interpolation between order statistics (`statistics.quantiles(method="inclusive")`).

Reads files only (no database). From the repo root:

  uv run python scripts/ccd_pre_event.py
"""

import statistics
from pathlib import Path

from omnisight_common.datasets import ccd

ROOT = Path(__file__).resolve().parents[1]
BIN_S = 0.5


def describe(xs: list[float]) -> dict:
    q = statistics.quantiles(xs, n=100, method="inclusive")
    return {
        "n": len(xs), "mean": statistics.mean(xs), "median": statistics.median(xs),
        "p10": q[9], "p25": q[24], "p75": q[74], "p90": q[89], "min": min(xs), "max": max(xs),
        "under_1s": sum(1 for x in xs if x < 1.0),
    }


def main() -> None:
    entries = {e.clip_key: e for e in ccd.load(ROOT / "data" / "ccd") if e.event_class == "Crash"}
    lines = (ROOT / "datasets" / "splits" / "ccd.csv").read_text(encoding="utf-8").splitlines()[1:]
    split = {k: s for k, _, s in (ln.split(",") for ln in lines)}
    groups = {"all": list(entries)} | {
        s: [k for k in entries if split[k] == s] for s in ("train", "validation", "held_out")
    }

    cols = ("n", "mean", "median", "p10", "p25", "p75", "p90", "min", "max", "under_1s")
    print(f"{'':12s}" + "".join(f"{c:>9s}" for c in cols))
    stats = {}
    for g, keys in groups.items():
        stats[g] = describe([entries[k].event_start_s for k in keys])
        print(f"{g:12s}" + "".join(
            f"{stats[g][c]:9d}" if isinstance(stats[g][c], int) else f"{stats[g][c]:9.2f}" for c in cols
        ))

    print(f"\nHistogram, {BIN_S} s bins (count of crash clips by pre-event footage):")
    edges = [i * BIN_S for i in range(int(5.0 / BIN_S))]
    print(f"{'bin':12s}" + "".join(f"{g:>11s}" for g in groups))
    for lo in edges:
        hi = lo + BIN_S
        counts = [sum(1 for k in keys if lo <= round(entries[k].event_start_s, 6) < hi) for keys in groups.values()]
        if any(counts):
            print(f"[{lo:.1f}, {hi:.1f}) s " + "".join(f"{c:11d}" for c in counts))

    median_ho = stats["held_out"]["median"]
    print(f"\nD-23: held-out median {median_ho:.2f} s -> SM-3 target mTTA >= {median_ho / 2:.2f} s")


if __name__ == "__main__":
    main()
