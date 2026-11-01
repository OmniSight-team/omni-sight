"""The arithmetic of TC-4's measuring script (OMNI-715), on made-up numbers."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import measure_tc4


def test_percentile_is_the_nearest_rank():
    values = [float(n) for n in range(1, 101)]
    assert measure_tc4.percentile(values, 0.5) == 50.0
    assert measure_tc4.percentile(values, 0.95) == 95.0
    assert measure_tc4.percentile([3.0], 0.95) == 3.0


def test_latency_stats_reports_the_max():
    stats = measure_tc4.latency_stats([0.2, 0.1, 2.9])
    assert stats["max"] == 2.9 and stats["n"] == 3 and stats["p50"] == 0.2


def test_recall_is_the_share_found():
    assert measure_tc4.recall([True, True, False, True]) == 0.75


def test_pass_needs_both_the_recall_and_every_query_under_three_seconds():
    assert measure_tc4.verdict(0.85, 2.99)
    assert not measure_tc4.verdict(0.84, 1.0)
    assert not measure_tc4.verdict(0.9, 3.0)
