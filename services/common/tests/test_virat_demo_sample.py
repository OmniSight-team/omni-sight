"""OMNI-702, D-26: the VIRAT demo sample redraws byte for byte, one loadable video per scene.

Runs the VIRAT loader on the local mirror's listing and annotations, with the committed
split and OMNI-608's probe of Drive for the sizes; skipped where those are absent.
"""

import csv
from pathlib import Path

import pytest
from omnisight_common.datasets import virat
from omnisight_common.datasets.demo import MAX_BYTES, sample_csv, sample_virat

ROOT = Path(__file__).resolve().parents[3]
PROBE = ROOT / "data" / "omni608_estimate.csv"

pytestmark = pytest.mark.skipif(
    not ((ROOT / "data" / "virat" / "video_files.txt").is_file() and PROBE.is_file()),
    reason="local dataset mirror or OMNI-608's probe not present",
)


@pytest.fixture(scope="module")
def drawn():
    with PROBE.open(encoding="utf-8") as f:
        sizes = {r["video_relpath"]: int(r["size_bytes"]) for r in csv.DictReader(f) if r["dataset"] == "virat"}
    split = {
        ln.split(",")[0]: ln.split(",")[2]
        for ln in (ROOT / "datasets" / "splits" / "virat.csv").read_text(encoding="utf-8").splitlines()[1:]
    }
    entries = virat.load(ROOT / "data" / "virat")
    return entries, sample_virat(entries, sizes), sizes, split


def test_redraw_equals_the_committed_sample(drawn):
    _, picked, _, split = drawn
    assert sample_csv(picked, split) == (ROOT / "datasets" / "demo" / "virat_sample.csv").read_bytes()


def test_one_video_per_scene_every_one_under_the_upload_limit(drawn):
    entries, picked, sizes, _ = drawn
    scenes = [e.attributes["scene"] for e in picked]
    assert len(scenes) == len(set(scenes)) == 9
    assert all(sizes[e.video_relpath] <= MAX_BYTES for e in picked)
    # The two scenes left out have no video the product would accept.
    left_out = {e.attributes["scene"] for e in entries} - set(scenes)
    assert left_out == {"0000", "0001"}
    assert all(sizes[e.video_relpath] > MAX_BYTES for e in entries if e.attributes["scene"] in left_out)


def test_a_video_over_the_limit_or_of_unknown_size_is_never_drawn(drawn):
    entries, _, sizes, _ = drawn
    scene_0002 = [e for e in entries if e.attributes["scene"] == "0002"]
    too_big = {e.video_relpath: MAX_BYTES + 1 for e in scene_0002}
    assert all(e.attributes["scene"] != "0002" for e in sample_virat(entries, {**sizes, **too_big}))
    unknown = {k: v for k, v in sizes.items() if k not in {e.video_relpath for e in scene_0002}}
    assert all(e.attributes["scene"] != "0002" for e in sample_virat(entries, unknown))
