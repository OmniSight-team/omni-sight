"""The import's selection and checks (K-27), on made-up ids and vectors."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import import_frame_vectors as imp


def test_a_segment_that_already_has_a_point_is_left_alone():
    store, unknown = imp.new_points(np.array([1, 2, 3]), {2}, {1: "job", 2: "job", 3: "job"})
    assert store == [1, 3] and unknown == []


def test_a_segment_with_no_job_is_reported_and_not_stored():
    store, unknown = imp.new_points(np.array([1, 2]), set(), {1: "job"})
    assert store == [1] and unknown == [2]


def test_vectors_must_be_unit_length_and_the_right_size():
    ids = np.array([1, 2])
    unit = np.eye(4, dtype=np.float32)[:2]
    imp.check_vectors("v", ids, unit, 4)
    with pytest.raises(ValueError):
        imp.check_vectors("v", ids, unit * 2, 4)
    with pytest.raises(ValueError):
        imp.check_vectors("v", ids, unit, 5)
    with pytest.raises(ValueError):
        imp.check_vectors("v", np.array([1, 1]), unit, 4)


def test_another_frame_model_is_refused():
    pins = {"frame_model_id": "a", "frame_model_revision": "1"}
    imp.check_pins(pins, "a", "1")
    with pytest.raises(ValueError):
        imp.check_pins(pins, "a", "2")
