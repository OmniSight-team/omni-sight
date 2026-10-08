"""VIRAT loader: the 275 videos with events, for SM-1 only (`docs/dataset-layout.md`).

- Identity: the base name; `videos_original/<name>.mp4` <-> `annotations/<name>.viratdata.*.txt`
- A missing annotation is often an **empty directory** with the file's name, so every
  annotation path is checked with `isfile()`, never `exists()`
- Events, objects and mapping are read together: events say what and when, objects say
  where, mapping says which objects take part in which event. A video is kept only when all
  three are real files and agree with each other
- Scene from the filename: `VIRAT_S_0500xx_...` is scene `0500`

VIRAT has many events per video and is used for search evaluation, not for lead-up windows,
so the manifest row carries no event class or time; the event and object counts go in
`attributes`.
"""

from pathlib import Path, PurePosixPath

from omnisight_common.datasets import AnnotationSource, ManifestEntry, read_listing
from omnisight_common.domain import Domain

DATASET = "virat"
KINDS = ("events", "objects", "mapping")


def annotation_path(dataset_dir: Path, name: str, kind: str) -> Path:
    return dataset_dir / "annotations" / f"{name}.viratdata.{kind}.txt"


def scene_of(name: str) -> str:
    """`VIRAT_S_050201_05_000890_000944` -> `0502`."""
    return name.split("_")[2][:4]


def _rows(path: Path) -> list[list[int]]:
    return [[int(float(x)) for x in ln.split()] for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def read_annotations(dataset_dir: Path, name: str) -> dict:
    """The three files of one video, checked against each other. Raises if they disagree."""
    events = _rows(annotation_path(dataset_dir, name, "events"))
    objects = _rows(annotation_path(dataset_dir, name, "objects"))
    mapping = _rows(annotation_path(dataset_dir, name, "mapping"))
    event_ids = {r[0] for r in events}
    object_ids = {r[0] for r in objects}
    if not event_ids:
        raise ValueError(f"{name}: events file has no events")
    if {r[0] for r in mapping} != event_ids:
        raise ValueError(f"{name}: mapping and events name different events")
    for r in mapping:
        involved = {i for i, flag in enumerate(r[6:]) if flag == 1}
        if len(involved) != r[5] or not involved <= object_ids:
            raise ValueError(f"{name}: event {r[0]} maps to objects {sorted(involved)} not all in objects file")
    return {"events": len(event_ids), "objects": len(object_ids), "event_types": sorted({r[1] for r in events})}


def load(dataset_dir: Path) -> list[ManifestEntry]:
    entries = []
    for rel in read_listing(dataset_dir):
        p = PurePosixPath(rel)
        if p.suffix != ".mp4" or p.parent.name != "videos_original":
            continue
        name = p.stem
        present = {k: annotation_path(dataset_dir, name, k).is_file() for k in KINDS}
        if not present["events"]:
            continue
        if not all(present.values()):
            raise ValueError(f"{name}: has events but not {[k for k, v in present.items() if not v]}")
        counts = read_annotations(dataset_dir, name)
        entries.append(
            ManifestEntry(
                dataset=DATASET,
                clip_key=name,
                domain=Domain.SURVEILLANCE,
                event_class=None,
                event_start_s=None,
                event_end_s=None,
                annotation_source=AnnotationSource.VIRAT_EVENTS,
                video_relpath=rel,
                attributes={"scene": scene_of(name), **counts},
            )
        )
    return entries
