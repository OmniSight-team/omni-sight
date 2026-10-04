"""Make the RTSP simulator's realistic clip set (OMNI-509) from the local dataset
subset in `data/`.

Ten real surveillance clips, re-encoded only as far as the simulator needs:
H.264, no audio, native size and frame rate, a keyframe every 2 s (so a camera
starting to read the stream waits at most 2 s for a picture). Written to
`infra/mediamtx/clips/real/real01_<name>.mp4` ... `real10_...`, the files
`infra/mediamtx/mediamtx.real.yml` loops on cam01 to cam20.

  three from VIRAT       1280x720, 23.97 fps, outdoor fixed cameras
  four UCF-Crime normal  320x240, 30 fps, fixed CCTV, mostly quiet
  three UCF-Crime        320x240, 30 fps, fixed CCTV, with an incident

Needs `ffmpeg` and `ffprobe` on the PATH and the files below in `data/` (the local
subset, docs/dataset-layout.md). Run from the repo root, then restart the
simulator so it picks them up (`docker compose up -d mediamtx`):

  uv run python scripts/make_simulator_clips.py
"""

import subprocess
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "infra" / "mediamtx" / "clips" / "real"
SOURCES = [
    "data/virat/videos_original/VIRAT_S_010003_07_000608_000636.mp4",
    "data/virat/videos_original/VIRAT_S_010107_02_000282_000312.mp4",
    "data/virat/videos_original/VIRAT_S_010208_07_000768_000791.mp4",
    "data/ucf_crime/videos/Training-Normal-Videos-Part-1/Normal_Videos155_x264.mp4",
    "data/ucf_crime/videos/Training-Normal-Videos-Part-1/Normal_Videos170_x264.mp4",
    "data/ucf_crime/videos/Training-Normal-Videos-Part-1/Normal_Videos297_x264.mp4",
    "data/ucf_crime/videos/Training-Normal-Videos-Part-1/Normal_Videos344_x264.mp4",
    "data/ucf_crime/videos/Anomaly-Videos-Part-1/Arrest/Arrest013_x264.mp4",
    "data/ucf_crime/videos/Anomaly-Videos-Part-2/Burglary/Burglary081_x264.mp4",
    "data/ucf_crime/videos/Anomaly-Videos-Part-3/Robbery/Robbery089_x264.mp4",
]


def probe(path: Path, entries: str) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", entries, "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


OUT.mkdir(parents=True, exist_ok=True)
for n, relative in enumerate(SOURCES, start=1):
    source = ROOT / relative
    fps = Fraction(probe(source, "stream=avg_frame_rate"))
    keyframe_every = round(2 * fps)  # a keyframe every 2 s
    target = OUT / f"real{n:02d}_{source.stem}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source), "-an", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "23", "-pix_fmt", "yuv420p", "-g", str(keyframe_every), "-keyint_min", str(keyframe_every),
         "-sc_threshold", "0", str(target)],
        check=True,
    )
    print(f"{target.name}: {probe(target, 'stream=codec_name,width,height,avg_frame_rate')}")
