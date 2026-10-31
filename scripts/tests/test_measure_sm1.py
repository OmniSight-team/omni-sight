"""OMNI-713: SM-1's measuring code, with stand-in encoders on generated archives. No SM-1 query goes
to a model here: a stand-in returns the vector the test gave it."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest
from omnisight_common.datasets.virat import Event
from omnisight_common.fusion import ModalityClassifier

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("measure_sm1", ROOT / "scripts" / "measure_sm1.py")
sm1 = importlib.util.module_from_spec(spec)
importlib.sys.modules[spec.name] = sm1
spec.loader.exec_module(sm1)

PINS = {"frame_model_id": "f", "frame_model_revision": "1", "clip_model_id": "c", "clip_model_revision": "2"}
A = "VIRAT_S_000001_00_000000_000010"
B = "VIRAT_S_010001_00_000000_000010"
FRAME_DIM, CLIP_DIM = 8, 4


def _unit(*values: float, dim: int) -> np.ndarray:
    vector = np.zeros(dim, np.float32)
    vector[: len(values)] = values
    return vector / np.linalg.norm(vector)


def _write_video(archive: Path, key: str, frame_index: list[int], frame_vectors: np.ndarray, clip_vectors: np.ndarray) -> None:
    np.savez(
        archive / f"{key}.npz",
        frame_index=np.array(frame_index, np.int32),
        timestamp_s=np.array(frame_index, np.float64) / 30,
        frame_vectors=frame_vectors,
        clip_vectors=clip_vectors,
    )


def _write_events(dataset: Path, key: str, events: list[tuple[int, int, int]]) -> None:
    rows = [f"{i} {event_type} {end - start + 1} {start} {end} {start} 0 0 1 1" for i, (event_type, start, end) in enumerate(events)]
    (dataset / "annotations").mkdir(exist_ok=True)
    (dataset / "annotations" / f"{key}.viratdata.events.txt").write_text("\n".join(rows) + "\n")


def _manifest(archive: Path, counts: dict[str, int], *, pins=PINS, failed=None) -> None:
    (archive / "manifest.json").write_text(json.dumps({
        "pins": pins, "videos": {key: {"admitted": n} for key, n in counts.items()}, "failed": failed or {},
    }))


@pytest.fixture
def world(tmp_path):
    """Video A, scene 0000: frames 0, 10, 20, 30, 40, 50 with type 3 in frames 10-20. Video B, scene
    0100: frames 0, 10, with type 4 at frame 10. The frame list starts at B's frame 0, the clip list
    at A's frame 10, so the two lists differ."""
    archive, dataset = tmp_path / "archive", tmp_path / "dataset"
    archive.mkdir()
    dataset.mkdir()
    # Each vector's first value falls down the list, so the order is the row's.
    frames_a = np.stack([_unit(1, 0.1 * i, dim=FRAME_DIM) for i in (20, 40, 41, 42, 43, 44)])
    frames_b = np.stack([_unit(1, 0.1 * i, dim=FRAME_DIM) for i in (0, 1)])
    clips_a = np.stack([_unit(1, 0.1 * i, dim=CLIP_DIM) for i in (10, 0, 11, 12, 13, 14)])
    clips_b = np.stack([_unit(1, 0.1 * i, dim=CLIP_DIM) for i in (20, 21)])
    _write_video(archive, A, [0, 10, 20, 30, 40, 50], frames_a, clips_a)
    _write_video(archive, B, [0, 10], frames_b, clips_b)
    _write_events(dataset, A, [(3, 10, 20)])
    _write_events(dataset, B, [(4, 10, 10)])
    _manifest(archive, {A: 6, B: 2})
    return archive, dataset


RULES = {"event_type=3", "event_type=4", "scene=0000", "scene=0100"}


class Stand:
    """Returns the vector the test gave each text."""

    def __init__(self, vectors: dict[str, np.ndarray]) -> None:
        self.vectors = vectors

    def encode_texts(self, texts):
        return np.stack([self.vectors[t] for t in texts])


def _query(query_id: str, kind: str, rule: str) -> dict:
    return {"query_id": query_id, "text": query_id, "kind": kind, "answer_rule": rule}


def _classifier(z: float) -> ModalityClassifier:
    """`w_f` = sigmoid(z), whatever the vector."""
    return ModalityClassifier([0.0] * FRAME_DIM, z)


