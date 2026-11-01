"""OMNI-709: the SM-1 query set and the classifier's training set, and the coverage count."""

import csv
import importlib.util
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from omnisight_common.datasets.virat import EVENT_TYPES, Event

ROOT = Path(__file__).resolve().parents[2]
DIGGING = 8  # no event of this type in the 275 videos, so no query can have an answer
SCENES = {"0000", "0001", "0002", "0100", "0101", "0102", "0400", "0401", "0500", "0502", "0503"}


def _rows(name: str) -> list[dict]:
    with open(ROOT / "datasets" / "eval" / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


spec = importlib.util.spec_from_file_location("virat_event_coverage", ROOT / "scripts" / "virat_event_coverage.py")
coverage_script = importlib.util.module_from_spec(spec)
importlib.sys.modules[spec.name] = coverage_script
spec.loader.exec_module(coverage_script)


def test_25_action_and_25_scene_queries_with_unique_ids_and_texts():
    rows = _rows("sm1_queries.csv")
    assert Counter(r["kind"] for r in rows) == {"action": 25, "scene": 25}
    assert len({r["query_id"] for r in rows}) == len({r["text"] for r in rows}) == 50


def test_every_rule_names_a_real_answer():
    for row in _rows("sm1_queries.csv"):
        key, value = row["answer_rule"].split("=")
        if row["kind"] == "action":
            assert key == "event_type" and int(value) in EVENT_TYPES and int(value) != DIGGING
        else:
            assert key == "scene" and value in SCENES


def test_action_queries_cover_every_event_type_with_about_two_wordings():
    counts = Counter(int(r["answer_rule"].split("=")[1]) for r in _rows("sm1_queries.csv") if r["kind"] == "action")
    assert set(counts) == set(EVENT_TYPES) - {DIGGING}
    assert all(2 <= n <= 3 for n in counts.values())


def test_scene_queries_cover_every_scene_two_or_three_times():
    counts = Counter(r["answer_rule"].split("=")[1] for r in _rows("sm1_queries.csv") if r["kind"] == "scene")
    assert set(counts) == SCENES
    assert all(2 <= n <= 3 for n in counts.values())


def test_the_classifier_trains_on_none_of_the_test_queries():
    def norm(text: str) -> str:
        return re.sub(r"\W+", " ", text.lower()).strip()

    rows = _rows("modality_train.csv")
    assert Counter(r["label"] for r in rows) == {"scene": 50, "action": 50}
    train = {norm(r["text"]) for r in rows}
    assert len(train) == len(rows)
    assert not train & {norm(r["text"]) for r in _rows("sm1_queries.csv")}


def test_coverage_counts_an_event_with_a_frame_inside_both_ends_included():
    coverage = coverage_script.Coverage()
    events = [
        Event(event_id=0, event_type=3, start_frame=10, end_frame=20),  # holds frame 20, its last
        Event(event_id=1, event_type=3, start_frame=21, end_frame=29),  # holds none
        Event(event_id=2, event_type=9, start_frame=0, end_frame=30),  # holds both, one for motion
    ]
    coverage.add_video("VIRAT_S_050201_05_000890_000944", events, np.array([20, 30]), np.array(["heartbeat", "motion"]))
    assert (coverage.types[3].events, coverage.types[3].with_admitted, coverage.types[3].with_motion) == (2, 1, 0)
    assert (coverage.types[9].events, coverage.types[9].with_admitted, coverage.types[9].with_motion) == (1, 1, 1)
    assert coverage.frames_per_scene == {"0502": 2}


def test_a_frame_inside_two_events_of_a_type_counts_once():
    coverage = coverage_script.Coverage()
    events = [Event(0, 9, 0, 10), Event(1, 9, 5, 15)]
    coverage.add_video("VIRAT_S_000001", events, np.array([7, 100]), np.array(["heartbeat", "heartbeat"]))
    assert coverage.types[9].frames_correct == 1
    result = coverage_script.report(coverage)
    assert result["types"][9]["share_of_frames"] == 0.5
    assert result["types"][9]["chance_at_5"] == pytest.approx(1 - 0.5**5)
    assert DIGGING in result["types_without_events"]
