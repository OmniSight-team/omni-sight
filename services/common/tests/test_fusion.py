"""Algorithm 3 (OMNI-711) on hand-made ranked lists: B.3's arithmetic, a missing rank, equal
weights, ties; and the classifier's weights."""

import json
from pathlib import Path

import pytest
from omnisight_common.fusion import (
    CLASSIFIER_FILE,
    K0,
    FusedHit,
    ModalityClassifier,
    fuse,
)
from omnisight_common.settings import CommonSettings


def test_the_tuned_weights_go_by_what_the_classifier_says_the_query_is():
    from omnisight_common.fusion import tuned_weights

    assert tuned_weights(0.8) == (0.5, 0.5)
    assert tuned_weights(0.5) == (0.5, 0.5)
    assert tuned_weights(0.2) == pytest.approx((0.6, 0.4))


def test_k0_is_b3s():
    assert K0 == 60


def test_the_arithmetic_of_b3_line_8():
    hits = fuse([1, 2], [2, 3], 0.7, 0.3, k=5)

    scores = {hit.segment_id: hit.score for hit in hits}
    assert scores[1] == pytest.approx(0.7 / 61)
    assert scores[2] == pytest.approx(0.7 / 62 + 0.3 / 61)
    assert scores[3] == pytest.approx(0.3 / 62)
    assert [hit.segment_id for hit in hits] == [2, 1, 3]


def test_a_missing_rank_adds_nothing_and_is_labelled():
    hits = {hit.segment_id: hit for hit in fuse([1, 2], [2, 3], 0.5, 0.5, k=5)}

    assert hits[1] == FusedHit(1, 0.5 / 61, 1, None)
    assert hits[3] == FusedHit(3, 0.5 / 62, None, 2)
    assert (hits[1].matched_by, hits[2].matched_by, hits[3].matched_by) == ("frame", "both", "clip")


def test_equal_weights_reward_being_in_both_lists():
    # 3 is last in both lists, yet beats the first of either: 2 x 0.5/63 > 0.5/61.
    hits = fuse([1, 3], [2, 3], 0.5, 0.5, k=5)

    assert hits[0].segment_id == 3


def test_ties_come_out_by_segment_id():
    # The two tops, same rank, same weight.
    assert [hit.segment_id for hit in fuse([9], [4], 0.5, 0.5, k=5)] == [4, 9]
    assert [hit.segment_id for hit in fuse([4], [9], 0.5, 0.5, k=5)] == [4, 9]


def test_only_the_top_k_of_the_merged_list_is_returned():
    assert [hit.segment_id for hit in fuse([1, 2, 3], [4, 5, 6], 0.9, 0.1, k=2)] == [1, 2]


def test_the_weights_decide_which_list_wins():
    assert fuse([1], [2], 0.9, 0.1, k=1)[0].segment_id == 1
    assert fuse([1], [2], 0.1, 0.9, k=1)[0].segment_id == 2


def test_an_empty_list_leaves_the_other_alone():
    assert [(h.segment_id, h.matched_by) for h in fuse([], [7, 8], 0.5, 0.5, k=5)] == [(7, "clip"), (8, "clip")]
    assert fuse([], [], 0.5, 0.5, k=5) == []


def test_weights_are_a_softmax_that_sums_to_one():
    classifier = ModalityClassifier([2.0, 0.0], 0.0)

    w_f, w_c = classifier.weights([1.0, 0.0])
    assert w_f + w_c == pytest.approx(1.0)
    assert w_f == pytest.approx(0.8807970779778825)
    assert classifier.weights([0.0, 1.0]) == (0.5, 0.5)


def test_a_vector_of_the_wrong_size_is_refused():
    with pytest.raises(ValueError):
        ModalityClassifier([1.0, 0.0], 0.0).weights([1.0])


def test_a_classifier_of_another_encoder_is_refused(tmp_path: Path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"model": "m", "model_revision": "r", "coefficients": [1.0], "intercept": 0.0}))

    assert ModalityClassifier.load("m", "r", path).weights([0.0]) == (0.5, 0.5)
    with pytest.raises(ValueError):
        ModalityClassifier.load("m", "other", path)


def test_the_committed_classifier_is_for_the_pinned_text_encoder():
    fields = CommonSettings.model_fields
    classifier = ModalityClassifier.load(fields["frame_model_id"].default, fields["frame_model_revision"].default)

    assert len(classifier.coefficients) == 1152
    assert CLASSIFIER_FILE.stat().st_size < 100_000
