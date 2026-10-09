"""The clips whose lead-up windows are checked by eye (OMNI-609), drawn once (D-26).

Phase A: "check a sample by hand". A seeded random sample, stratified:
- **UCF-Crime: 30 clips with positive windows**, 15 timed by the official annotation and
  15 by UCA (D-21), each half spread over the classes round-robin (classes in name order,
  clips shuffled within a class), so both sources and every class are represented
- **CCD: 30 crash clips**, drawn uniformly

A clip's 30 s and 60 s windows end at the same event start, so the sample is of clips.
These are also the only dataset clips loaded into the product (D-26): the window view
needs to play them. Deterministic: seed 609, inputs sorted before any random draw.
"""

import random
from collections import defaultdict

from omnisight_common.datasets import AnnotationSource, ManifestEntry

SEED = 609
UCF_PER_SOURCE = 15
CCD_SIZE = 30
SAMPLE_HEADER = "dataset,clip_key,video_relpath,event_class,annotation_source,split"


def _round_robin(by_class: dict[str, list[ManifestEntry]], n: int, rng: random.Random) -> list[ManifestEntry]:
    queues = {}
    for cls in sorted(by_class):
        clips = sorted(by_class[cls], key=lambda e: e.clip_key)
        rng.shuffle(clips)
        queues[cls] = clips
    out: list[ManifestEntry] = []
    while len(out) < n and any(queues.values()):
        for cls in sorted(queues):
            if queues[cls] and len(out) < n:
                out.append(queues[cls].pop(0))
    return out


def sample_ucf_crime(entries: list[ManifestEntry], windowed: set[str]) -> list[ManifestEntry]:
    """`windowed`: clip keys that have positive windows (OMNI-607)."""
    rng = random.Random(SEED)
    out: list[ManifestEntry] = []
    for source in (AnnotationSource.UCF_CRIME_TEMPORAL, AnnotationSource.UCA):
        by_class: dict[str, list[ManifestEntry]] = defaultdict(list)
        for e in entries:
            if e.annotation_source == source and e.clip_key in windowed:
                by_class[e.event_class].append(e)
        out += _round_robin(by_class, UCF_PER_SOURCE, rng)
    return out


def sample_ccd(entries: list[ManifestEntry], windowed: set[str]) -> list[ManifestEntry]:
    rng = random.Random(SEED)
    crashes = sorted((e for e in entries if e.clip_key in windowed), key=lambda e: e.clip_key)
    return rng.sample(crashes, CCD_SIZE)


SAMPLERS = {"ucf_crime": sample_ucf_crime, "ccd": sample_ccd}


def sample_csv(picked: dict[str, list[ManifestEntry]], split: dict[str, dict[str, str]]) -> bytes:
    lines = [SAMPLE_HEADER]
    for dataset in sorted(picked):
        for e in sorted(picked[dataset], key=lambda e: e.clip_key):
            lines.append(
                f"{dataset},{e.clip_key},{e.video_relpath},{e.event_class},{e.annotation_source.value},{split[dataset][e.clip_key]}"
            )
    return ("\n".join(lines) + "\n").encode("utf-8")
