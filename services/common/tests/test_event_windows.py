"""OMNI-607: lead-up windows are cut as D-24 says, and the export is reproducible.

The rule tests build tiny manifests by hand. The last test rebuilds the committed
`datasets/windows/*.csv` from the local mirror byte for byte; it is skipped where the
mirror or its `video_probe.csv` is absent.
"""

from pathlib import Path

import pytest
from omnisight_common.datasets import AnnotationSource, ManifestEntry, ccd, ucf_crime
from omnisight_common.datasets.windows import (
    DERIVERS,
    EVENT_AT_ZERO,
    EVENT_PAST_END,
    NEGATIVE,
    POSITIVE,
    SECOND_INTERVAL,
    UNTIMED,
    Probe,
    derive_ccd,
    derive_ucf_crime,
    off_rate,
    read_probes,
    skipped_csv,
    windows_csv,
)
from omnisight_common.domain import Domain

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"


def ucf(key, source, start=None, end=None, **attributes):
    cls = "Normal" if source == AnnotationSource.NORMAL else "Robbery"
    return ManifestEntry("ucf_crime", key, Domain.SURVEILLANCE, cls, start, end, source, f"videos/{key}", attributes)


def crash(key, start, youtube_id="y1"):
    return ManifestEntry(
        "ccd", f"Crash-1500/{key}", Domain.TRAFFIC, "Crash", start, 5.0, AnnotationSource.CCD_BINLABELS,
        f"videos/Crash-1500/{key}.mp4", {"youtube_id": youtube_id},
    )


def normal_ccd(key):
    return ManifestEntry(
        "ccd", f"Normal/{key}", Domain.TRAFFIC, "Normal", None, None, AnnotationSource.NORMAL, f"videos/Normal/{key}.mp4"
    )


def probes_for(entries, duration=300.0, fps=30.0):
    return {e.video_relpath: Probe(fps, round(duration * fps), duration) for e in entries}


def test_positive_window_ends_where_the_event_starts_for_30_and_60_s():
    e = ucf("a.mp4", AnnotationSource.UCF_CRIME_TEMPORAL, 100.0, 120.0)
    windows, skipped = derive_ucf_crime([e], {"a.mp4": "held_out"}, probes_for([e]))
    assert skipped == []
    assert sorted((w.nominal_length_s, w.window_start_s, w.window_end_s) for w in windows) == [
        (30.0, 70.0, 100.0), (60.0, 40.0, 100.0)
    ]
    assert all(w.kind == POSITIVE and w.window_end_s <= e.event_start_s and not w.shortened for w in windows)
    assert all(w.split == "held_out" and w.event_class == "Robbery" for w in windows)


def test_too_little_footage_shortens_the_window_and_flags_it():
    e = ucf("a.mp4", AnnotationSource.UCA, 45.0, 50.0)
    windows, _ = derive_ucf_crime([e], {"a.mp4": "train"}, probes_for([e]))
    by_l = {w.nominal_length_s: w for w in windows}
    assert (by_l[30.0].window_start_s, by_l[30.0].shortened) == (15.0, False)
    assert (by_l[60.0].window_start_s, by_l[60.0].window_end_s, by_l[60.0].length_s) == (0.0, 45.0, 45.0)
    assert by_l[60.0].shortened


def test_second_interval_is_skipped_and_counted_per_length():
    e = ucf("a.mp4", AnnotationSource.UCF_CRIME_TEMPORAL, 100.0, 110.0, second_interval=[130.0, 140.0])
    windows, skipped = derive_ucf_crime([e], {"a.mp4": "held_out"}, probes_for([e]))
    assert len(windows) == 2 and all(w.window_end_s == 100.0 for w in windows)
    assert sorted((k.interval, k.nominal_length_s, k.reason) for k in skipped) == [
        (2, 30.0, SECOND_INTERVAL), (2, 60.0, SECOND_INTERVAL)
    ]


@pytest.mark.parametrize(
    ("source", "start", "reason"),
    [
        (AnnotationSource.UNTIMED, None, UNTIMED),
        (AnnotationSource.UCF_CRIME_TEMPORAL, 0.0, EVENT_AT_ZERO),
        (AnnotationSource.UCA, 301.0, EVENT_PAST_END),
    ],
)
def test_an_event_without_a_window_has_a_reason(source, start, reason):
    e = ucf("a.mp4", source, start, None if start is None else start + 5)
    windows, skipped = derive_ucf_crime([e], {"a.mp4": "train"}, probes_for([e], duration=300.0))
    assert windows == []
    assert [(k.interval, k.nominal_length_s, k.reason) for k in skipped] == [(1, 30.0, reason), (1, 60.0, reason)]


