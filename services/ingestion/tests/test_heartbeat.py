"""OMNI-305: heartbeat frames, Algorithm 1 step 5.

Same loading trick as test_motion_gate.py (see its docstring): pipeline.py is
loaded by file path under its own name, because ingestion and query both have
a top-level package called `app`.

HeartbeatGate wraps another gate rather than replacing it — these tests use a
small scripted stand-in gate wherever the point is HeartbeatGate's own
scheduling logic, and the real MotionGate (via main.py's actual wiring) only
in the end-to-end tests that prove the two work together on a real clip.
"""

import importlib.util
from pathlib import Path

import cv2
import numpy as np
import pytest

_spec = importlib.util.spec_from_file_location(
    "omnisight_ingestion_pipeline_heartbeat",
    Path(__file__).resolve().parents[1] / "app" / "pipeline.py",
)
pipeline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pipeline)


def _solid(value: int = 100, size: int = 20) -> np.ndarray:
    return np.full((size, size, 3), value, dtype=np.uint8)


class _ScriptedGate(pipeline.FrameGate):
    """Returns exactly what the test tells it to for each call, in order —
    so HeartbeatGate's own logic can be tested without depending on real
    motion detection at all."""

    def __init__(self, decisions: list["pipeline.GateDecision"]):
        self._decisions = list(decisions)
        self.calls: list[float] = []

    def evaluate(self, frame, timestamp_s: float) -> "pipeline.GateDecision":
        self.calls.append(timestamp_s)
        return self._decisions.pop(0)


def _never_admits(n: int) -> _ScriptedGate:
    return _ScriptedGate([pipeline.GateDecision(motion_score=0.0, admitted=False) for _ in range(n)])


# ---------------------------------------------------------------------------
# HeartbeatGate's own scheduling logic
# ---------------------------------------------------------------------------


def test_before_the_first_heartbeat_is_due_a_discarded_frame_stays_discarded():
    gate = pipeline.HeartbeatGate(_never_admits(3), heartbeat_interval_s=1.0, stride_s=0.5)

    for t in (0.0, 0.5, 0.9):
        decision = gate.evaluate(_solid(), t)
        assert decision.admitted is False
        assert decision.admission_reason is None


def test_a_source_with_its_own_time_origin_gets_its_first_heartbeat_one_interval_in():
    """A live stream is stamped with Unix time (OMNI-312), so its first frame is
    nowhere near t=0. Given its start, its first heartbeat is still one interval
    in, not immediate."""
    start = 1_790_000_000.0
    gate = pipeline.HeartbeatGate(
        _never_admits(4), heartbeat_interval_s=1.0, stride_s=0.5, start_s=start
    )

    assert gate.evaluate(_solid(), start).admitted is False
    assert gate.evaluate(_solid(), start + 0.6).admitted is False
    decision = gate.evaluate(_solid(), start + 1.0)
    assert decision.admitted is True and decision.admission_reason == "heartbeat"
    assert gate.evaluate(_solid(), start + 1.2).admitted is False


def test_without_a_start_a_unix_time_stream_would_heartbeat_on_its_first_frame():
    """The reason `start_s` exists: the default origin of 0 is right for a file
    and wrong for a live stream."""
    gate = pipeline.HeartbeatGate(_never_admits(1), heartbeat_interval_s=1.0, stride_s=0.5)

    decision = gate.evaluate(_solid(), 1_790_000_000.0)

    assert decision.admitted is True and decision.admission_reason == "heartbeat"


def test_a_frame_at_or_past_the_interval_is_force_admitted_as_heartbeat():
    gate = pipeline.HeartbeatGate(_never_admits(2), heartbeat_interval_s=1.0, stride_s=0.5)
    gate.evaluate(_solid(), 0.5)  # not due yet

    decision = gate.evaluate(_solid(), 1.0)

    assert decision.admitted is True
    assert decision.admission_reason == "heartbeat"


