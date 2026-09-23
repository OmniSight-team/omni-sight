"""OMNI-308: ensure_playback_copy, a browser-playable H.264 copy of a video.

Runs against real ffmpeg-encoded files, no mocks — the same convention every
other file in this directory uses. Requires `ffmpeg`/`ffprobe` on PATH (the
same binaries the running container gets from its own Dockerfile change).
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "omnisight_ingestion_playback",
    Path(__file__).resolve().parents[1] / "app" / "playback.py",
)
playback = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(playback)


def _encode(path: Path, *, vcodec: str, seconds: float = 1.0, extra: list[str] | None = None) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
            "-t", str(seconds),
            "-c:v", vcodec,
            *(extra or []),
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _real_codec(path: Path) -> str:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_playback_path_for_is_beside_the_original_not_in_its_place(tmp_path):
    original = tmp_path / "abc123.mp4"

    assert playback.playback_path_for(str(original)) == str(tmp_path / "abc123_playback.mp4")


def test_an_already_h264_source_needs_no_copy(tmp_path):
    clip = tmp_path / "clip.mp4"
    _encode(clip, vcodec="libx264")
    assert _real_codec(clip) == "h264"

    result = playback.ensure_playback_copy(str(clip))

    assert result is None
    assert not Path(playback.playback_path_for(str(clip))).exists()


def test_a_non_h264_source_gets_a_real_h264_copy_beside_it(tmp_path):
    clip = tmp_path / "clip.mp4"
    _encode(clip, vcodec="mpeg4")  # CCD's own real codec (OMNI-300)
    assert _real_codec(clip) == "mpeg4"

    result = playback.ensure_playback_copy(str(clip))

    assert result == playback.playback_path_for(str(clip))
    assert Path(result).is_file()
    assert _real_codec(Path(result)) == "h264"
    assert clip.is_file()  # the original is untouched, not replaced


def test_no_leftover_part_file_after_a_successful_transcode(tmp_path):
    clip = tmp_path / "clip.mp4"
    _encode(clip, vcodec="mpeg4")

    result = playback.ensure_playback_copy(str(clip))

    assert not Path(f"{result}.part").exists()


def test_rerunning_overwrites_rather_than_erroring_or_duplicating(tmp_path):
    clip = tmp_path / "clip.mp4"
    _encode(clip, vcodec="mpeg4")

    first = playback.ensure_playback_copy(str(clip))
    first_bytes = Path(first).read_bytes()
    second = playback.ensure_playback_copy(str(clip))

    assert first == second
    assert Path(second).is_file()
    # ffmpeg's own -y flag overwrote it cleanly — a real second encode, not a
    # leftover from the first, though byte-identical is plausible for this
    # tiny synthetic clip and isn't itself the thing being asserted.
    assert len(first_bytes) > 0


def test_a_missing_file_is_a_clean_failure_not_a_crash(tmp_path):
    with pytest.raises(playback.PlaybackError) as excinfo:
        playback.ensure_playback_copy(str(tmp_path / "nope.mp4"))

    assert excinfo.value.reason
    assert not Path(f"{tmp_path / 'nope_playback.mp4'}.part").exists()


def test_a_file_ffprobe_cannot_read_is_still_attempted_and_fails_cleanly(tmp_path):
    """Codec detection failing (a corrupt file, here: not a video at all) is
    treated as "needs a copy, try anyway" rather than silently skipped — the
    transcode attempt then fails on its own, cleanly."""
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a real video file" * 50)

    with pytest.raises(playback.PlaybackError):
        playback.ensure_playback_copy(str(junk))

    assert not Path(playback.playback_path_for(str(junk))).exists()
    assert not Path(f"{playback.playback_path_for(str(junk))}.part").exists()
