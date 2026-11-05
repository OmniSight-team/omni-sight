"""OMNI-X02 (D-42): the box detector's prompts from a search query, and the label shown."""

import pytest
from omnisight_common.box_prompts import label_for, prompts_for


@pytest.mark.parametrize(
    ("query", "prompts"),
    [
        ("a blue car", ["a blue car", "car"]),
        ("a person walking", ["a person walking", "person"]),
        ("a white truck", ["a white truck", "car"]),
        ("a person opening a trunk", ["a person opening a trunk", "person"]),
        ("A Man and a Woman near a VAN", ["A Man and a Woman near a VAN", "person", "car"]),
        ("someone riding a bike with a bag", ["someone riding a bike with a bag", "bicycle", "bag"]),
        ("  people  ", ["people", "person"]),
        ("a dog running", ["a dog running"]),
        ("   ", []),
    ],
)
def test_the_query_as_typed_then_its_object_words(query, prompts):
    assert prompts_for(query) == prompts


def test_only_whole_words_count():
    assert prompts_for("a scarf and a caravan") == ["a scarf and a caravan"]


def test_a_box_found_by_the_whole_query_is_labelled_with_its_object_word():
    prompts = ["a blue car", "car"]
    assert label_for("a blue car", prompts) == "car"
    assert label_for("car", prompts) == "car"


def test_a_query_with_no_object_word_labels_its_boxes_with_itself():
    assert label_for("a dog running", ["a dog running"]) == "a dog running"
