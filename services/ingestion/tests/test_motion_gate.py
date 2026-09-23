"""OMNI-304: Algorithm 1, the grid-cell motion gate.

Same loading trick as test_extraction_pipeline.py (see its docstring):
pipeline.py is loaded by file path under its own name, because ingestion and
query both have a top-level package called `app`.

Two levels: exact, hand-built numpy frames for the gate's own arithmetic
(buffering, grid, threshold, blur), then a real encoded video through
extract_file for the ticket's own acceptance criterion — a clip that is still
and then moves.
"""

import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

_spec = importlib.util.spec_from_file_location(
    "omnisight_ingestion_pipeline_motion",
    Path(__file__).resolve().parents[1] / "app" / "pipeline.py",
)
pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pipeline)


def _solid(value: int, size: int = 200) -> np.ndarray:
    return np.full((size, size, 3), value, dtype=np.uint8)


def _gate(**overrides) -> "pipeline.MotionGate":
    args = {
        "grid_size": 4,
        "cell_threshold": 25.0,
        "min_active_cells": 1,
        "buffer_frames": 2,
        "blur_kernel": 1,  # ksize (1,1): GaussianBlur is a no-op, for exact arithmetic
    }
    args.update(overrides)
    return pipeline.MotionGate(**args)


# ---------------------------------------------------------------------------
# Exact arithmetic, hand-built frames
# ---------------------------------------------------------------------------


def test_the_first_buffer_frames_evaluations_are_not_scored_yet():
    gate = _gate(buffer_frames=3)

    decisions = [gate.evaluate(_solid(100)) for _ in range(3)]

    assert all(d.motion_score is None and d.admitted is False for d in decisions)


def test_scoring_starts_on_the_call_right_after_the_buffer_fills():
    gate = _gate(buffer_frames=3)
    for _ in range(3):
        gate.evaluate(_solid(100))

    decision = gate.evaluate(_solid(100))

    assert decision.motion_score is not None


def test_two_identical_frames_after_warmup_score_zero_and_are_not_admitted():
    gate = _gate(buffer_frames=2, min_active_cells=1)
    gate.evaluate(_solid(100))
    gate.evaluate(_solid(100))

    decision = gate.evaluate(_solid(100))

    assert decision.motion_score == 0.0
    assert decision.admitted is False


def test_compares_against_the_frame_buffer_frames_back_not_the_one_before():
    """buffer_frames=2: the 3rd call must compare against the 1st call's
    frame, not the 2nd. Frame 2 is made very different from frames 1 and 3 on
    purpose — comparing against it (the immediately-preceding frame) would
    show heavy motion; comparing against frame 1, as the design requires,
    shows none."""
    gate = _gate(buffer_frames=2, min_active_cells=1)
    gate.evaluate(_solid(30))  # frame 1 — this is what frame 3 must be compared to
    gate.evaluate(_solid(220))  # frame 2 — a decoy, very different from both neighbours

    decision = gate.evaluate(_solid(30))  # frame 3, identical to frame 1

    assert decision.motion_score == 0.0
    assert decision.admitted is False


def test_a_cell_counts_as_changed_only_past_the_threshold():
    frame_a = _solid(100)
    frame_b = frame_a.copy()
    frame_b[0:50, 0:50] = 100 + 20  # one cell, diff 20 — below the threshold below

    gate = _gate(grid_size=4, cell_threshold=25.0, min_active_cells=1)
    gate.evaluate(frame_a)
    gate.evaluate(frame_a)
    below = gate.evaluate(frame_b)

    gate2 = _gate(grid_size=4, cell_threshold=15.0, min_active_cells=1)
    gate2.evaluate(frame_a)
    gate2.evaluate(frame_a)
    above = gate2.evaluate(frame_b)

    assert below.motion_score == 0.0 and below.admitted is False
    assert above.motion_score == 1.0 and above.admitted is True


def test_motion_score_is_the_count_of_changed_cells_independent_of_min_active_cells():
    frame_a = _solid(100, size=200)
    frame_b = frame_a.copy()
    frame_b[0:50, 0:50] = 220  # cell (0,0)
    frame_b[0:50, 150:200] = 220  # cell (0,3) — two of the sixteen 4x4 cells

    gate = _gate(grid_size=4, cell_threshold=25.0, min_active_cells=5)
    gate.evaluate(frame_a)
    gate.evaluate(frame_a)
    decision = gate.evaluate(frame_b)

    # stored even though it falls short of the admission bar — "on every
    # segment, admitted or not"
    assert decision.motion_score == 2.0
    assert decision.admitted is False  # 2 < min_active_cells=5


def test_admitted_once_the_active_cell_count_reaches_min_active_cells():
    frame_a = _solid(100, size=200)
    frame_b = frame_a.copy()
    frame_b[0:50, 0:50] = 220
    frame_b[0:50, 150:200] = 220

    gate = _gate(grid_size=4, cell_threshold=25.0, min_active_cells=2)
    gate.evaluate(frame_a)
    gate.evaluate(frame_a)
    decision = gate.evaluate(frame_b)

    assert decision.motion_score == 2.0
    assert decision.admitted is True  # 2 >= min_active_cells=2