def test_the_inner_gates_real_score_is_kept_exactly_not_faked_or_dropped():
    inner = _ScriptedGate([pipeline.GateDecision(motion_score=None, admitted=False)])  # e.g. still warming up
    gate = pipeline.HeartbeatGate(inner, heartbeat_interval_s=1.0, stride_s=0.5)

    decision = gate.evaluate(_solid(), 1.0)

    assert decision.admitted is True
    assert decision.admission_reason == "heartbeat"
    assert decision.motion_score is None  # exactly what the inner gate said — not overwritten to 0 or faked


def test_a_heartbeat_admission_gets_a_clip_window_like_any_other():
    gate = pipeline.HeartbeatGate(_never_admits(1), heartbeat_interval_s=1.0, stride_s=0.5)

    decision = gate.evaluate(_solid(), 2.0)  # well past 2*stride_s=1.0, no clamping needed

    assert decision.clip_start_s == pytest.approx(2.0 - 1.0)  # t - 2Δ
    assert decision.clip_end_s == 2.0


def test_a_heartbeat_admission_before_2delta_has_a_clamped_clip_window():
    """Unlike a motion admission (which can't happen before 2Δ, since that's
    exactly the warm-up guard), a heartbeat can fire that early — the window
    must not claim video from before the source even starts."""
    gate = pipeline.HeartbeatGate(_never_admits(1), heartbeat_interval_s=0.2, stride_s=0.5)

    decision = gate.evaluate(_solid(), 0.2)  # t=0.2 < 2*stride_s=1.0

    assert decision.admitted is True
    assert decision.clip_start_s == 0.0  # clamped, not -0.8
    assert decision.clip_end_s == 0.2


def test_no_double_admission_for_the_same_due_frame():
    gate = pipeline.HeartbeatGate(_never_admits(2), heartbeat_interval_s=1.0, stride_s=0.5)

    first = gate.evaluate(_solid(), 1.0)
    second = gate.evaluate(_solid(), 1.05)  # still not due again yet

    assert first.admitted is True
    assert second.admitted is False


def test_the_next_heartbeat_is_due_one_full_interval_after_the_last_one_not_from_zero():
    gate = pipeline.HeartbeatGate(_never_admits(3), heartbeat_interval_s=1.0, stride_s=0.5)
    gate.evaluate(_solid(), 1.0)  # heartbeat #1

    just_before = gate.evaluate(_solid(), 1.9)
    at_next_due = gate.evaluate(_solid(), 2.0)

    assert just_before.admitted is False
    assert at_next_due.admitted is True


def test_a_real_motion_admission_postpones_the_next_heartbeat():
    """The inner gate admitting at t=1.5 (for whatever reason) means
    something is already represented right there — the next *heartbeat* is
    not due again until a full interval past that, not still on the original
    t=0-based schedule (which would have put it at t=2.0)."""
    inner = _ScriptedGate(
        [
            pipeline.GateDecision(motion_score=0.0, admitted=False),  # t=1.0 — no motion
            pipeline.GateDecision(
                motion_score=50.0, admitted=True, clip_start_s=0.5, clip_end_s=1.5, admission_reason="motion"
            ),  # t=1.5 — real motion
            pipeline.GateDecision(motion_score=0.0, admitted=False),  # t=2.0
        ]
    )
    gate = pipeline.HeartbeatGate(inner, heartbeat_interval_s=1.0, stride_s=0.5)
    at_1_0 = gate.evaluate(_solid(), 1.0)
    at_1_5 = gate.evaluate(_solid(), 1.5)
    at_2_0 = gate.evaluate(_solid(), 2.0)

    assert at_1_0.admitted is True and at_1_0.admission_reason == "heartbeat"
    assert at_1_5.admitted is True and at_1_5.admission_reason == "motion"  # passed through unchanged
    assert at_2_0.admitted is False  # not due until 1.5 + 1.0 = 2.5


def test_a_fresh_heartbeat_gate_per_video_starts_with_nothing_due_yet():
    gate_one = pipeline.HeartbeatGate(_never_admits(2), heartbeat_interval_s=0.5, stride_s=0.5)
    gate_one.evaluate(_solid(), 0.5)  # heartbeat #1
    gate_one.evaluate(_solid(), 0.6)

    gate_two = pipeline.HeartbeatGate(_never_admits(1), heartbeat_interval_s=0.5, stride_s=0.5)
    decision = gate_two.evaluate(_solid(), 0.1)  # would be a double-fire on gate_one's schedule

    assert decision.admitted is False  # gate_two's own clock hasn't reached 0.5 yet


