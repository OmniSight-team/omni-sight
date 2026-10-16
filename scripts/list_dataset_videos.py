"""List every video of UCF-Crime, CCD and VIRAT on Drive, and pack what the local mirror lacks (OMNI-604).

The manifest covers the whole of each dataset, but the local mirror holds 38 clips. So the
loaders read `<dataset>/video_files.txt`, one relative path per video file, written here from
the full copy on Drive. VIRAT's full `annotations/` folder is small and is packed too, **with
its empty directories**: 122 annotation "files" are empty directories, and the loader must
meet them locally exactly as it does on Drive.

Standard library only. Run in Colab with Drive mounted:

  from google.colab import drive; drive.mount('/content/drive')
  !python list_dataset_videos.py /content/drive/MyDrive/omnisight/data

It writes `video_files.txt` into each dataset folder on Drive and
`<root>/omni604_mirror.zip` holding the three listings and `virat/annotations/`. Unzip that
into `phase-b/data/` (paths inside the zip are relative to `data/`).
"""

import os
import sys
import zipfile
from pathlib import Path

DATASETS = {
    "ucf_crime": "videos",
    "ccd": "videos",
    "virat": "videos_original",
}


def list_videos(root: Path, dataset: str, folder: str) -> list[str]:
    base = root / dataset
    out = []
    for dirpath, _, filenames in os.walk(base / folder):
        for f in filenames:
            if f.lower().endswith(".mp4"):
                out.append((Path(dirpath) / f).relative_to(base).as_posix())
    return sorted(out)


def main(root: Path) -> None:
    zip_path = root / "omni604_mirror.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for dataset, folder in DATASETS.items():
            videos = list_videos(root, dataset, folder)
            listing = root / dataset / "video_files.txt"
            listing.write_text("".join(v + "\n" for v in videos), encoding="utf-8")
            z.write(listing, f"{dataset}/video_files.txt")
            print(f"{dataset}: {len(videos)} videos")

        ann = root / "virat" / "annotations"
        files = dirs = 0
        for entry in sorted(ann.iterdir()):
            arc = f"virat/annotations/{entry.name}"
            if entry.is_file():
                z.write(entry, arc)
                files += 1
            elif entry.is_dir():
                z.writestr(arc + "/", "")
                dirs += 1
        print(f"virat/annotations: {files} files, {dirs} empty directories")
    print(f"wrote {zip_path} ({zip_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