def _result(world, queries, *, z=0.0):
    archive, dataset = world
    loaded = sm1.load_archive([A, B], archive, dataset, {q["answer_rule"] for q in queries}, pins=PINS)
    top = _unit(1, 0, dim=FRAME_DIM)
    clip_top = _unit(1, 0, dim=CLIP_DIM)
    return sm1.measure(
        queries, loaded,
        Stand({q["text"]: top for q in queries}), Stand({q["text"]: clip_top for q in queries}),
        _classifier(z),
    )


def test_an_event_rule_accepts_its_own_type_both_ends_included():
    frames = np.array([9, 10, 15, 20, 21, 30])
    events = [Event(0, 3, 10, 20), Event(1, 4, 30, 40)]
    assert sm1.answer_mask("event_type=3", A, events, frames).tolist() == [False, True, True, True, False, False]
    assert sm1.answer_mask("event_type=4", A, events, frames).tolist() == [False, False, False, False, False, True]


def test_two_events_of_a_type_count_each_frame_once():
    frames = np.array([10, 15, 20])
    mask = sm1.answer_mask("event_type=3", A, [Event(0, 3, 10, 15), Event(1, 3, 15, 20)], frames)
    assert mask.sum() == 3


def test_a_scene_rule_takes_the_scene_from_the_file_name():
    frames = np.array([0, 1])
    assert sm1.answer_mask("scene=0000", A, [], frames).all()
    assert not sm1.answer_mask("scene=0000", B, [], frames).any()


def test_an_unknown_rule_is_refused():
    with pytest.raises(ValueError):
        sm1.answer_mask("colour=red", A, [], np.array([0]))


def test_the_archive_loads_whole_and_in_order(world):
    archive, dataset = world
    loaded = sm1.load_archive([A, B], archive, dataset, RULES, pins=PINS)
    assert len(loaded) == 8
    assert loaded.frame_vectors.shape == (8, FRAME_DIM)
    assert loaded.clip_vectors.shape == (8, CLIP_DIM)
    assert loaded.correct["event_type=3"].tolist() == [False, True, True, False, False, False, False, False]
    assert loaded.correct["scene=0100"].tolist() == [False] * 6 + [True, True]


def test_the_labels_need_no_vectors(world):
    archive, dataset = world
    loaded = sm1.load_archive([A, B], archive, dataset, RULES, vectors=False)
    assert loaded.frame_vectors is None
    assert loaded.correct["event_type=4"].sum() == 1


def test_an_archive_of_other_checkpoints_is_refused(world):
    archive, dataset = world
    with pytest.raises(RuntimeError, match="made with"):
        sm1.load_archive([A, B], archive, dataset, RULES, pins={**PINS, "clip_model_revision": "other"})


def test_an_archive_missing_a_video_or_with_a_failure_is_refused(world):
    archive, dataset = world
    _manifest(archive, {A: 6})
    with pytest.raises(RuntimeError, match="not whole"):
        sm1.load_archive([A, B], archive, dataset, RULES)
    _manifest(archive, {A: 6, B: 2}, failed={B: "broken"})
    with pytest.raises(RuntimeError, match="not whole"):
        sm1.load_archive([A, B], archive, dataset, RULES)


def test_a_file_disagreeing_with_the_manifest_is_refused(world):
    archive, dataset = world
    _manifest(archive, {A: 5, B: 2})
    with pytest.raises(RuntimeError, match="the manifest says 5"):
        sm1.load_archive([A, B], archive, dataset, RULES)


def test_a_rule_no_frame_meets_is_refused(world):
    archive, dataset = world
    with pytest.raises(RuntimeError, match="no frame"):
        sm1.load_archive([A, B], archive, dataset, {"event_type=12"})


def test_chance_is_five_random_frames():
    assert sm1.chance_at_5(np.array([True, False, False, False])) == pytest.approx(1 - 0.75**5)


def test_exact_search_compares_every_vector_and_keeps_five_best_first(world):
    archive, dataset = world
    loaded = sm1.load_archive([A, B], archive, dataset, RULES)
    rows, scores = sm1._exact_top(loaded.frame_vectors, _unit(1, 0, dim=FRAME_DIM))
    assert rows[0] == 6  # B's frame 0, which sits behind all of A's in the file order
    assert len(rows) == 5
    assert [scores[r] for r in rows] == sorted((scores[r] for r in rows), reverse=True)