def test_a_completely_static_5_minute_clip_produces_a_handful_of_admitted_frames():
    """The ticket's own acceptance criterion, exercised directly against the
    gate's scheduling arithmetic (no need to encode 300 real seconds of
    video for this) — a static clip's own motion gate never admits, by
    construction, so every admission here has to be heartbeat's doing."""
    total_seconds = 300
    gate = pipeline.HeartbeatGate(_never_admits(total_seconds), heartbeat_interval_s=1.0, stride_s=0.5)

    decisions = [gate.evaluate(_solid(), float(t)) for t in range(total_seconds)]

    admitted = [d for d in decisions if d.admitted]
    # One per second from t=1 to t=299 inclusive — the first heartbeat is due
    # a full interval in, not at t=0 — but the acceptance criterion's point
    # stands: "a handful," nowhere near zero.
    assert len(admitted) == 299
    assert all(d.admission_reason == "heartbeat" for d in admitted)


# ---------------------------------------------------------------------------
# End to end: HeartbeatGate wrapping the real MotionGate, through extract_file
# ---------------------------------------------------------------------------


def _extract_with_wired_gate(clip: Path, out: Path, *, heartbeat_interval_s: float, stride_s: float = 0.3):
    gate = pipeline.HeartbeatGate(
        pipeline.MotionGate(grid_size=8, cell_threshold=25.0, min_active_cells=3, stride_s=stride_s, blur_kernel=21),
        heartbeat_interval_s=heartbeat_interval_s,
        stride_s=stride_s,
    )
    return pipeline.extract_file(
        str(clip),
        source_type="upload",
        video_id=1,
        camera_id=None,
        frames_dir=out / "f",
        thumbs_dir=out / "t",
        thumb_width=160,
        frame_quality=85,
        thumb_quality=70,
        gate=gate,
    )


def test_a_truly_static_real_clip_gets_heartbeat_admissions_with_real_files_on_disk(tmp_path):
    path = tmp_path / "static.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    still = np.full((120, 160, 3), 90, dtype=np.uint8)
    for _ in range(40):  # 4 seconds, fully static — MotionGate alone would admit nothing
        writer.write(still)
    writer.release()

    records = _extract_with_wired_gate(path, tmp_path, heartbeat_interval_s=1.0)

    admitted = [r for r in records if r.admitted]
    assert admitted, "a static clip must not end up with zero admitted frames"
    assert all(r.admission_reason == "heartbeat" for r in admitted)  # never motion — nothing moved
    for r in admitted:
        assert r.frame_path is not None
        assert Path(r.frame_path).is_file()  # an admitted-by-heartbeat frame is written like any other


def test_still_then_moving_labels_each_admission_with_its_real_reason(tmp_path):
    """The two mechanisms working together: heartbeat covers the still
    section, motion covers the moving one, and each admitted row says which."""
    path = tmp_path / "clip.mp4"
    fps = 10
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (160, 120))
    still = np.full((120, 160, 3), 90, dtype=np.uint8)
    for _ in range(2 * fps):  # 2s still
        writer.write(still)
    for i in range(2 * fps):  # 2s moving — parity-flip, same trick as test_motion_gate.py
        color = (20, 20, 20) if i % 2 == 0 else (220, 220, 220)
        frame = np.full((120, 160, 3), 90, dtype=np.uint8)
        frame[10:110, 10:150] = color
        writer.write(frame)
    writer.release()

    records = _extract_with_wired_gate(path, tmp_path, heartbeat_interval_s=0.5, stride_s=0.3)

    still_admitted = [r for r in records if r.admitted and r.timestamp_s < 2.0]
    moving_admitted = [r for r in records if r.admitted and r.timestamp_s >= 2.0]

    assert still_admitted, "the still section must still get heartbeat coverage"
    assert all(r.admission_reason == "heartbeat" for r in still_admitted)
    assert moving_admitted, "the moving section must be admitted by real motion"
    assert all(r.admission_reason == "motion" for r in moving_admitted)
