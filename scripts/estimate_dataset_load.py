"""Size and frames of the footage OMNI-608 loads into the product, read on Drive.

Before loading, the ticket asks for each subset's total size and frames (`ffprobe`), and a
load time from OMNI-311's measured publish cost. The subsets are listed in
`omni608_subsets.txt` (`dataset,video_relpath` per line: CCD all 4,500, VIRAT the 275 with
events, UCF-Crime the 290 held-out), made from the manifest by
`scripts/plan_dataset_load.py`.

Standard library plus `ffprobe`. In Colab with Drive mounted, both files uploaded:

  !python estimate_dataset_load.py /content/drive/MyDrive/omnisight/data omni608_subsets.txt

Writes `<root>/omni608_estimate.csv`
(`dataset,video_relpath,size_bytes,fps,frames,duration_s,error`) and prints totals.
"""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

WORKERS = 16


def probe(path: Path) -> tuple[str, str, str, str, str]:
    """`(size_bytes, fps, frames, duration_s, error)` as CSV fields."""
    if not path.is_file():
        return "", "", "", "", "missing"
    size = str(path.stat().st_size)
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
        return size, f"{fps:.6g}", str(stream.get("nb_frames", "")), f"{float(info['format']['duration']):.3f}", ""
    except (subprocess.SubprocessError, KeyError, IndexError, ValueError, ZeroDivisionError) as exc:
        return size, "", "", "", type(exc).__name__


def main(root: Path, subsets: Path) -> None:
    rows = [ln.strip().split(",", 1) for ln in subsets.read_text(encoding="utf-8").splitlines() if ln.strip()]
    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(probe, [root / d / rel for d, rel in rows]))
    lines = ["dataset,video_relpath,size_bytes,fps,frames,duration_s,error"]
    lines += [",".join((d, rel, *r)) for (d, rel), r in zip(rows, results, strict=True)]
    out = root / "omni608_estimate.csv"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for dataset in sorted({d for d, _ in rows}):
        rs = [r for (d, _), r in zip(rows, results, strict=True) if d == dataset]
        size = sum(int(r[0]) for r in rs if r[0])
        frames = sum(int(r[2]) for r in rs if r[2])
        errors = sum(1 for r in rs if r[4])
        print(f"{dataset}: {len(rs)} videos, {size / 1e9:.2f} GB, {frames:,} frames, {errors} errors")
    print(f"wrote {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
