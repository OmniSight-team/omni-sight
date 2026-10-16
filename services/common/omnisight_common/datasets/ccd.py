"""CCD loader: 1,500 crash clips and 3,000 normal clips (`docs/dataset-layout.md`).

- Identity: `(subset, id)`, written `Crash-1500/000001` — `000001.mp4` exists in both
  folders and they are different videos
- Crash labels: one line per clip in `videos/Crash-1500.txt`. The 50 frame labels sit in
  brackets *with* commas, so the bracketed block is pulled out with a regex before the rest
  is split. Event start = index of the first `1` / 10 fps
- Normal clips: no label file, every frame negative; taken from the disk listing
"""

import re
from pathlib import Path, PurePosixPath

from omnisight_common.datasets import AnnotationSource, ManifestEntry, read_listing
from omnisight_common.domain import Domain

DATASET = "ccd"
CRASH, NORMAL = "Crash-1500", "Normal"
CCD_FPS = 10.0
FRAMES_PER_CLIP = 50
LABEL_LINE = re.compile(r"^(?P<vid>\d+),\[(?P<bins>[^\]]*)\],(?P<rest>.*)$")
REST_FIELDS = ("startframe", "youtube_id", "timing", "weather", "ego_involved")


def parse_label_line(line: str) -> dict:
    m = LABEL_LINE.match(line.strip())
    if m is None:
        raise ValueError(f"not a Crash-1500.txt line: {line[:60]!r}")
    bins = [int(b) for b in m["bins"].split(",")]
    rest = m["rest"].split(",")
    if len(bins) != FRAMES_PER_CLIP or len(rest) != len(REST_FIELDS):
        raise ValueError(f"{m['vid']}: {len(bins)} frame labels and {len(rest)} other fields")
    return {"vid": m["vid"], "bins": bins, **dict(zip(REST_FIELDS, rest, strict=True))}


def load(dataset_dir: Path) -> list[ManifestEntry]:
    by_subset: dict[str, set[str]] = {CRASH: set(), NORMAL: set()}
    for rel in read_listing(dataset_dir):
        p = PurePosixPath(rel)
        if p.suffix == ".mp4" and p.parent.name in by_subset:
            by_subset[p.parent.name].add(p.stem)

    entries: list[ManifestEntry] = []
    labelled: set[str] = set()
    for line in (dataset_dir / "videos" / "Crash-1500.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = parse_label_line(line)
        vid = row["vid"]
        if vid in labelled:
            raise ValueError(f"Crash-1500.txt labels {vid} twice")
        labelled.add(vid)
        if vid not in by_subset[CRASH]:
            raise ValueError(f"Crash-1500.txt labels {vid}, which is not in videos/{CRASH}/")
        ones = [i for i, b in enumerate(row["bins"]) if b == 1]
        if not ones:
            raise ValueError(f"crash clip {vid} has no accident frame")
        entries.append(
            ManifestEntry(
                dataset=DATASET,
                clip_key=f"{CRASH}/{vid}",
                domain=Domain.TRAFFIC,
                event_class="Crash",
                event_start_s=ones[0] / CCD_FPS,
                event_end_s=(ones[-1] + 1) / CCD_FPS,
                annotation_source=AnnotationSource.CCD_BINLABELS,
                video_relpath=f"videos/{CRASH}/{vid}.mp4",
                attributes={k: row[k] for k in REST_FIELDS},
            )
        )
    unlabelled = by_subset[CRASH] - labelled
    if unlabelled:
        raise ValueError(f"{len(unlabelled)} crash clips have no label line, e.g. {sorted(unlabelled)[:3]}")

    for vid in sorted(by_subset[NORMAL]):
        entries.append(
            ManifestEntry(
                dataset=DATASET,
                clip_key=f"{NORMAL}/{vid}",
                domain=Domain.TRAFFIC,
                event_class="Normal",
                event_start_s=None,
                event_end_s=None,
                annotation_source=AnnotationSource.NORMAL,
                video_relpath=f"videos/{NORMAL}/{vid}.mp4",
            )
        )
    return entries
