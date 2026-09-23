"""Ensures a browser-playable H.264 copy of a stored video exists (OMNI-308).

OMNI-300 found real dataset footage a browser cannot play at all: CCD's clips
are MPEG-4 Part 2, and UCF-Crime's carry an extra audio and a PNG-cover-art
stream a plain <video> element trips over. This module is what the player
(OMNI-308) actually points at — extraction and gating (OMNI-303/304) keep
reading the ORIGINAL file always; the copy this module writes exists purely
for viewing, beside the original, never in its place.
"""

import subprocess
from pathlib import Path

# ffprobe reads a container header; a real transcode of even a short clip
# takes longer. Two very different orders of magnitude, so two timeouts.
CODEC_PROBE_TIMEOUT_S = 15
TRANSCODE_TIMEOUT_S = 120


class PlaybackError(Exception):
    """A playback copy could not be produced. Always caught by the route and
    returned as a reason — this never fails the probe or the upload it
    follows; the original file already proved decodable on its own."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def playback_path_for(path: str) -> str:
    """Beside the original, never in its place — `foo.mp4` gets
    `foo_playback.mp4` next to it in the same directory."""
    original = Path(path)
    return str(original.with_name(f"{original.stem}_playback.mp4"))


def _video_codec(path: str) -> str | None:
    """The first video stream's codec name, via ffprobe — more reliable than
    parsing OpenCV's own fourcc encoding, and ffmpeg is already a dependency
    here for the transcode step below. None if ffprobe itself can't tell."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=CODEC_PROBE_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def ensure_playback_copy(path: str) -> str | None:
    """Returns the playback copy's path, or None if the source is already
    H.264 and needs no copy at all — the original plays fine as-is.

    Codec detection failing (a corrupt or unusual file) is treated as "needs
    a copy, try anyway" rather than skipped silently; if the transcode also
    fails, that raises PlaybackError same as any other real failure.
    """
    if _video_codec(path) == "h264":
        return None

    target = playback_path_for(path)
    staging = f"{target}.part"
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", path,
                "-map", "0:v:0",
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                # ffmpeg infers the container from the output's extension;
                # ".mp4.part" isn't recognized, so the muxer is named
                # explicitly rather than dropping the staging suffix.
                "-f", "mp4",
                staging,
            ],
            capture_output=True,
            text=True,
            timeout=TRANSCODE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        Path(staging).unlink(missing_ok=True)
        raise PlaybackError("ffmpeg timed out") from exc
    except OSError as exc:
        Path(staging).unlink(missing_ok=True)
        raise PlaybackError(f"could not run ffmpeg: {exc}") from exc

    if result.returncode != 0:
        Path(staging).unlink(missing_ok=True)
        # ffmpeg's own stderr is verbose; the last stretch names the actual
        # failure (an unsupported input, a bad codec, etc.), the rest is
        # banner/version noise.
        raise PlaybackError(f"ffmpeg failed: {result.stderr.strip()[-500:]}")

    Path(staging).replace(target)
    return target