def test_an_uneven_resolution_is_still_divided_into_the_full_grid():
    """203 is not divisible by 4 — np.array_split must still produce 16 cells,
    some one pixel larger, rather than raising or silently dropping a strip."""
    frame_a = np.full((203, 203, 3), 100, dtype=np.uint8)
    frame_b = frame_a.copy()
    frame_b[:, :] = 220  # every cell changes

    gate = _gate(grid_size=4, cell_threshold=25.0, min_active_cells=1)
    gate.evaluate(frame_a)
    gate.evaluate(frame_a)
    decision = gate.evaluate(frame_b)

    assert decision.motion_score == 16.0


def test_blurring_suppresses_independent_per_pixel_noise_that_grayscale_alone_would_not():
    rng = np.random.default_rng(0)
    base = np.full((200, 200), 100, dtype=np.uint8)
    noisy_a = np.clip(base.astype(int) + rng.integers(-20, 21, base.shape), 0, 255).astype(np.uint8)
    noisy_b = np.clip(base.astype(int) + rng.integers(-20, 21, base.shape), 0, 255).astype(np.uint8)

    raw_diff = cv2.absdiff(noisy_a, noisy_b).mean()

    gate = _gate(blur_kernel=21)
    blurred_a = gate._preprocess(cv2.cvtColor(noisy_a, cv2.COLOR_GRAY2BGR))
    blurred_b = gate._preprocess(cv2.cvtColor(noisy_b, cv2.COLOR_GRAY2BGR))
    blurred_diff = cv2.absdiff(blurred_a, blurred_b).mean()

    assert blurred_diff < raw_diff


def test_a_fresh_gate_per_video_carries_no_state_from_a_previous_one():
    gate_one = _gate(buffer_frames=2, min_active_cells=1)
    gate_one.evaluate(_solid(30))
    gate_one.evaluate(_solid(220))  # gate_one now has real history

    gate_two = _gate(buffer_frames=2, min_active_cells=1)
    warmup = [gate_two.evaluate(_solid(30)) for _ in range(2)]

    assert all(d.motion_score is None for d in warmup)  # starts cold, not mid-buffer


# ---------------------------------------------------------------------------
# The ticket's own acceptance criterion: a real clip, still then moving
# ---------------------------------------------------------------------------

FPS = 10
WIDTH, HEIGHT = 320, 180
STILL_SAMPLES = 8
MOVING_SAMPLES = 4
BUFFER_FRAMES = 5


def _write_still_then_moving_clip(path: Path) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    assert writer.isOpened()
    still = np.full((HEIGHT, WIDTH, 3), 90, dtype=np.uint8)
    for sample in range(STILL_SAMPLES + MOVING_SAMPLES):
        if sample < STILL_SAMPLES:
            frame = still
        else:
            # A large, high-contrast block covering most of the frame — easily
            # past the default threshold even after blurring — in a different
            # place each moving sample, so it also looks like real movement.
            frame = np.full((HEIGHT, WIDTH, 3), 90, dtype=np.uint8)
            offset = (sample - STILL_SAMPLES) * 40
            frame[20:160, offset : offset + 120] = (20, 220, 20)
        for _ in range(FPS):  # one second of identical frames per sample
            writer.write(frame)
    writer.release()


@pytest.fixture(scope="module")
def still_then_moving_clip(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("motion") / "still_then_moving.mp4"
    _write_still_then_moving_clip(path)
    return path


def test_still_frames_score_low_and_moving_frames_score_high_and_are_admitted(
    still_then_moving_clip, tmp_path
):
    """The acceptance criterion, run with the same defaults main.py wires from
    settings: grid 8x8, threshold 25.0, min_active_cells 3, buffer 5, blur 21."""
    gate = pipeline.MotionGate(
        grid_size=8, cell_threshold=25.0, min_active_cells=3, buffer_frames=BUFFER_FRAMES, blur_kernel=21
    )

    records = pipeline.extract_file(
        str(still_then_moving_clip),
        source_type="upload",
        video_id=1,
        camera_id=None,
        interval_s=1.0,
        frames_dir=tmp_path / "f",
        thumbs_dir=tmp_path / "t",
        thumb_width=160,
        frame_quality=85,
        thumb_quality=70,
        gate=gate,
    )

    assert len(records) == STILL_SAMPLES + MOVING_SAMPLES

    warmup = records[:BUFFER_FRAMES]
    scored_still = records[BUFFER_FRAMES:STILL_SAMPLES]
    moving = records[STILL_SAMPLES:]

    # early frames: not scored yet, and stored that way regardless
    assert all(r.motion_score is None and r.admitted is False for r in warmup)

    # early *scored* frames: still, so low and discarded — the numbers alone
    assert all(r.motion_score is not None for r in scored_still)
    assert all(r.motion_score < 3 for r in scored_still), [r.motion_score for r in scored_still]
    assert all(r.admitted is False for r in scored_still)

    # moving frames: high and admitted
    assert all(r.motion_score is not None for r in moving)
    assert all(r.motion_score >= 3 for r in moving), [r.motion_score for r in moving]
    assert all(r.admitted is True for r in moving)

    # a clear separation between the two groups, not a fluke on one frame
    assert max(r.motion_score for r in scored_still) < min(r.motion_score for r in moving)