def test_equal_scores_come_out_by_row():
    vectors = np.stack([_unit(1, 0, dim=2)] * 7)
    assert sm1._exact_top(vectors, _unit(1, 0, dim=2))[0] == [0, 1, 2, 3, 4]


BOTH_KINDS = [_query("a", "action", "event_type=3"), _query("s", "scene", "scene=0100")]


def test_each_mode_gets_its_own_list(world):
    row = _result(world, BOTH_KINDS)["queries"][0]
    frame_hits = [(h["clip_key"], h["frame_index"]) for h in row["modes"]["frame"]["hits"]]
    clip_hits = [(h["clip_key"], h["frame_index"]) for h in row["modes"]["clip"]["hits"]]
    assert frame_hits[0] == (B, 0)
    assert clip_hits[0] == (A, 10)
    assert row["modes"]["clip"]["found"] is True
    assert row["modes"]["clip"]["first_correct_rank"] == 1
    assert row["modes"]["clip"]["hits"][0]["correct"] is True


def test_fused_mixes_the_lists_by_rank_with_the_classifiers_weights(world):
    # All the weight on the clip list: fused equals the clip list, in B.3's scores.
    row = _result(world, BOTH_KINDS, z=-50.0)["queries"][0]
    assert [h["frame_index"] for h in row["modes"]["fused"]["hits"]] == [h["frame_index"] for h in row["modes"]["clip"]["hits"]]
    assert row["modes"]["fused"]["hits"][0]["score"] == pytest.approx(row["w_c"] / 61)
    assert row["w_c"] == pytest.approx(1.0)


def test_fused_equal_ignores_the_classifier(world):
    to_frame = _result(world, BOTH_KINDS, z=50.0)["queries"][0]["modes"]["fused_equal"]
    to_clip = _result(world, BOTH_KINDS, z=-50.0)["queries"][0]["modes"]["fused_equal"]
    assert to_frame == to_clip


def _row(kind: str, frame: bool, clip: bool, fused: bool, equal: bool = False, chance: float = 0.1) -> dict:
    return {
        "kind": kind,
        "chance": chance,
        "modes": {"frame": {"found": frame}, "clip": {"found": clip}, "fused": {"found": fused}, "fused_equal": {"found": equal}},
    }


def test_recall_is_counted_overall_and_per_kind():
    summary = sm1.summarise([_row("action", False, True, True), _row("action", False, False, False), _row("scene", True, False, True), _row("scene", True, True, True)])
    assert summary["recall_at_5"] == 0.75
    assert summary["baseline"] == 0.5
    assert summary["by_kind"]["action"]["fused"] == 0.5
    assert summary["by_kind"]["action"]["frame"] == 0.0
    assert summary["by_kind"]["scene"]["clip"] == 0.5
    assert summary["overall"]["chance"] == pytest.approx(0.1)
    assert summary["action_lift"] == 0.5


def test_pass_needs_the_target_and_the_lift():
    action_lifts = [_row("action", False, True, True)] + [_row("scene", True, True, True)] * 9
    assert sm1.summarise(action_lifts)["passed"] is True
    no_lift = [_row("action", True, True, True)] + [_row("scene", True, True, True)] * 9
    assert sm1.summarise(no_lift)["passed"] is False
    below_target = [_row("action", False, True, True)] + [_row("scene", True, True, True)] * 3 + [_row("scene", True, True, False)]
    assert sm1.summarise(below_target)["recall_at_5"] == 0.8
    assert sm1.summarise(below_target)["passed"] is False


def test_exactly_the_target_passes():
    rows = [_row("action", False, True, True)] * 17 + [_row("scene", True, True, False)] * 3
    assert sm1.summarise(rows)["recall_at_5"] == pytest.approx(0.85)
    assert sm1.summarise(rows)["passed"] is True


def test_the_result_says_what_it_ran_on_and_is_json(world):
    result = _result(world, BOTH_KINDS)
    assert result["n_queries"] == 2
    assert result["frames"] == 8
    assert result["videos"] == 2
    assert result["measured_at"]
    assert json.loads(json.dumps(result))["queries"][1]["answer_rule"] == "scene=0100"


def test_the_committed_set_is_what_a_run_reads():
    queries = sm1.read_queries()
    assert len(queries) == 50
    assert len(sm1.file_sha256(sm1.QUERIES)) == 64
