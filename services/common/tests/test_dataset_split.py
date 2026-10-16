"""OMNI-605: the split is reproducible to the byte, and keeps its rules.

Runs the loaders on the local mirror (`data/`, with each dataset's `video_files.txt`) and
compares with the committed `datasets/splits/*.csv`. Skipped where the mirror is absent.
"""

from collections import defaultdict
from pathlib import Path

import pytest
from omnisight_common.datasets import ccd, ucf_crime, virat
from omnisight_common.datasets.split import (
    EVALUATION,
    HELD_OUT,
    TRAIN,
    VALIDATION,
    split_csv,
)

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
SPLITS = ROOT / "datasets" / "splits"
LOADERS = {"ucf_crime": ucf_crime.load, "ccd": ccd.load, "virat": virat.load}

pytestmark = pytest.mark.skipif(
    not all((DATA / d / "video_files.txt").is_file() for d in LOADERS), reason="local dataset mirror not present"
)


@pytest.fixture(scope="module")
def entries():
    return {d: load(DATA / d) for d, load in LOADERS.items()}


def rows(data: bytes) -> list[list[str]]:
    return [ln.split(",") for ln in data.decode("utf-8").splitlines()[1:]]


@pytest.mark.parametrize("dataset", list(LOADERS))
def test_rebuilding_gives_the_committed_file_byte_for_byte(entries, dataset):
    first = split_csv(dataset, entries[dataset])
    assert split_csv(dataset, entries[dataset]) == first
    assert (SPLITS / f"{dataset}.csv").read_bytes() == first


def test_ucf_held_out_is_exactly_the_official_test_list(entries):
    split = {k: s for k, _, s in rows(split_csv("ucf_crime", entries["ucf_crime"]))}
    official = {e.clip_key: e.attributes["official_list"] for e in entries["ucf_crime"]}
    assert {k for k, s in split.items() if s == HELD_OUT} == {k for k, o in official.items() if o == "test"}
    assert all(official[k] == "train" for k, s in split.items() if s in (TRAIN, VALIDATION))


def test_ucf_every_class_has_validation_videos(entries):
    per_class = defaultdict(set)
    for _, c, s in rows(split_csv("ucf_crime", entries["ucf_crime"])):
        per_class[c].add(s)
    assert all(VALIDATION in s and TRAIN in s and HELD_OUT in s for s in per_class.values())


def test_ccd_no_source_video_on_two_sides(entries):
    split = {k: s for k, _, s in rows(split_csv("ccd", entries["ccd"]))}
    sides = defaultdict(set)
    for e in entries["ccd"]:
        if e.event_class == "Crash":
            sides[e.attributes["youtube_id"]].add(split[e.clip_key])
    assert all(len(s) == 1 for s in sides.values())


def test_ccd_crash_and_normal_both_in_every_split(entries):
    seen = {(c, s) for _, c, s in rows(split_csv("ccd", entries["ccd"]))}
    assert seen == {(c, s) for c in ("Crash", "Normal") for s in (TRAIN, VALIDATION, HELD_OUT)}


def test_virat_is_evaluation_only(entries):
    assert {s for _, _, s in rows(split_csv("virat", entries["virat"]))} == {EVALUATION}
