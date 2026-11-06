"""The backfill's choice of points (D-43, D-44), on made-up payloads."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backfill_search_payload as backfill

VIRAT_10 = (("dataset", "virat"), ("footage", "video:10"))
UPLOAD_20 = (("dataset", None), ("footage", "video:20"))
CAMERA_7 = (("dataset", None), ("footage", "camera:7"))


def test_each_point_gets_its_dataset_and_footage():
    points = [
        (1, {"video_id": 10}),  # dataset clip, nothing yet
        (2, {"video_id": 20}),  # plain upload, no footage yet
        (3, {"camera_id": 7}),  # camera frame (`video_id` null, so missing), no footage yet
        (4, {"video_id": 10, "dataset": "virat", "footage": "video:10"}),  # already right
        (5, {"video_id": 20, "footage": "video:20"}),  # already right: no `dataset` key = null
        (6, {"video_id": 10, "footage": "video:10"}),  # dataset missing
        (7, {"video_id": 20, "dataset": "ccd", "footage": "video:20"}),  # no longer a dataset clip
    ]
    todo = backfill.changes(points, {10: "virat"})
    assert todo == {VIRAT_10: [1, 6], UPLOAD_20: [2, 7], CAMERA_7: [3]}


def test_a_second_run_changes_nothing():
    points = [(1, {"video_id": 10}), (2, {"video_id": 20, "dataset": "virat"}), (3, {"camera_id": 7})]
    dataset_of = {10: "ccd"}
    todo = backfill.changes(points, dataset_of)
    values_of = {i: dict(values) for values, ids in todo.items() for i in ids}
    after = [(i, backfill.applied(p, values_of[i]) if i in values_of else p) for i, p in points]
    assert after[1][1] == {"video_id": 20, "footage": "video:20"}  # the wrong dataset is deleted
    assert backfill.changes(after, dataset_of) == {}
