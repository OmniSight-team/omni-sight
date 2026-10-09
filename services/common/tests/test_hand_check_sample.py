"""OMNI-608, D-26: the hand-check sample redraws byte for byte and keeps its strata.

Runs the loaders on the local mirror with the committed split and windows; skipped where
the mirror is absent.
"""

from collections import Counter
from pathlib import Path

import pytest
from omnisight_common.datasets import ccd, ucf_crime
from omnisight_common.datasets.hand_check import SAMPLERS, sample_csv

ROOT = Path(__file__).resolve().parents[3]
LOADERS = {"ucf_crime": ucf_crime.load, "ccd": ccd.load}

pytestmark = pytest.mark.skipif(
    not all((ROOT / "data" / d / "video_files.txt").is_file() for d in LOADERS), reason="local dataset mirror not present"
)


def rows(path: Path) -> list[list[str]]:
    return [ln.split(",") for ln in path.read_text(encoding="utf-8").splitlines()[1:]]


@pytest.fixture(scope="module")
def drawn():
    picked, split = {}, {}
    for d, load in LOADERS.items():
        split[d] = {r[0]: r[2] for r in rows(ROOT / "datasets" / "splits" / f"{d}.csv")}
        windowed = {r[0] for r in rows(ROOT / "datasets" / "windows" / f"{d}.csv") if r[2] == "positive"}
        picked[d] = SAMPLERS[d](load(ROOT / "data" / d), windowed)
    return picked, split


def test_redraw_equals_the_committed_sample(drawn):
    assert sample_csv(*drawn) == (ROOT / "datasets" / "hand_check" / "sample.csv").read_bytes()


def test_ucf_sample_has_both_sources_and_every_class(drawn):
    picked, _ = drawn
    per_source = Counter(e.annotation_source.value for e in picked["ucf_crime"])
    assert per_source == {"ucf_crime_temporal": 15, "uca": 15}
    for source in per_source:
        assert len({e.event_class for e in picked["ucf_crime"] if e.annotation_source.value == source}) == 13


def test_ccd_sample_is_30_distinct_crash_clips(drawn):
    picked, _ = drawn
    keys = [e.clip_key for e in picked["ccd"]]
    assert len(set(keys)) == 30 and all(k.startswith("Crash-1500/") for k in keys)
