"""Event times for UCF-Crime from UCA, and how far they agree with the official ones (OMNI-603).

UCF-Crime times its anomalies for the 290 test videos only. UCA (UCF-Crime Annotation,
Yuan et al., CVPR 2024; github.com/Xuange923/Surveillance-Video-Understanding, folder
`UCF Annotation`, Apache-2.0, academic use) gives start and end times at 0.1 s for
**every** event described in 1,854 UCF-Crime videos: people walking in, cars passing,
and somewhere among them the crime. So the crime's segment has to be picked.

The rule (written before the agreement was computed, from training-video descriptions
only; this is the "semi-automatic" part Phase A names):

  1. Each anomaly class has a list of word patterns naming its act (CLASS_PATTERNS
     in `omnisight_common.datasets.uca`: "collided", "crash" for RoadAccidents; "shot", "gun" for Shooting ...).
  2. A video's event is the UCA segment with the **earliest start** whose description
     matches one of its class's patterns (UCA's segments are not in time order).
     Event start and end = that segment's start and end.
  3. No segment matches: the video has **no event time**. Nothing is guessed, and the
     video gets no lead-up window.

Normal videos have no event. The class is taken from the video name's prefix, which is
the class folder on disk.

Agreement: on the official test anomaly videos that UCA also describes, the start picked
by the rule is compared with the official first interval's start (frame number / 30, the
frame rate the official annotation is written at, `ReadMe-Anomaly-Detection.txt`).

Run from the repo root (reads the local annotation mirror, nothing else):

  uv run python scripts/uca_event_times.py
"""

import statistics
from collections import Counter
from pathlib import Path

from omnisight_common.datasets.uca import CLASS_PATTERNS, class_of, pick_event
from omnisight_common.datasets.uca import load_uca as _load_uca

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "data" / "ucf_crime" / "annotations"
UCA = ANN / "uca" / "json"
OFFICIAL_FPS = 30.0


def load_uca() -> dict[str, tuple[str, dict]]:
    return _load_uca(UCA)


def official_lists() -> tuple[list[str], list[str]]:
    def read(p: Path) -> list[str]:
        return [ln.strip().split("/")[-1].removesuffix(".mp4") for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]

    return read(ANN / "Anomaly_Train.txt"), read(ANN / "Anomaly_Detection_splits" / "Anomaly_Test.txt")


def official_times() -> dict[str, tuple[float, float, float, float]]:
    out = {}
    for ln in (ANN / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt").read_text(encoding="utf-8").split("\n"):
        parts = ln.split()
        if parts:
            out[parts[0].removesuffix(".mp4")] = tuple(float(x) for x in parts[2:6])
    return out


def main() -> None:
    uca = load_uca()
    train, test = official_lists()
    print(f"UCA: {len(uca)} videos ({Counter(s for s, _ in uca.values())}); official lists: train {len(train)}, test {len(test)}")
    print(f"UCA videos not in the official lists: {sum(1 for n in uca if n not in set(train) | set(test))}")

    print("\nOfficial training anomaly videos: described by UCA, and timed by the rule")
    rows = []
    for c in sorted(CLASS_PATTERNS):
        names = [n for n in train if class_of(n) == c]
        described = [n for n in names if n in uca]
        timed = [n for n in described if pick_event(c, uca[n][1])]
        rows.append((c, len(names), len(described), len(timed)))
        print(f"  {c:14s} {len(names):4d} videos, {len(described):4d} in UCA, {len(timed):4d} timed")
    tot = [sum(r[i] for r in rows) for i in (1, 2, 3)]
    print(f"  {'total':14s} {tot[0]:4d} videos, {tot[1]:4d} in UCA, {tot[2]:4d} timed")
    missing = [n for n in train if class_of(n) != "Normal" and n not in uca]
    print(f"  not in UCA: {missing}")
    untimed = [n for n in train if class_of(n) != "Normal" and n in uca and not pick_event(class_of(n), uca[n][1])]
    print(f"  in UCA, no segment matches: {untimed}")

    print("\nAgreement on official test anomaly videos (UCA start by the rule vs official start1 / 30 fps)")
    off = official_times()
    diffs, signed, inside, no_match, per_class = [], [], 0, [], {}
    for n in test:
        c = class_of(n)
        if c == "Normal" or n not in uca:
            continue
        pick = pick_event(c, uca[n][1])
        if pick is None:
            no_match.append(n)
            continue
        s1, e1, s2, e2 = off[n]
        o_start, o_end = s1 / OFFICIAL_FPS, e1 / OFFICIAL_FPS
        d = pick[0] - o_start
        signed.append(d)
        diffs.append(abs(d))
        per_class.setdefault(c, []).append(abs(d))
        in2 = s2 >= 0 and s2 / OFFICIAL_FPS <= pick[0] <= e2 / OFFICIAL_FPS
        inside += (o_start <= pick[0] <= o_end) or in2
    n_cmp = len(diffs)
    print(f"  compared: {n_cmp}; no segment matched: {len(no_match)} {no_match}")
    print(f"  |difference| mean {statistics.mean(diffs):.1f} s, median {statistics.median(diffs):.1f} s, "
          f"p75 {statistics.quantiles(diffs, n=4)[2]:.1f} s, p90 {statistics.quantiles(diffs, n=10)[8]:.1f} s, max {max(diffs):.1f} s")
    print(f"  signed (UCA - official): mean {statistics.mean(signed):+.1f} s, median {statistics.median(signed):+.1f} s")
    for lim in (1, 2, 5, 10):
        k = sum(1 for x in diffs if x <= lim)
        print(f"  within {lim:2d} s: {k} of {n_cmp} ({100 * k / n_cmp:.0f}%)")
    print(f"  UCA start inside an official interval: {inside} of {n_cmp} ({100 * inside / n_cmp:.0f}%)")
    print("  per class, median |difference| (n):")
    for c, xs in sorted(per_class.items()):
        print(f"    {c:14s} {statistics.median(xs):6.1f} s  ({len(xs)})")


if __name__ == "__main__":
    main()