def test_negative_windows_sit_inside_the_video_in_its_own_split():
    normals = [ucf(f"n{i}.mp4", AnnotationSource.NORMAL) for i in range(20)]
    split = {e.clip_key: ("validation" if i % 2 else "train") for i, e in enumerate(normals)}
    windows, skipped = derive_ucf_crime(normals, split, probes_for(normals, duration=90.0))
    assert skipped == [] and len(windows) == 40
    for w in windows:
        assert w.kind == NEGATIVE and w.event_class == "Normal" and w.split == split[w.clip_key]
        assert 0 <= w.window_start_s and w.window_end_s <= 90.0 and w.length_s == w.nominal_length_s
    assert len({w.window_start_s for w in windows}) > 1  # positions are drawn, not fixed


def test_negative_window_in_a_short_video_is_the_whole_video_flagged():
    e = ucf("n.mp4", AnnotationSource.NORMAL)
    windows, _ = derive_ucf_crime([e], {"n.mp4": "train"}, probes_for([e], duration=40.0))
    by_l = {w.nominal_length_s: w for w in windows}
    assert not by_l[30.0].shortened
    assert (by_l[60.0].window_start_s, by_l[60.0].window_end_s, by_l[60.0].shortened) == (0.0, 40.0, True)


def test_derivation_is_deterministic_and_order_free():
    entries = [ucf(f"n{i}.mp4", AnnotationSource.NORMAL) for i in range(10)]
    entries += [ucf("a.mp4", AnnotationSource.UCA, 80.0, 90.0)]
    split = {e.clip_key: "train" for e in entries}
    first = windows_csv(derive_ucf_crime(entries, split, probes_for(entries))[0])
    assert windows_csv(derive_ucf_crime(list(reversed(entries)), split, probes_for(entries))[0]) == first


def test_ccd_one_window_from_the_first_frame_to_the_accident_never_30_or_60_s():
    entries = [crash("000001", 3.2), crash("000002", 4.1)]
    windows, skipped = derive_ccd(entries, {e.clip_key: "train" for e in entries}, probes_for(entries, 5.0, 10.0))
    assert skipped == []
    assert [(w.nominal_length_s, w.window_start_s, w.window_end_s, w.shortened) for w in windows] == [
        (None, 0.0, 3.2, False), (None, 0.0, 4.1, False)
    ]


def test_ccd_normals_take_lengths_from_crash_windows_of_their_own_split():
    entries = [crash("000001", 3.2), crash("000002", 4.7)] + [normal_ccd(f"{i:06d}") for i in range(1, 11)]
    split = {e.clip_key: "train" for e in entries} | {"Crash-1500/000002": "validation", "Normal/000010": "validation"}
    windows, _ = derive_ccd(entries, split, probes_for(entries, 5.0, 10.0))
    for w in (w for w in windows if w.kind == NEGATIVE):
        assert w.length_s == (4.7 if w.split == "validation" else 3.2)
        assert w.nominal_length_s is None and 0 <= w.window_start_s and w.window_end_s <= 5.0


def test_videos_off_the_label_rate_are_reported():
    entries = [ucf("a.mp4", AnnotationSource.NORMAL), ucf("b.mp4", AnnotationSource.NORMAL)]
    probes = probes_for(entries) | {"videos/b.mp4": Probe(25.0, 250, 10.0)}
    assert off_rate(entries, probes, "ucf_crime") == [("b.mp4", 25.0)]


def test_a_video_without_a_probe_or_with_a_failed_probe_stops_the_derivation(tmp_path):
    e = ucf("a.mp4", AnnotationSource.NORMAL)
    with pytest.raises(ValueError, match="has no probe"):
        derive_ucf_crime([e], {"a.mp4": "train"}, {})
    (tmp_path / "video_probe.csv").write_text(
        "video_relpath,fps,frames,duration_s,error\nvideos/a.mp4,,,,missing\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="could not be probed"):
        read_probes(tmp_path)


LOADERS = {"ucf_crime": ucf_crime.load, "ccd": ccd.load}


@pytest.mark.skipif(
    not all((DATA / d / "video_probe.csv").is_file() for d in LOADERS)
    or not all((ROOT / "datasets" / "windows" / f"{d}.csv").is_file() for d in LOADERS),
    reason="local mirror, its probes or the exported windows not present",
)
@pytest.mark.parametrize("dataset", list(LOADERS))
def test_rebuilding_gives_the_committed_files_byte_for_byte(dataset):
    lines = (ROOT / "datasets" / "splits" / f"{dataset}.csv").read_text(encoding="utf-8").splitlines()[1:]
    split = {k: s for k, _, s in (ln.split(",") for ln in lines)}
    windows, skipped = DERIVERS[dataset](LOADERS[dataset](DATA / dataset), split, read_probes(DATA / dataset))
    assert (ROOT / "datasets" / "windows" / f"{dataset}.csv").read_bytes() == windows_csv(windows)
    assert (ROOT / "datasets" / "windows" / f"{dataset}_skipped.csv").read_bytes() == skipped_csv(skipped)
