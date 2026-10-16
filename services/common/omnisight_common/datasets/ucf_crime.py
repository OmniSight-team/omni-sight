"""UCF-Crime loader: the 1,900 anomaly-detection videos (`docs/dataset-layout.md`).

- Identity: the filename, with `Normal_Videos_for_Event_Recognition/` excluded (its 50 files
  have namesakes in `Testing_Normal_Videos_Anomaly/`)
- Membership: the top-level `annotations/Anomaly_Train.txt` (the copy in
  `Anomaly_Detection_splits/` is 0 bytes) and `Anomaly_Detection_splits/Anomaly_Test.txt`,
  matched on the basename
- Class: the folder the video sits in on disk, never the `Anomaly-Videos-Part-N` level
- Times: test anomalies from the official temporal annotation (frame numbers at 30 fps, up
  to two intervals); training anomalies from UCA through the D-21 rule; none otherwise
"""

from pathlib import Path, PurePosixPath

from omnisight_common.datasets import AnnotationSource, ManifestEntry, read_listing
from omnisight_common.datasets.uca import load_uca, pick_event
from omnisight_common.domain import Domain

DATASET = "ucf_crime"
EXCLUDED_FOLDER = "Normal_Videos_for_Event_Recognition"
NORMAL_FOLDERS = ("Testing_Normal_Videos_Anomaly", "Training-Normal-Videos-Part-1", "Training-Normal-Videos-Part-2")
# The temporal annotation is written in frame numbers at 30 fps (ReadMe-Anomaly-Detection.txt).
ANNOTATION_FPS = 30.0


def _read_list(path: Path) -> list[str]:
    entries = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not entries:
        raise ValueError(f"{path} is empty")
    return entries


def _videos_by_name(listing: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for rel in listing:
        p = PurePosixPath(rel)
        if p.suffix != ".mp4" or EXCLUDED_FOLDER in p.parts:
            continue
        if p.name in out:
            raise ValueError(f"{p.name} is listed twice: {out[p.name]} and {rel}")
        out[p.name] = rel
    return out


def _temporal(path: Path) -> dict[str, tuple[str, list[tuple[float, float]]]]:
    """`name.mp4 -> (class, [(start_s, end_s), ...])`, frames converted at 30 fps."""
    out = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        parts = ln.split()
        if not parts:
            continue
        name, cls, *frames = parts
        s1, e1, s2, e2 = (int(f) for f in frames)
        intervals = [(s / ANNOTATION_FPS, e / ANNOTATION_FPS) for s, e in ((s1, e1), (s2, e2)) if s >= 0]
        out[name] = (cls, intervals)
    return out


def load(dataset_dir: Path) -> list[ManifestEntry]:
    ann = dataset_dir / "annotations"
    on_disk = _videos_by_name(read_listing(dataset_dir))
    temporal = _temporal(ann / "Temporal_Anomaly_Annotation_for_Testing_Videos.txt")
    uca = load_uca(ann / "uca" / "json")

    lists = {
        "train": _read_list(ann / "Anomaly_Train.txt"),
        "test": _read_list(ann / "Anomaly_Detection_splits" / "Anomaly_Test.txt"),
    }
    entries: list[ManifestEntry] = []
    seen: set[str] = set()
    for official_list, names in lists.items():
        for listed in names:
            listed_folder, name = PurePosixPath(listed).parent.name, PurePosixPath(listed).name
            if name in seen:
                raise ValueError(f"{name} is in both official lists")
            seen.add(name)
            rel = on_disk.get(name)
            if rel is None:
                raise ValueError(f"{listed} is in the {official_list} list but not on disk")
            folder = PurePosixPath(rel).parent.name
            is_normal = folder in NORMAL_FOLDERS
            event_class = "Normal" if is_normal else folder
            if not is_normal and event_class != listed_folder:
                raise ValueError(f"{name}: list says {listed_folder}, disk folder is {folder}")

            start = end = None
            attributes: dict = {"official_list": official_list}
            if is_normal:
                source = AnnotationSource.NORMAL
            elif official_list == "test":
                cls, intervals = temporal[name]
                if cls != event_class or not intervals:
                    raise ValueError(f"{name}: temporal annotation says {cls} with {len(intervals)} intervals")
                (start, end), *second = intervals
                if second:
                    attributes["second_interval"] = list(second[0])
                source = AnnotationSource.UCF_CRIME_TEMPORAL
            else:
                stem = name.removesuffix(".mp4")
                pick = pick_event(event_class, uca[stem][1]) if stem in uca else None
                if pick is None:
                    source = AnnotationSource.UNTIMED
                    attributes["untimed_reason"] = "not in UCA" if stem not in uca else "no UCA segment matches the class"
                else:
                    start, end, _ = pick
                    source = AnnotationSource.UCA
            entries.append(
                ManifestEntry(
                    dataset=DATASET,
                    clip_key=name,
                    domain=Domain.SURVEILLANCE,
                    event_class=event_class,
                    event_start_s=start,
                    event_end_s=end,
                    annotation_source=source,
                    video_relpath=rel,
                    attributes=attributes,
                )
            )
    return entries
