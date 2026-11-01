"""SigLIP 2 frame and text encoder (OMNI-704), Algorithm 2 line 1 (Phase A Appendix B.2):

    e_f ← SigLIP2_image(f_t); e_f ← e_f / ||e_f||        (1152-D)

and the same model's text tower for a search query, so a query and a frame land in the
same space. The same code runs here on the CPU and on Colab's GPU (D-26): it imports
nothing from this service but torch and transformers, and takes the checkpoint's folder
and a device. Frames are read from the stored full-frame JPEG (`frame_path`) in both
places, so both see the same input.
"""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

EMBEDDING_DIM = 1152
# SigLIP 2's text tower was trained on lowercased text padded to 64 tokens. The processor
# applies neither by default; text that is not padded the same way still encodes, but
# matches worse, with no error to show it. Pinned by test_encoder.py.
TEXT_MAX_LENGTH = 64
# How close to 1 a normalised vector's length must be (float32 rounding).
UNIT_TOLERANCE = 1e-4
REVISION_FILE = "REVISION"


ALLOW_PATTERNS = ["*.json", "*.safetensors", "tokenizer.model"]


def ensure_checkpoint(model_id: str, revision: str, model_dir: str | Path,
                      allow_patterns: list[str] = ALLOW_PATTERNS) -> Path:
    """The checkpoint's files at the pinned revision, downloaded if missing.

    A `REVISION` file in the folder records which revision its files are; a folder holding
    any other revision is brought to the pinned one rather than silently used. Used for
    InternVideo2 too (OMNI-706), with that checkpoint's own `allow_patterns`.
    """
    folder = Path(model_dir)
    marker = folder / REVISION_FILE
    if not marker.is_file() or marker.read_text().strip() != revision:
        from huggingface_hub import snapshot_download

        snapshot_download(
            model_id,
            revision=revision,
            local_dir=folder,
            allow_patterns=allow_patterns,
        )
        marker.write_text(revision + "\n")
    return folder


def text_inputs(processor, texts: Sequence[str]):
    """Tokens for the text tower, prepared the way SigLIP 2 was trained (TEXT_MAX_LENGTH)."""
    return processor(
        text=[t.lower() for t in texts],
        padding="max_length",
        max_length=TEXT_MAX_LENGTH,
        truncation=True,
        return_tensors="pt",
    )


class FrameTextEncoder:
    def __init__(self, model_dir: str | Path, device: str = "cpu") -> None:
        self.device = device
        self.processor = AutoProcessor.from_pretrained(model_dir)
        # float32 on both machines: the same numbers locally and on Colab.
        self.model = AutoModel.from_pretrained(model_dir, dtype=torch.float32).to(device).eval()

    @torch.inference_mode()
    def encode_images(self, paths: Sequence[str | Path]) -> np.ndarray:
        """One unit-length 1152-D row per image, in the order given."""
        images = []
        for path in paths:
            with Image.open(path) as image:
                images.append(image.convert("RGB"))
        inputs = self.processor(images=images, return_tensors="pt").to(self.device)
        features = self.model.get_image_features(**inputs).pooler_output
        return _unit_rows(features)

    @torch.inference_mode()
    def encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        inputs = text_inputs(self.processor, texts).to(self.device)
        features = self.model.get_text_features(**inputs).pooler_output
        return _unit_rows(features)


def _unit_rows(features: torch.Tensor) -> np.ndarray:
    vectors = torch.nn.functional.normalize(features.float(), dim=-1).cpu().numpy()
    if vectors.ndim != 2 or vectors.shape[1] != EMBEDDING_DIM:
        raise ValueError(f"expected {EMBEDDING_DIM}-D embeddings, got shape {vectors.shape}")
    norms = np.linalg.norm(vectors, axis=1)
    if not np.all(np.isfinite(vectors)) or np.any(np.abs(norms - 1.0) > UNIT_TOLERANCE):
        raise ValueError(f"embeddings are not finite unit vectors (norms {norms.min()}..{norms.max()})")
    return vectors
