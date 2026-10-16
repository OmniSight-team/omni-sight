"""One loader per dataset, each emitting the same manifest entry (OMNI-604).

Every dataset keeps its native layout (`docs/dataset-layout.md`). A loader reads that
dataset's annotation files plus `video_files.txt`, the list of every video file on Drive
(written by `scripts/list_dataset_videos.py`), so the manifest covers the **whole**
dataset even though the local mirror holds only a few clips. Loaders only read files; the
manifest is written to Postgres by `scripts/build_dataset_manifest.py`.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from omnisight_common.domain import Domain

VIDEO_LISTING = "video_files.txt"


class AnnotationSource(StrEnum):
    """Where a clip's event time comes from, or why it has none."""

    UCF_CRIME_TEMPORAL = "ucf_crime_temporal"  # the official test-set annotation
    UCA = "uca"  # UCA through the D-21 rule
    CCD_BINLABELS = "ccd_binlabels"  # first `1` in Crash-1500.txt
    VIRAT_EVENTS = "virat_events"  # the clip's events / objects / mapping files
    NORMAL = "normal"  # a normal clip: there is no event
    UNTIMED = "untimed"  # an anomaly whose time is not known; it gets no window


@dataclass(frozen=True)
class ManifestEntry:
    dataset: str
    clip_key: str
    domain: Domain
    event_class: str | None
    event_start_s: float | None
    event_end_s: float | None
    annotation_source: AnnotationSource
    # Relative to the dataset's folder, as the file sits on Drive and in the mirror.
    video_relpath: str
    # What only one dataset has: a second interval, the CCD source video, the VIRAT scene ...
    attributes: dict = field(default_factory=dict)


def read_listing(dataset_dir: Path) -> list[str]:
    """`video_files.txt`: one relative path per line, forward slashes."""
    path = dataset_dir / VIDEO_LISTING
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        raise ValueError(f"{path} is empty")
    return lines
