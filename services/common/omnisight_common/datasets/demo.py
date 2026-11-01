"""The VIRAT demo sample: real surveillance footage in the product, to search (OMNI-702, D-26).

One video per scene, from the 275 VIRAT videos with events, so every camera view that can
be loaded is searchable. **Only videos the product accepts are eligible:** a file over the
upload limit (500 MB) would be refused like any upload, so it is left out before the draw.
Scenes `0000` and `0001` have no video under the limit (642-1,608 MB each), which leaves 9
scenes, 9 videos. Within a scene the video is drawn at random. Drawn once and committed
(`datasets/demo/virat_sample.csv`); SM-1 still runs on Colab over all 275.
Deterministic: seed 702, inputs sorted before any random draw.
"""

import random
from collections import defaultdict

from omnisight_common.datasets import ManifestEntry
from omnisight_common.datasets.hand_check import SAMPLE_HEADER

SEED = 702
MAX_BYTES = 500 * 1024 * 1024  # the product's upload limit (`max_upload_size_mb`)


def sample_virat(entries: list[ManifestEntry], size_bytes: dict[str, int]) -> list[ManifestEntry]:
    """`size_bytes`: file size per `video_relpath`. A video with no known size is not eligible."""
    rng = random.Random(SEED)
    by_scene: dict[str, list[ManifestEntry]] = defaultdict(list)
    for e in entries:
        if 0 < size_bytes.get(e.video_relpath, 0) <= MAX_BYTES:
            by_scene[e.attributes["scene"]].append(e)
    return [rng.choice(sorted(by_scene[s], key=lambda e: e.clip_key)) for s in sorted(by_scene)]


def sample_csv(picked: list[ManifestEntry], split: dict[str, str]) -> bytes:
    """The same columns as the hand-check sample, so the same code reads both."""
    lines = [SAMPLE_HEADER]
    for e in sorted(picked, key=lambda e: e.clip_key):
        lines.append(f"{e.dataset},{e.clip_key},{e.video_relpath},,{e.annotation_source.value},{split[e.clip_key]}")
    return ("\n".join(lines) + "\n").encode("utf-8")
