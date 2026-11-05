"""Open-vocabulary boxes on search results (OMNI-X02, D-42). Not a Phase A requirement: an
addition on top of FR-4. Search says which frame matches; this says where in the frame.

    query text -> prompts: the query as typed + the object words it contains (built by query,
                  omnisight_common.box_prompts)
    stored full-frame JPEG (`frame_path`) -> YOLO-World (yolov8s-worldv2) with those prompts
               -> boxes with score >= min_score, overlapping boxes merged across prompts,
                  at most max_boxes, in fractions of the frame's width and height (0-1)

The weights file is pinned by SHA-256 and downloaded on the first start if missing, like the
encoders' checkpoints (D-30). The prompts' text encoder is OpenAI's CLIP ViT-B/32, which
ultralytics would otherwise `pip install` from GitHub at run time; it is a pinned dependency
instead, its weights kept beside YOLO-World's (clip checks their SHA-256 itself).
"""

import hashlib
import logging
import threading
import urllib.request
from collections.abc import Sequence
from pathlib import Path

from omnisight_common.box_prompts import label_for

logger = logging.getLogger("app.detector")

WEIGHTS_FILE = "yolov8s-worldv2.pt"
WEIGHTS_URL = "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s-worldv2.pt"
WEIGHTS_SHA256 = "9b2c17ab6124a913e9b3a5c170617920d91b0f01111a8479da69f00e2cf27792"


def ensure_weights(model_dir: str | Path) -> Path:
    """YOLO-World's weights at the pinned SHA-256, downloaded if missing. A file with another
    hash is never used: it is downloaded again, and if that does not match either, start fails."""
    path = Path(model_dir) / WEIGHTS_FILE
    if path.is_file() and _sha256(path) == WEIGHTS_SHA256:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    urllib.request.urlretrieve(WEIGHTS_URL, partial)
    digest = _sha256(partial)
    if digest != WEIGHTS_SHA256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"{WEIGHTS_URL} has SHA-256 {digest}, not the pinned {WEIGHTS_SHA256}")
    partial.replace(path)
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BoxDetector:
    def __init__(self, model_dir: str | Path, min_score: float, max_boxes: int, device: str = "cpu") -> None:
        from ultralytics.utils import SETTINGS

        SETTINGS.update({"sync": False})  # no usage events sent to Ultralytics
        import ultralytics.nn.text_model as text_model
        from ultralytics import YOLOWorld

        # CLIP's weights beside YOLO-World's on the models mount, not in the container.
        text_model.WEIGHTS_DIR = Path(model_dir)
        self.model = YOLOWorld(ensure_weights(model_dir))
        self.device = device
        self.min_score = min_score
        self.max_boxes = max_boxes
        self._prompts: list[str] | None = None
        # set_classes changes the model: one request at a time.
        self._lock = threading.Lock()

    def _set_prompts(self, prompts: list[str]) -> None:
        if prompts != self._prompts:
            # As YOLOWorld.set_classes, but CLIP is loaded once and kept, not on every call.
            self.model.model.set_classes(prompts, cache_clip_model=True)
            self.model.model.names = list(prompts)
            self.model.predictor = None
            self._prompts = list(prompts)

    def detect(self, paths: Sequence[str | Path], prompts: Sequence[str]) -> list[list[dict]]:
        """Per frame, in the order given: [{label, score, box: [x1, y1, x2, y2]}], the box in
        fractions of the frame. A frame that cannot be read gets an empty list."""
        prompts = list(dict.fromkeys(p.strip() for p in prompts if p.strip()))
        if not prompts:
            return [[] for _ in paths]
        out = []
        with self._lock:
            self._set_prompts(prompts)
            for path in paths:
                try:
                    [result] = self.model.predict(
                        str(path),
                        conf=self.min_score,
                        max_det=self.max_boxes,
                        # Overlapping boxes merged whichever prompt found them: otherwise one
                        # car gets a box for "a blue car" and another for "car" (D-42).
                        agnostic_nms=True,
                        device=self.device,
                        verbose=False,
                    )
                except (FileNotFoundError, OSError) as exc:
                    logger.warning("detect: frame unreadable", extra={"extra_fields": {"frame_path": str(path), "error": repr(exc)[:300]}})
                    out.append([])
                    continue
                boxes = result.boxes
                out.append([
                    {
                        "label": label_for(prompts[int(cls)], prompts),
                        "score": round(float(score), 4),
                        "box": [round(float(v), 4) for v in xyxyn],
                    }
                    for cls, score, xyxyn in zip(boxes.cls.tolist(), boxes.conf.tolist(), boxes.xyxyn.tolist(), strict=True)
                ])
        return out
