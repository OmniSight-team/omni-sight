"""Algorithm 3 (Phase A §3.5.3, Appendix B.3): two ranked lists merged by rank, weighted by a
small classifier of the query (D-38). Here so Colab's SM-1 runs the same code as the product.

No model and no store: lists of segment ids in, a merged list out; a text vector in, two
weights out. The classifier's file is trained by `scripts/train_modality_classifier.py`.
"""

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

K0 = 60  # B.3's RRF constant
CLASSIFIER_FILE = Path(__file__).with_name("modality_classifier.json")


@dataclass(frozen=True)
class FusedHit:
    segment_id: int
    score: float
    # 1 is the top of a list; None is B.3's ∞, not in that list.
    rank_frame: int | None
    rank_clip: int | None

    @property
    def matched_by(self) -> str:
        if self.rank_frame is not None and self.rank_clip is not None:
            return "both"
        return "frame" if self.rank_frame is not None else "clip"


def fuse(frame_ids: Sequence[int], clip_ids: Sequence[int], w_f: float, w_c: float, k: int, k0: int = K0) -> list[FusedHit]:
    """B.3 lines 4-9. Each list is ranked best first. Equal scores come out by segment id:
    B.3 does not order them, and the same query must give the same answer."""
    rank_f = {segment_id: rank for rank, segment_id in enumerate(frame_ids, 1)}
    rank_c = {segment_id: rank for rank, segment_id in enumerate(clip_ids, 1)}
    hits = []
    for m in rank_f.keys() | rank_c.keys():
        r_f, r_c = rank_f.get(m), rank_c.get(m)
        # A missing rank is ∞, so its term is 0.
        score = (0.0 if r_f is None else w_f / (k0 + r_f)) + (0.0 if r_c is None else w_c / (k0 + r_c))
        hits.append(FusedHit(m, score, r_f, r_c))
    hits.sort(key=lambda hit: (-hit.score, hit.segment_id))
    return hits[:k]


class ModalityClassifier:
    """B.3 line 1, `(w_f, w_c) <- C(q)`: logistic regression on the query's SigLIP 2 text vector.

    A two-class logistic regression is a softmax over the logits `(z, 0)`, so `w_f` is the
    probability the query describes a scene, `w_c` that it describes an action."""

    def __init__(self, coefficients: Sequence[float], intercept: float) -> None:
        self.coefficients = coefficients
        self.intercept = intercept

    @classmethod
    def load(cls, model: str, model_revision: str, path: Path = CLASSIFIER_FILE) -> "ModalityClassifier":
        """Raises ValueError if it was trained on another text encoder's vectors."""
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data["model"], data["model_revision"]) != (model, model_revision):
            raise ValueError(f"trained on {data['model']}@{data['model_revision']}, not {model}@{model_revision}")
        return cls(data["coefficients"], data["intercept"])

    def weights(self, text_vector: Sequence[float]) -> tuple[float, float]:
        if len(text_vector) != len(self.coefficients):
            raise ValueError(f"a vector of {len(text_vector)} dimensions, trained on {len(self.coefficients)}")
        z = math.fsum(c * x for c, x in zip(self.coefficients, text_vector, strict=True)) + self.intercept
        w_f = 1.0 / (1.0 + math.exp(-z))
        return w_f, 1.0 - w_f
