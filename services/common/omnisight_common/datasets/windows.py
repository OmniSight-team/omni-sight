"""Lead-up windows, derived by working backward from each known event (OMNI-607, D-24).

Phase A §3.4 and §3.6: windows are derived "by working backward from each known event";
the predictor sees "30s and 60s sliding windows" (§4.1, TC-5). No dataset ships them.

- **Positive window:** `[event_start - L, event_start)`, so it never contains any part of
  the event. UCF-Crime: L = 30 s and 60 s. CCD: one window `[0, accident_start)`, as long as
  the footage is (under 5 s, D-2); no 30 s or 60 s window exists on CCD and none is made
- **Too little footage:** the window starts at 0 instead, and is flagged `shortened`
- **No window:** recorded with its reason, never dropped silently — the second interval of
  a UCF-Crime test video (its lead-up overlaps the first event), an event at 0 s, an event
  past the probed end of its video, an anomaly with no event time
- **Negative window:** one per normal video and length, at a seeded random position inside
  the video, in the video's own split. CCD normals take a length drawn from the crash
  windows of the same split
- **Duration and fps** come from each video's own probe (`video_probe.csv`, written by
  `scripts/probe_dataset_videos.py`), never assumed

Pure functions over the loaders' entries, the committed split and the probes, so Colab can
import them. Deterministic: seed 607, inputs sorted before any random draw.
"""

import math
import random
from dataclasses import dataclass
from pathlib import Path

from omnisight_common.datasets import AnnotationSource, ManifestEntry
from omnisight_common.domain import Domain

SEED = 607
UCF_LENGTHS_S = (30.0, 60.0)
POSITIVE, NEGATIVE = "positive", "negative"
SHORTENED = "shortened"
PROBE_LISTING = "video_probe.csv"
# The rate each dataset's labels are written at: UCF-Crime's official frame numbers (its
# readme) and CCD's binlabels (one per frame at 10 fps). A video at another rate is reported.
LABEL_FPS = {"ucf_crime": 30.0, "ccd": 10.0}

WINDOWS_HEADER = (
    "clip_key,video_relpath,kind,nominal_length_s,window_start_s,window_end_s,length_s,event_class,split,fps,flags"
)
SKIPPED_HEADER = "clip_key,event_class,split,interval,nominal_length_s,reason"

# Why an event has no window.
SECOND_INTERVAL = "second interval: its lead-up overlaps the first event"
EVENT_AT_ZERO = "event starts at 0 s: no footage before it"
EVENT_PAST_END = "event starts after the probed end of the video"
UNTIMED = "no event time"


@dataclass(frozen=True)
class Probe:
    fps: float
    frames: int | None
    duration_s: float


@dataclass(frozen=True)
class Window:
    clip_key: str
    video_relpath: str
    kind: str  # POSITIVE or NEGATIVE
    nominal_length_s: float | None  # L for UCF-Crime; None on CCD, where windows are as long as the footage
    window_start_s: float
    window_end_s: float
    event_class: str
    domain: Domain
    split: str
    fps: float
    shortened: bool

    @property
    def length_s(self) -> float:
        return round(self.window_end_s - self.window_start_s, 3)


@dataclass(frozen=True)
class Skipped:
    clip_key: str
    event_class: str
    split: str
    interval: int  # 1 = the event, 2 = UCF-Crime's second interval
    nominal_length_s: float | None
    reason: str


def read_probes(dataset_dir: Path) -> dict[str, Probe]:
    """`video_probe.csv` -> `{video_relpath: Probe}`. A row with an error raises."""
    path = dataset_dir / PROBE_LISTING
    out: dict[str, Probe] = {}
    for ln in path.read_text(encoding="utf-8").splitlines()[1:]:
        if not ln.strip():
            continue
        rel, fps, frames, duration, error = ln.split(",")
        if error:
            raise ValueError(f"{path}: {rel} could not be probed ({error})")
        out[rel] = Probe(float(fps), int(frames) if frames else None, float(duration))
    return out


def _probe(probes: dict[str, Probe], e: ManifestEntry) -> Probe:
    p = probes.get(e.video_relpath)
    if p is None:
        raise ValueError(f"{e.dataset} {e.clip_key}: {e.video_relpath} has no probe")
    return p


def off_rate(entries: list[ManifestEntry], probes: dict[str, Probe], dataset: str) -> list[tuple[str, float]]:
    """Videos whose probed fps is not the rate the dataset's labels are written at."""
    want = LABEL_FPS[dataset]
    return sorted(
        (e.clip_key, _probe(probes, e).fps) for e in entries if not math.isclose(_probe(probes, e).fps, want, abs_tol=0.01)
    )


def _ms(x: float) -> float:
    return round(x, 3)


