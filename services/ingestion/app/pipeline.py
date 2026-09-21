"""The frame pipeline: decoded frame in, stored segment out.

`process_frame` is the one place a frame becomes a segment. A file extractor
calls it (`extract_file`, below) and, in Part B, so does the live capture
worker — neither passes anything that says which of the two it is beyond the
plain `source_type` label, so nothing downstream can tell them apart.

Deliberately imports nothing from `app.*`: every setting arrives as an
argument, which keeps this module independent of the service around it.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

import cv2


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


@dataclass(frozen=True)
class SegmentRecord:
    """One stored frame — the fields of a `segments` row, minus the id."""

    video_id: int | None
    camera_id: int | None
    frame_index: int
    timestamp_s: float
    frame_path: str
    thumb_path: str
    motion_score: float | None
    admitted: bool
    source_type: str


class FrameGate:
    """Decides whether a frame is worth keeping.

    OMNI-304 implements the motion gate here. Until then nothing is scored and
    nothing is admitted (motion_score None means "not scored yet"), so every
    stored segment says honestly that no decision has been made about it. The
    gate is passed in, one per stream, because motion detection compares a
    frame with earlier ones and so has to carry state between calls.
    """

    def evaluate(self, frame) -> GateDecision:
        return GateDecision(motion_score=None, admitted=False)


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
    """Gate one decoded frame, write it and its thumbnail, and return the
    segment that describes them. The caller owns the output directories and
    puts the returned record into the database."""
    decision = gate.evaluate(frame)

    name = f"{source.frame_index:06d}.jpg"
    frame_path = frames_dir / name
    thumb_path = thumbs_dir / name
    _write_jpeg(frame_path, frame, frame_quality)
    _write_jpeg(thumb_path, _thumbnail(frame, thumb_width), thumb_quality)

    return SegmentRecord(
        video_id=source.video_id,
        camera_id=source.camera_id,
        frame_index=source.frame_index,
        timestamp_s=source.timestamp_s,
        frame_path=str(frame_path),
        thumb_path=str(thumb_path),
        motion_score=decision.motion_score,
        admitted=decision.admitted,
        source_type=source.source_type,
    )


def extract_file(
    path: str,
    *,
    source_type: str,
    video_id: int | None,
    camera_id: int | None,
    interval_s: float,
    frames_dir: Path,
    thumbs_dir: Path,
    thumb_width: int,
    frame_quality: int,
    thumb_quality: int,
    gate: FrameGate | None = None,
) -> list[SegmentRecord]:
    """Take one frame every `interval_s` seconds from a stored file and run each
    through process_frame.

    The two output directories are wiped first: they belong to this one video,
    so anything already in them is stale (a previous, longer extraction, or the
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
        step = interval_s * fps
        records: list[SegmentRecord] = []
        index = -1
        next_sample = 0
        try:
            # grab() steps through the file without converting the frames it
            # skips; only the sampled ones are retrieved and processed.
            while capture.grab():
                index += 1
                if index < next_sample:
                    continue
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
                # max(): an interval shorter than one frame must still move on.
                next_sample = max(index + 1, round(len(records) * step))
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
