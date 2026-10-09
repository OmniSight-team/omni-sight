"""Probe every UCF-Crime and CCD video for its own fps, frame count and duration (OMNI-607).

Lead-up windows are cut in seconds against each video's real length, and the fps is read
from each file, never assumed (UCF-Crime's official frame numbers are at 30 fps; a video
at another rate is reported). The full videos are on Drive, the local mirror holds 38, so
this runs in Colab like `list_dataset_videos.py`.

For each dataset it probes every file in `<dataset>/video_files.txt` with `ffprobe` (the
container header only; no frame is decoded) and writes `<dataset>/video_probe.csv`:

  video_relpath,fps,frames,duration_s,error

`fps` is the stream's `avg_frame_rate`, `frames` its `nb_frames`, `duration_s` the
container's duration. A file that cannot be probed keeps its row with `error` filled in.

Standard library plus `ffprobe` (installed in Colab). Run with Drive mounted:

  from google.colab import drive; drive.mount('/content/drive')
  !python probe_dataset_videos.py /content/drive/MyDrive/omnisight/data

It also writes `<root>/omni607_probe.zip` holding the two CSVs. Unzip that into
`phase-b/data/` (paths inside the zip are relative to `data/`).
"""

import json
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

DATASETS = ("ucf_crime", "ccd")
HEADER = "video_relpath,fps,frames,duration_s,error"
WORKERS = 16  # Drive reads are slow per file, not per byte


def probe(path: Path) -> tuple[str, str, str, str]:
    """`(fps, frames, duration_s, error)` as CSV fields."""
    if not path.is_file():
        return "", "", "", "missing"
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=avg_frame_rate,nb_frames:format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, timeout=120, check=True,
        ).stdout
        info = json.loads(out)
        stream = info["streams"][0]
        fps = float(Fraction(stream["avg_frame_rate"]))
        duration = float(info["format"]["duration"])
        frames = stream.get("nb_frames", "")
        return f"{fps:.6g}", str(frames), f"{duration:.3f}", ""
    except (subprocess.SubprocessError, KeyError, IndexError, ValueError, ZeroDivisionError) as exc:
        return "", "", "", type(exc).__name__


def main(root: Path) -> None:
    zip_path = root / "omni607_probe.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for dataset in DATASETS:
            base = root / dataset
            listing = [ln.strip() for ln in (base / "video_files.txt").read_text(encoding="utf-8").splitlines() if ln.strip()]
            with ThreadPoolExecutor(WORKERS) as pool:
                results = list(pool.map(probe, [base / rel for rel in listing]))
            lines = [HEADER] + [",".join((rel, *r)) for rel, r in zip(listing, results, strict=True)]
            out = base / "video_probe.csv"
            out.write_text("\n".join(lines) + "\n", encoding="utf-8")
            z.write(out, f"{dataset}/video_probe.csv")
            errors = sum(1 for r in results if r[3])
            print(f"{dataset}: {len(listing)} videos probed, {errors} errors")
    print(f"wrote {zip_path} ({zip_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
