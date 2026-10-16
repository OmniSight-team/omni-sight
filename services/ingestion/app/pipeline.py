"""The frame pipeline: decoded frame in, stored segment out.

`process_frame` is the one place a frame becomes a segment. A file extractor
calls it (`extract_file`, below) and, in Part B, so does the live capture
worker — neither passes anything that says which of the two it is beyond the
plain `source_type` label, so nothing downstream can tell them apart.

Deliberately imports nothing from `app.*`: every setting arrives as an
argument, which keeps this module independent of the service around it.

OMNI-304 follows Phase A §3.5.1's pseudocode (Appendix B.1) line by line —
every design choice below is annotated with the pseudocode line it implements.
"""

import shutil
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


class ExtractError(Exception):
    """A file could not be extracted. Always caught by the route and returned
    as a reason — a bad file is a clean, reported failure, never a crash."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class FrameSource:
    """Where a frame came from. Everything process_frame needs to know about
    its origin, and nothing about how the frame was obtained."""

    source_type: str  # "upload" or "camera"
    frame_index: int
    timestamp_s: float
    video_id: int | None = None
    camera_id: int | None = None


@dataclass(frozen=True)
class GateDecision:
    motion_score: float | None
    admitted: bool
    # The causal clip window, pseudocode lines 7-8: [t - 2Δ, t], set only when
    # `admitted` is True. The window is recorded as two numbers, never as
    # written-out video — slice 8 cuts the actual bytes from the source when
    # it needs them.
    clip_start_s: float | None = None
    clip_end_s: float | None = None
    # Why the frame was admitted — "motion" or "heartbeat" (OMNI-305). None on
    # a frame that was not admitted at all; a real motion score is kept as-is
    # either way (a heartbeat admission does not fake or discard the score the
    # gate actually computed).
    admission_reason: str | None = None


def _clip_window(timestamp_s: float, stride_s: float) -> tuple[float, float]:
    """[t-2Δ, t]. Clamped so the start never precedes the video's own start —
    a real motion admission's own 2Δ warm-up guard makes that unreachable for
    it, but a heartbeat admission (OMNI-305) can fire before warm-up ends."""
    return max(0.0, timestamp_s - 2 * stride_s), timestamp_s


@dataclass(frozen=True)
class SegmentRecord:
    """One stored frame — the fields of a `segments` row, minus the id.

    frame_path and thumb_path are None unless the frame was admitted: writing
    a JPEG for every decoded frame of a 30 fps video is not affordable at
    slice 6 scale, so only admitted (and, from OMNI-305, heartbeat) frames get
    one. For a file a row is still written for every gated frame regardless —
    rows are cheap, JPEGs are not, and the discarded scores are what make the
    gate inspectable and the threshold slider (OMNI-310) possible. A live
    camera's discarded frames are counted, not stored (OMNI-501).
    """

    video_id: int | None
    camera_id: int | None
    frame_index: int
    timestamp_s: float
    frame_path: str | None
    thumb_path: str | None
    motion_score: float | None
    admitted: bool
    source_type: str
    clip_start_s: float | None = None
    clip_end_s: float | None = None
    admission_reason: str | None = None
    # The bytes of the frame and thumbnail JPEGs written for this frame; 0 when none
    # were (OMNI-610: the dashboard's storage figure sums this instead of walking the disk).
    file_bytes: int = 0


class FrameGate:
    """Decides whether a frame is worth keeping.

    OMNI-304 implements the motion gate here. Until then nothing is scored and
    nothing is admitted (motion_score None means "not scored yet"), so every
    stored segment says honestly that no decision has been made about it. The
    gate is passed in, one per stream, because motion detection compares a
    frame with earlier ones and so has to carry state between calls.
    """

    def evaluate(self, frame, timestamp_s: float) -> GateDecision:
        return GateDecision(motion_score=None, admitted=False)


# Guards the 2Δ boundary comparisons in MotionGate against floating-point
# accumulation. Frame timestamps arrive as repeated float addition/division
# (index / fps), which does not reproduce an exact multiple of Δ — without
# this, the warm-up check and the buffer-pruning check could disagree by a
# few ULPs at the exact boundary, occasionally pruning one entry too many and
# spuriously dropping a fully warmed-up gate back into "warmup" for a frame
# or two. Microseconds, tiny next to any real Δ (settings enforce Δ > 0).
_CLOCK_EPSILON_S = 1e-6


def _split_edges(length: int, parts: int) -> np.ndarray:
    # np.array_split's boundaries: the first `length % parts` parts are one
    # pixel larger, so a frame that doesn't divide the grid evenly is still
    # covered exactly, with no strip dropped.
    size, extra = divmod(length, parts)
    return np.array([i * size + min(i, extra) for i in range(parts + 1)])


def _cell_means(diff: np.ndarray, grid_size: int) -> np.ndarray:
    """Algorithm 1 lines 4-5's cell means, the G x G grid in one array operation
    instead of G² (OMNI-613). The same cells as np.array_split and the same
    arithmetic as each cell's .mean(): an exact integer sum divided by the
    cell's pixel count, so the scores are identical, not approximately equal."""
    height, width = diff.shape
    if height % grid_size == 0 and width % grid_size == 0:
        sums = diff.reshape(grid_size, height // grid_size, grid_size, width // grid_size).sum(
            axis=(1, 3), dtype=np.uint32
        )
        return sums / ((height // grid_size) * (width // grid_size))
    # Uneven: corner lookups in the integral image give each cell's sum.
    rows, cols = _split_edges(height, grid_size), _split_edges(width, grid_size)
    corners = cv2.integral(diff)[np.ix_(rows, cols)].astype(np.int64)
    sums = corners[1:, 1:] - corners[:-1, 1:] - corners[1:, :-1] + corners[:-1, :-1]
    return sums / np.outer(np.diff(rows), np.diff(cols))


class MotionGate(FrameGate):
    """Algorithm 1 (Phase A §3.5.1 / Appendix B.1), followed line by line:

        in:  stride Δ, grid G, threshold τ, min cells k
        1:   Buffer_cam.append(f_t)
        2:   if Buffer.duration < 2Δ: warmup
        3:   diff = |gray(f_t) − gray(f_{t−Δ})|
        4:   cells = partition(diff, G×G)
        5:   active = count(c : mean(c) > τ)
        6:   if active ≥ k: admit
        7:   W = Buffer.window([t − 2Δ, t])
        8:   forward(f_t, W)
        10:  else: drop(f_t)

    Δ is a **duration**, not a frame count — the same Δ means the same amount
    of real time regardless of the source's frame rate, which is what makes a
    5-second, 10 fps clip and a 5-second, 30 fps clip behave the same way. A
    frame-count buffer does not have this property: it was the original
    implementation's bug (recorded in OMNI-303's rework note) — a 5-second CCD
    clip sampled at 1 fps produced exactly 5 frames, which never filled a
    5-frame buffer, so no CCD clip was ever scored.

    One documented departure from the pseudocode: frames are blurred before
    differencing (see `_preprocess`). The pseudocode does not blur; without it,
    two frames of a perfectly still scene still differ pixel by pixel from
    sensor noise alone, which the blur suppresses. Recorded in docs/decisions.md (D-4).

    One instance per extraction: it holds a buffer of earlier frames, so it
    carries state across calls the way a stateless function could not, and
    that state must never cross from one video into another.
    """

    def __init__(
        self,
        *,
        grid_size: int,
        cell_threshold: float,
        min_active_cells: int,
        stride_s: float,
        blur_kernel: int,
    ):
        self._grid_size = grid_size
        self._cell_threshold = cell_threshold
        self._min_active_cells = min_active_cells
        self._stride_s = stride_s
        self._blur_kernel = blur_kernel
        # (timestamp_s, blurred grayscale frame), oldest first. Pruned to the
        # last 2Δ on every call (line 7's window never reaches further back
        # than that), so memory stays bounded regardless of clip length or fps.
        self._buffer: deque[tuple[float, np.ndarray]] = deque()

    def _preprocess(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Blurring first is what keeps sensor noise from being read as
        # motion: two frames of a perfectly still scene still differ pixel by
        # pixel from sensor noise alone, and a blur smooths that out before
        # the comparison is even made. Not in the pseudocode — see class doc.
        return cv2.GaussianBlur(gray, (self._blur_kernel, self._blur_kernel), 0)

    def evaluate(self, frame, timestamp_s: float) -> GateDecision:
        t = timestamp_s
        processed = self._preprocess(frame)

        # Line 1: append before comparing, so a one-frame buffer at t=0 is
        # itself in the buffer (harmless: Δ>0 means it's never its own
        # "nearest to t-Δ").
        self._buffer.append((t, processed))

        # Line 2: warm-up is measured in time, not in a count of frames. 2Δ,
        # not Δ, because an admitted frame's clip window (line 7) reaches back
        # to t-2Δ; scoring only starts once the buffer has actually seen that
        # much history, not just enough for the line-3 diff on its own.
        duration = t - self._buffer[0][0]
        if duration < 2 * self._stride_s - _CLOCK_EPSILON_S:
            return GateDecision(motion_score=None, admitted=False)

        # Line 3: compare against the buffered frame nearest t-Δ, never the
        # immediately preceding one — consecutive frames barely differ, which
        # is the whole reason Δ exists.
        target = t - self._stride_s
        earlier = min(self._buffer, key=lambda item: abs(item[0] - target))[1]
        diff = cv2.absdiff(processed, earlier)

        # Lines 4-5.
        active_cells = int(np.count_nonzero(_cell_means(diff, self._grid_size) > self._cell_threshold))

        # Line 6.
        admitted = active_cells >= self._min_active_cells

        # Keep only what a future call could still need: entries newer than
        # 2Δ back from the newest one seen so far. The margin here is on the
        # side of keeping an entry, not dropping it — pruning too eagerly is
        # what would let duration dip back under 2Δ on the very next call.
        while self._buffer and t - self._buffer[0][0] > 2 * self._stride_s + _CLOCK_EPSILON_S:
            self._buffer.popleft()

        # Lines 7-8: the window is pure arithmetic from t and Δ — nothing is
        # read back out of the buffer, because the buffer holds preprocessed
        # (grayscale, blurred) frames for differencing only, never the
        # original bytes a clip would be cut from.
        if admitted:
            clip_start_s, clip_end_s = _clip_window(t, self._stride_s)
            return GateDecision(
                motion_score=float(active_cells),
                admitted=True,
                clip_start_s=clip_start_s,
                clip_end_s=clip_end_s,
                admission_reason="motion",
            )
        return GateDecision(motion_score=float(active_cells), admitted=False)


class HeartbeatGate(FrameGate):
    """Algorithm 1 step 5: also admit a frame at a fixed interval even when
    the wrapped gate finds no motion, so a parked car or an empty room stays
    represented in the index instead of being invisible for an entire
    recording.

    A thin wrapper, not a replacement for the wrapped gate: every real
    decision (the score, whether it was motion, the clip window) still comes
    from the inner gate. This only ever turns a "not admitted" into an
    admitted one; it never touches `motion_score`, and it never overrides a
    motion admission's own reason or window.

    One instance per extraction, same as the gate it wraps — its "next
    heartbeat due" clock must never cross from one video into another.
    """

    def __init__(
        self,
        inner: FrameGate,
        *,
        heartbeat_interval_s: float,
        stride_s: float,
        start_s: float = 0.0,
    ):
        self._inner = inner
        self._heartbeat_interval_s = heartbeat_interval_s
        self._stride_s = stride_s
        # The first heartbeat is due a full interval in, not at the start — a
        # due time equal to the start would make the very first frame of every
        # video a heartbeat admission regardless of the interval. `start_s` is
        # the source's own time origin: 0 for a file, whose timestamps are
        # seconds from its start, and the moment capture began for a live
        # stream (OMNI-312), whose timestamps are Unix time.
        self._next_due_s = start_s + heartbeat_interval_s

    def evaluate(self, frame, timestamp_s: float) -> GateDecision:
        decision = self._inner.evaluate(frame, timestamp_s)
        if decision.admitted:
            # A real admission already covers this stretch of video — the
            # next heartbeat isn't due again until a full interval past it,
            # so motion-rich footage doesn't also collect redundant
            # heartbeat admissions right next to its own real ones.
            self._next_due_s = timestamp_s + self._heartbeat_interval_s
            return decision

        if timestamp_s < self._next_due_s:
            return decision  # not due yet; pass the "not admitted" through unchanged

        self._next_due_s = timestamp_s + self._heartbeat_interval_s
        clip_start_s, clip_end_s = _clip_window(timestamp_s, self._stride_s)
        return GateDecision(
            motion_score=decision.motion_score,  # unchanged — whatever it actually was
            admitted=True,
            clip_start_s=clip_start_s,
            clip_end_s=clip_end_s,
            admission_reason="heartbeat",
        )


def _write_jpeg(path: Path, image, quality: int) -> None:
    if not cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, quality]):
        raise ExtractError(f"could not write {path.name}")


def _thumbnail(frame, width: int):
    height, full_width = frame.shape[:2]
    if full_width <= width:
        return frame  # never upscale
    scaled_height = max(1, round(height * width / full_width))
    return cv2.resize(frame, (width, scaled_height), interpolation=cv2.INTER_AREA)


def process_frame(
    frame,
    source: FrameSource,
    gate: FrameGate,
    frames_dir: Path,
    thumbs_dir: Path,
    *,
    thumb_width: int,
    frame_quality: int,
    thumb_quality: int,
) -> SegmentRecord:
    """Gate one decoded frame. A JPEG and thumbnail are written only if the
    gate admits the frame; a segment is returned either way. The caller owns
    the output directories and puts the returned record into the database."""
    decision = gate.evaluate(frame, source.timestamp_s)

    frame_path = thumb_path = None
    file_bytes = 0
    if decision.admitted:
        name = f"{source.frame_index:06d}.jpg"
        frame_path = frames_dir / name
        thumb_path = thumbs_dir / name
        _write_jpeg(frame_path, frame, frame_quality)
        _write_jpeg(thumb_path, _thumbnail(frame, thumb_width), thumb_quality)
        file_bytes = frame_path.stat().st_size + thumb_path.stat().st_size

    return SegmentRecord(
        video_id=source.video_id,
        camera_id=source.camera_id,
        frame_index=source.frame_index,
        timestamp_s=source.timestamp_s,
        frame_path=str(frame_path) if frame_path is not None else None,
        thumb_path=str(thumb_path) if thumb_path is not None else None,
        motion_score=decision.motion_score,
        admitted=decision.admitted,
        source_type=source.source_type,
        clip_start_s=decision.clip_start_s,
        clip_end_s=decision.clip_end_s,
        admission_reason=decision.admission_reason,
        file_bytes=file_bytes,
    )


def extract_file(
    path: str,
    *,
    source_type: str,
    video_id: int | None,
    camera_id: int | None,
    frames_dir: Path,
    thumbs_dir: Path,
    thumb_width: int,
    frame_quality: int,
    thumb_quality: int,
    gate: FrameGate | None = None,
) -> list[SegmentRecord]:
    """Decode and gate every frame of a stored file (OMNI-303's rework: the
    algorithm has no sampling step, so extraction doesn't invent one) and run
    each through process_frame.

    The two output directories are wiped first: they belong to this one video,
    so anything already in them is stale (a previous extraction, or the
    leftovers of a crashed one). If anything goes wrong they are wiped again,
    so a failed extraction leaves no files behind.
    """
    if not Path(path).is_file():
        raise ExtractError("file not found")

    capture = cv2.VideoCapture(path)
    try:
        if not capture.isOpened():
            raise ExtractError("could not open file")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if fps <= 0:
            raise ExtractError("could not determine frame rate")

        for directory in (frames_dir, thumbs_dir):
            shutil.rmtree(directory, ignore_errors=True)
            directory.mkdir(parents=True, exist_ok=True)

        gate = gate or FrameGate()
        records: list[SegmentRecord] = []
        index = -1
        try:
            # grab() returning False is a clean end of file. retrieve() then
            # failing on a frame grab() just confirmed exists is a genuinely
            # undecodable frame, not the stream ending — the two are kept
            # distinct rather than collapsed into a single "stop" signal.
            while capture.grab():
                index += 1
                ok, frame = capture.retrieve()
                if not ok or frame is None:
                    raise ExtractError(f"could not decode frame {index}")
                records.append(
                    process_frame(
                        frame,
                        FrameSource(
                            source_type=source_type,
                            frame_index=index,
                            timestamp_s=index / fps,
                            video_id=video_id,
                            camera_id=camera_id,
                        ),
                        gate,
                        frames_dir,
                        thumbs_dir,
                        thumb_width=thumb_width,
                        frame_quality=frame_quality,
                        thumb_quality=thumb_quality,
                    )
                )
            if not records:
                raise ExtractError("no frames could be read from file")
        except ExtractError:
            _wipe(frames_dir, thumbs_dir)
            raise
        except Exception as exc:
            _wipe(frames_dir, thumbs_dir)
            raise ExtractError(f"extraction failed: {exc}") from exc
        return records
    finally:
        capture.release()


def _wipe(*directories: Path) -> None:
    for directory in directories:
        shutil.rmtree(directory, ignore_errors=True)