def _positive(e: ManifestEntry, split: str, probe: Probe, length: float | None) -> Window:
    end = _ms(e.event_start_s)
    start = 0.0 if length is None else _ms(max(0.0, end - length))
    return Window(
        clip_key=e.clip_key, video_relpath=e.video_relpath, kind=POSITIVE, nominal_length_s=length,
        window_start_s=start, window_end_s=end, event_class=e.event_class, domain=e.domain, split=split,
        fps=probe.fps, shortened=length is not None and end < length,
    )


def _negative(e: ManifestEntry, split: str, probe: Probe, length: float, nominal: float | None, rng: random.Random) -> Window:
    duration = _ms(probe.duration_s)
    if duration <= length:
        start, end, shortened = 0.0, duration, True
    else:
        # Floored to the millisecond so the window never runs past the video's end.
        start = math.floor(rng.random() * (duration - length) * 1000) / 1000
        end, shortened = _ms(start + length), False
    return Window(
        clip_key=e.clip_key, video_relpath=e.video_relpath, kind=NEGATIVE, nominal_length_s=nominal,
        window_start_s=start, window_end_s=end, event_class=e.event_class, domain=e.domain, split=split,
        fps=probe.fps, shortened=shortened,
    )


def _event_skip_reason(e: ManifestEntry, probe: Probe) -> str | None:
    if e.event_start_s is None:
        return UNTIMED
    if _ms(e.event_start_s) <= 0:
        return EVENT_AT_ZERO
    if e.event_start_s > probe.duration_s:
        return EVENT_PAST_END
    return None


def derive_ucf_crime(
    entries: list[ManifestEntry], split: dict[str, str], probes: dict[str, Probe]
) -> tuple[list[Window], list[Skipped]]:
    windows: list[Window] = []
    skipped: list[Skipped] = []
    rng = random.Random(SEED)
    for e in sorted(entries, key=lambda e: e.clip_key):
        s, probe = split[e.clip_key], _probe(probes, e)
        if e.annotation_source == AnnotationSource.NORMAL:
            for length in UCF_LENGTHS_S:
                windows.append(_negative(e, s, probe, length, length, rng))
            continue
        reason = _event_skip_reason(e, probe)
        for length in UCF_LENGTHS_S:
            if reason is None:
                windows.append(_positive(e, s, probe, length))
            else:
                skipped.append(Skipped(e.clip_key, e.event_class, s, 1, length, reason))
            if "second_interval" in e.attributes:
                skipped.append(Skipped(e.clip_key, e.event_class, s, 2, length, SECOND_INTERVAL))
    return windows, skipped


def derive_ccd(
    entries: list[ManifestEntry], split: dict[str, str], probes: dict[str, Probe]
) -> tuple[list[Window], list[Skipped]]:
    windows: list[Window] = []
    skipped: list[Skipped] = []
    for e in sorted(entries, key=lambda e: e.clip_key):
        if e.annotation_source != AnnotationSource.CCD_BINLABELS:
            continue
        s, probe = split[e.clip_key], _probe(probes, e)
        reason = _event_skip_reason(e, probe)
        if reason is None:
            windows.append(_positive(e, s, probe, None))
        else:
            skipped.append(Skipped(e.clip_key, e.event_class, s, 1, None, reason))

    # Normals take their length from the crash windows of their own split.
    pool: dict[str, list[float]] = {}
    for w in windows:
        pool.setdefault(w.split, []).append(w.length_s)
    rng = random.Random(SEED)
    for e in sorted(entries, key=lambda e: e.clip_key):
        if e.annotation_source != AnnotationSource.NORMAL:
            continue
        s = split[e.clip_key]
        length = rng.choice(sorted(pool[s]))
        windows.append(_negative(e, s, _probe(probes, e), length, None, rng))
    return windows, skipped


DERIVERS = {"ucf_crime": derive_ucf_crime, "ccd": derive_ccd}


def _num(x: float | None) -> str:
    return "" if x is None else f"{x:.3f}".rstrip("0").rstrip(".")


def windows_csv(windows: list[Window]) -> bytes:
    """The exported file: sorted by clip, kind, length; LF line endings."""
    rows = sorted(windows, key=lambda w: (w.clip_key, w.kind, w.nominal_length_s or 0.0))
    lines = [WINDOWS_HEADER] + [
        ",".join((
            w.clip_key, w.video_relpath, w.kind, _num(w.nominal_length_s), _num(w.window_start_s),
            _num(w.window_end_s), _num(w.length_s), w.event_class, w.split, f"{w.fps:.6g}",
            SHORTENED if w.shortened else "",
        ))
        for w in rows
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def skipped_csv(skipped: list[Skipped]) -> bytes:
    rows = sorted(skipped, key=lambda k: (k.clip_key, k.interval, k.nominal_length_s or 0.0))
    lines = [SKIPPED_HEADER] + [
        f"{k.clip_key},{k.event_class},{k.split},{k.interval},{_num(k.nominal_length_s)},{k.reason}" for k in rows
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")
