"""The train / validation / held-out split, fixed once (OMNI-605, D-22).

Deterministic: a fixed seed, every input sorted before it is shuffled, so the same manifest
always gives the same split. The committed CSVs under `datasets/splits/` are the split;
`scripts/build_dataset_split.py` refuses to write a different one.

- UCF-Crime: held-out = the official 290 test videos; validation = 15% of the official
  training list, stratified by class (and within a class by timed / untimed, so validation
  has the same share of videos that get lead-up windows); train = the rest
- CCD: 15% held-out, 15% validation, stratified crash / normal. Crash clips are assigned by
  source video (`youtube_id`), so clips cut from one video never sit on two sides
- VIRAT: evaluation only (SM-1), no training split
"""

import random
from collections import defaultdict

from omnisight_common.datasets import AnnotationSource, ManifestEntry

SEED = 605
VALIDATION_FRACTION = 0.15
HELD_OUT_FRACTION = 0.15
TRAIN, VALIDATION, HELD_OUT, EVALUATION = "train", "validation", "held_out", "evaluation"
CSV_HEADER = "clip_key,event_class,split"


def split_ucf_crime(entries: list[ManifestEntry]) -> dict[str, str]:
    rng = random.Random(SEED)
    out: dict[str, str] = {}
    strata: dict[tuple[str, bool], list[str]] = defaultdict(list)
    for e in entries:
        if e.attributes["official_list"] == "test":
            out[e.clip_key] = HELD_OUT
        else:
            strata[(e.event_class, e.annotation_source == AnnotationSource.UNTIMED)].append(e.clip_key)
    for key in sorted(strata):
        keys = sorted(strata[key])
        rng.shuffle(keys)
        n_val = round(len(keys) * VALIDATION_FRACTION)
        for i, k in enumerate(keys):
            out[k] = VALIDATION if i < n_val else TRAIN
    return out


def split_ccd(entries: list[ManifestEntry]) -> dict[str, str]:
    rng = random.Random(SEED)
    out: dict[str, str] = {}

    groups: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        if e.event_class == "Crash":
            groups[e.attributes["youtube_id"]].append(e.clip_key)
    n_crash = sum(len(g) for g in groups.values())
    want = {HELD_OUT: round(n_crash * HELD_OUT_FRACTION), VALIDATION: round(n_crash * VALIDATION_FRACTION)}
    have = {HELD_OUT: 0, VALIDATION: 0}
    order = sorted(groups)
    rng.shuffle(order)
    for g in order:
        side = next((s for s in (HELD_OUT, VALIDATION) if have[s] < want[s]), TRAIN)
        if side != TRAIN:
            have[side] += len(groups[g])
        for k in groups[g]:
            out[k] = side

    normals = sorted(e.clip_key for e in entries if e.event_class == "Normal")
    rng.shuffle(normals)
    n_ho, n_val = round(len(normals) * HELD_OUT_FRACTION), round(len(normals) * VALIDATION_FRACTION)
    for i, k in enumerate(normals):
        out[k] = HELD_OUT if i < n_ho else VALIDATION if i < n_ho + n_val else TRAIN
    return out


def split_virat(entries: list[ManifestEntry]) -> dict[str, str]:
    return {e.clip_key: EVALUATION for e in entries}


SPLITTERS = {"ucf_crime": split_ucf_crime, "ccd": split_ccd, "virat": split_virat}


def split_csv(dataset: str, entries: list[ManifestEntry]) -> bytes:
    """The committed file: one line per clip, sorted by clip_key, LF line endings."""
    assigned = SPLITTERS[dataset](entries)
    if len(assigned) != len(entries):
        raise ValueError(f"{dataset}: {len(entries)} clips but {len(assigned)} assigned")
    lines = [CSV_HEADER]
    for e in sorted(entries, key=lambda e: e.clip_key):
        lines.append(f"{e.clip_key},{e.event_class or ''},{assigned[e.clip_key]}")
    return ("\n".join(lines) + "\n").encode("utf-8")
