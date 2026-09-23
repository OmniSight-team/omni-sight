"""OMNI-304 (reworked): Algorithm 1, ROI-aware spatial-motion sampling.

Same loading trick as test_extraction_pipeline.py (see its docstring):
pipeline.py is loaded by file path under its own name, because ingestion and
query both have a top-level package called `app`.

The original version of this file tested a frame-COUNT buffer
(`buffer_frames`, "compare to N samples back"). The rework replaces it with a
time-based stride Δ ("compare to the frame nearest t-Δ seconds back") — a
duration means the same thing at any frame rate, which a frame count does
not. That is the literal fix for the bug this rework note names: a 5-second
CCD clip sampled at 1 fps produced exactly 5 samples, which could never fill
a 5-frame warm-up buffer, so no CCD clip was ever scored. This file's central
new test (`test_the_ccd_bug_is_fixed_...`) proves that directly.

Two levels: exact, hand-built numpy frames with explicit timestamps for the
gate's own arithmetic (buffering, the pseudocode's line-by-line behaviour,
the clip window), then a real encoded video through extract_file for the
ticket's own acceptance criterion — a clip that is still and then moves.
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
        "stride_s": 1.0,
        "blur_kernel": 1,  # ksize (1,1): GaussianBlur is a no-op, for exact arithmetic
    }
    args.update(overrides)
    return pipeline.MotionGate(**args)


# ---------------------------------------------------------------------------
# Exact arithmetic, hand-built frames, explicit timestamps
# ---------------------------------------------------------------------------


def test_warmup_lasts_until_the_buffer_spans_2_delta_not_just_delta():
    """Pseudocode line 2: `if Buffer.duration < 2Δ: warmup` — twice the
    stride, not once. At t=1.0 (== Δ) the buffer only spans 1.0s, still under
    2Δ=2.0, so this must still be warm-up."""
    gate = _gate(stride_s=1.0)

    at_delta = None
    for t in (0.0, 0.5, 1.0):
        at_delta = gate.evaluate(_solid(100), t)
    assert at_delta.motion_score is None and at_delta.admitted is False  # duration 1.0 < 2Δ=2.0

    at_two_delta = gate.evaluate(_solid(100), 2.0)  # duration now 2.0 >= 2Δ
    assert at_two_delta.motion_score is not None


def test_two_identical_frames_after_warmup_score_zero_and_are_not_admitted():
    gate = _gate(stride_s=0.5, min_active_cells=1)
    for t in (0.0, 0.5, 1.0):
        gate.evaluate(_solid(100), t)

    decision = gate.evaluate(_solid(100), 1.5)

    assert decision.motion_score == 0.0
    assert decision.admitted is False


def test_compares_against_the_frame_nearest_t_minus_delta_not_the_one_before():
    """Δ=1.0: scoring frame at t=2.0 must compare against the frame nearest
    t-Δ=1.0, not the immediately preceding one at t=1.9. The 1.9 frame is
    made very different on purpose — comparing against it (the immediately
    preceding sample) would show heavy motion; comparing correctly, against
    the t=1.0 frame, shows none."""
    gate = _gate(stride_s=1.0, min_active_cells=1)
    gate.evaluate(_solid(30), 0.0)
    gate.evaluate(_solid(30), 1.0)  # this is what t=2.0 must be compared to
    gate.evaluate(_solid(220), 1.9)  # a decoy, immediately before t=2.0

    decision = gate.evaluate(_solid(30), 2.0)  # identical to the t=1.0 frame

    assert decision.motion_score == 0.0
    assert decision.admitted is False


def test_a_duration_means_the_same_thing_at_any_frame_rate():
    """The whole point of Δ being a duration: a 10fps stream (dt=0.1) and a
    30fps stream (dt=1/30) with the same Δ and the same underlying scene
    change must reach the same verdict, even though the frame *count* to the
    comparison target differs (10 vs 30)."""
    frame_a, frame_b = _solid(30), _solid(220)

    def run(dt: float, change_at_index: int, total: int) -> "pipeline.GateDecision":
        gate = _gate(stride_s=0.5, min_active_cells=1)
        decision = None
        for i in range(total):
            frame = frame_b if i >= change_at_index else frame_a
            decision = gate.evaluate(frame, i * dt)
        return decision

    # Both scenes hold `frame_a` for 1s, then switch to `frame_b`, and both
    # are evaluated 1.5s in (well past 2Δ=1.0s of warm-up either way).
    slow = run(dt=0.1, change_at_index=10, total=15)  # 10fps
    fast = run(dt=1 / 30, change_at_index=30, total=45)  # 30fps

    assert slow.admitted is True
    assert fast.admitted is True
    assert slow.motion_score == fast.motion_score


def test_the_ccd_bug_is_fixed_a_5s_10fps_clip_produces_scored_frames():
    """The concrete case the rework note names: 50 calls at dt=0.1 (a 5s,
    10fps clip's worth of timestamps). With the old frame-count buffer
    (buffer_frames=5) every one of these 50 calls fell inside warm-up,
    because the clip only ever produced 5 *sampled* frames in the first
    place — sampling doesn't happen at all here, and warm-up is now bounded
    by time (2Δ), not by the clip's own length, so scoring starts well
    before the clip ends."""
    gate = _gate(stride_s=0.2, min_active_cells=1)  # 2Δ = 0.4s = 4 frames at 10fps

    decisions = [gate.evaluate(_solid(100), i * 0.1) for i in range(50)]

    scored = [d for d in decisions if d.motion_score is not None]
    assert len(scored) > 0
    assert len(scored) == 46  # 50 - 4 warm-up calls (duration < 0.4s)


def test_a_cell_counts_as_changed_only_past_the_threshold():
    frame_a = _solid(100)
    frame_b = frame_a.copy()
    frame_b[0:50, 0:50] = 100 + 20  # one cell, diff 20 — below the threshold below

    gate = _gate(grid_size=4, cell_threshold=25.0, min_active_cells=1, stride_s=1.0)
    gate.evaluate(frame_a, 0.0)
    gate.evaluate(frame_a, 1.0)
    below = gate.evaluate(frame_b, 2.0)

    gate2 = _gate(grid_size=4, cell_threshold=15.0, min_active_cells=1, stride_s=1.0)
    gate2.evaluate(frame_a, 0.0)
    gate2.evaluate(frame_a, 1.0)
    above = gate2.evaluate(frame_b, 2.0)

    assert below.motion_score == 0.0 and below.admitted is False
    assert above.motion_score == 1.0 and above.admitted is True


def test_motion_score_is_the_count_of_changed_cells_independent_of_min_active_cells():
    frame_a = _solid(100, size=200)
    frame_b = frame_a.copy()
    frame_b[0:50, 0:50] = 220  # cell (0,0)
    frame_b[0:50, 150:200] = 220  # cell (0,3) — two of the sixteen 4x4 cells

    gate = _gate(grid_size=4, cell_threshold=25.0, min_active_cells=5, stride_s=1.0)
    gate.evaluate(frame_a, 0.0)
    gate.evaluate(frame_a, 1.0)
    decision = gate.evaluate(frame_b, 2.0)

    # stored even though it falls short of the admission bar — "on every
    # segment, admitted or not"
    assert decision.motion_score == 2.0
    assert decision.admitted is False  # 2 < min_active_cells=5


def test_admitted_once_the_active_cell_count_reaches_min_active_cells():
    frame_a = _solid(100, size=200)
    frame_b = frame_a.copy()
    frame_b[0:50, 0:50] = 220
    frame_b[0:50, 150:200] = 220

    gate = _gate(grid_size=4, cell_threshold=25.0, min_active_cells=2, stride_s=1.0)
    gate.evaluate(frame_a, 0.0)
    gate.evaluate(frame_a, 1.0)
    decision = gate.evaluate(frame_b, 2.0)

    assert decision.motion_score == 2.0
    assert decision.admitted is True  # 2 >= min_active_cells=2


def test_an_uneven_resolution_is_still_divided_into_the_full_grid():
    """203 is not divisible by 4 — np.array_split must still produce 16 cells,
    some one pixel larger, rather than raising or silently dropping a strip."""
    frame_a = np.full((203, 203, 3), 100, dtype=np.uint8)
    frame_b = frame_a.copy()
    frame_b[:, :] = 220  # every cell changes

    gate = _gate(grid_size=4, cell_threshold=25.0, min_active_cells=1, stride_s=1.0)
    gate.evaluate(frame_a, 0.0)
    gate.evaluate(frame_a, 1.0)
    decision = gate.evaluate(frame_b, 2.0)

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
    gate_one = _gate(stride_s=0.5, min_active_cells=1)
    for t in (0.0, 0.5, 1.0, 1.5):
        gate_one.evaluate(_solid(30) if t < 1.0 else _solid(220), t)  # gate_one now has real history

    gate_two = _gate(stride_s=0.5, min_active_cells=1)
    warmup = [gate_two.evaluate(_solid(30), t) for t in (0.0, 0.5)]

    assert all(d.motion_score is None for d in warmup)  # starts cold, not mid-buffer


# ---------------------------------------------------------------------------
# The causal clip window, pseudocode lines 7-8
# ---------------------------------------------------------------------------


def test_an_admitted_frame_carries_a_clip_window_of_2delta_ending_at_its_own_timestamp():
    gate = _gate(stride_s=0.5, min_active_cells=1)
    gate.evaluate(_solid(30), 0.0)
    gate.evaluate(_solid(30), 0.5)
    gate.evaluate(_solid(30), 1.0)  # duration now 1.0 == 2Δ, warm-up over

    decision = gate.evaluate(_solid(220), 1.5)  # very different from the buffered history

    assert decision.admitted is True
    assert decision.clip_start_s == pytest.approx(1.5 - 1.0)  # t - 2Δ
    assert decision.clip_end_s == 1.5


def test_a_discarded_frame_carries_no_clip_window():
    gate = _gate(stride_s=0.5, min_active_cells=1)
    for t in (0.0, 0.5, 1.0):
        gate.evaluate(_solid(30), t)

    decision = gate.evaluate(_solid(30), 1.5)  # identical, not admitted

    assert decision.admitted is False
    assert decision.clip_start_s is None
    assert decision.clip_end_s is None


def test_an_unscored_warmup_frame_carries_no_clip_window():
    gate = _gate(stride_s=0.5)

    decision = gate.evaluate(_solid(30), 0.0)

    assert decision.motion_score is None
    assert decision.clip_start_s is None
    assert decision.clip_end_s is None


# ---------------------------------------------------------------------------
# The ticket's own acceptance criterion: a real clip, still then moving
# ---------------------------------------------------------------------------

FPS = 10
WIDTH, HEIGHT = 320, 180
STILL_SECONDS = 3.0
MOVING_SECONDS = 2.0
STRIDE_S = 0.3  # 2Δ = 0.6s of warm-up


def _write_still_then_moving_clip(path: Path) -> int:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    assert writer.isOpened()
    still_frames = round(STILL_SECONDS * FPS)
    moving_frames = round(MOVING_SECONDS * FPS)
    still = np.full((HEIGHT, WIDTH, 3), 90, dtype=np.uint8)
    for i in range(still_frames):
        writer.write(still)
    # A sliding block's diff against a frame Δ back depends on how far it
    # moved in that span, which can land under the grid-cell threshold by
    # coincidence for some (grid_size, stride) combinations — a real effect
    # (real footage does this too, see UCF-Crime's 31-36 range rather than a
    # flat maximum, docs/context/week-03-04.md), but not what this test wants
    # to prove. A fresh random color per frame has the same problem in a
    # subtler form: two independently drawn colors can land close enough to
    # each other (or to the background) to fall under threshold by pure
    # chance. A hard black/white flip by frame parity has neither risk, and
    # is deliberately paired with STRIDE_S/FPS below being chosen so the
    # frame gap (Δ·FPS = 3) is odd — an odd gap always lands on the opposite
    # parity, so every comparison in this test is guaranteed maximum contrast.
    assert round(STRIDE_S * FPS) % 2 == 1, "the parity-flip trick below needs an odd frame gap"
    for i in range(moving_frames):
        color = (20, 20, 20) if i % 2 == 0 else (220, 220, 220)
        frame = np.full((HEIGHT, WIDTH, 3), 90, dtype=np.uint8)
        frame[20:160, 20:280] = color
        writer.write(frame)
    writer.release()
    return still_frames + moving_frames


@pytest.fixture(scope="module")
def still_then_moving_clip(tmp_path_factory) -> tuple[Path, int]:
    path = tmp_path_factory.mktemp("motion") / "still_then_moving.mp4"
    count = _write_still_then_moving_clip(path)
    return path, count


def test_still_frames_score_low_and_moving_frames_score_high_and_are_admitted(
    still_then_moving_clip, tmp_path
):
    """The acceptance criterion, run with the same G/τ/k defaults main.py
    wires from settings (grid 8, threshold 25.0, min_active_cells 3), and a
    short stride so the still section has plenty of scored frames left after
    its own warm-up."""
    clip, total_frames = still_then_moving_clip
    gate = pipeline.MotionGate(
        grid_size=8, cell_threshold=25.0, min_active_cells=3, stride_s=STRIDE_S, blur_kernel=21
    )

    records = pipeline.extract_file(
        str(clip),
        source_type="upload",
        video_id=1,
        camera_id=None,
        frames_dir=tmp_path / "f",
        thumbs_dir=tmp_path / "t",
        thumb_width=160,
        frame_quality=85,
        thumb_quality=70,
        gate=gate,
    )

    assert len(records) == total_frames

    warmup_seconds = 2 * STRIDE_S
    warmup = [r for r in records if r.timestamp_s < warmup_seconds]
    scored_still = [r for r in records if warmup_seconds <= r.timestamp_s < STILL_SECONDS]
    moving = [r for r in records if r.timestamp_s >= STILL_SECONDS]

    assert warmup and scored_still and moving  # the split isn't degenerate

    # early frames: not scored yet, and stored that way regardless
    assert all(r.motion_score is None and r.admitted is False for r in warmup)

    # early *scored* frames: still, so low and discarded — the numbers alone
    assert all(r.motion_score is not None for r in scored_still)
    assert all(r.motion_score < 3 for r in scored_still), [r.motion_score for r in scored_still]
    assert all(r.admitted is False for r in scored_still)
    assert all(r.frame_path is None for r in scored_still)  # never written

    # moving frames: high and admitted, each with its own causal clip window
    assert all(r.motion_score is not None for r in moving)
    assert all(r.motion_score >= 3 for r in moving), [r.motion_score for r in moving]
    assert all(r.admitted is True for r in moving)
    assert all(r.frame_path is not None and Path(r.frame_path).is_file() for r in moving)
    for r in moving:
        assert r.clip_start_s == pytest.approx(r.timestamp_s - 2 * STRIDE_S)
        assert r.clip_end_s == r.timestamp_s

    # a clear separation between the two groups, not a fluke on one frame
    assert max(r.motion_score for r in scored_still) < min(r.motion_score for r in moving)


def test_a_ccd_clip_and_a_ucf_crime_shaped_clip_both_produce_scored_frames(tmp_path):
    """Acceptance: "A CCD clip and a UCF-Crime clip both produce scored
    frames." Both real datasets are exercised live against the running stack
    (docs/context/week-03-04.md); this is the fast, offline version of the
    same claim — two different fps/duration combinations, both past the
    warm-up window before the clip ends."""
    ccd = tmp_path / "ccd_shaped.mp4"  # 5s @ 10fps, like a real CCD clip
    ucf = tmp_path / "ucf_shaped.mp4"  # 3s @ 30fps, short like a real UCF-Crime clip
    for path, seconds, fps in ((ccd, 5, 10), (ucf, 3, 30)):
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (WIDTH, HEIGHT))
        for i in range(round(seconds * fps)):
            frame = np.full((HEIGHT, WIDTH, 3), 90, dtype=np.uint8)
            frame[20:160, (i * 5) % 200 : (i * 5) % 200 + 100] = (20, 220, 20)
            writer.write(frame)
        writer.release()

    for path in (ccd, ucf):
        gate = pipeline.MotionGate(
            grid_size=8, cell_threshold=25.0, min_active_cells=3, stride_s=0.5, blur_kernel=21
        )
        records = pipeline.extract_file(
            str(path),
            source_type="upload",
            video_id=1,
            camera_id=None,
            frames_dir=tmp_path / "f" / path.stem,
            thumbs_dir=tmp_path / "t" / path.stem,
            thumb_width=160,
            frame_quality=85,
            thumb_quality=70,
            gate=gate,
        )
        scored = [r for r in records if r.motion_score is not None]
        assert scored, f"{path.name} produced no scored frames at all"
