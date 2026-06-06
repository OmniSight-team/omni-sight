"""Algorithm 2 — SigLIP2 image embedding (frame path).

Input:  f_t BGR frame from Algorithm 1 (sampler.Payload.frame)
Output: L2-normalized float32 ndarray, shape (EMBED_DIM,)
"""
from __future__ import annotations

import logging
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

MODEL_ID = "google/siglip2-so400m-patch16-naflex"
EMBED_DIM = 1152


@lru_cache(maxsize=1)
def _load_model():
    import torch
    from transformers import AutoModel, AutoProcessor

    logger.info("Loading SigLIP2 %s", MODEL_ID)
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID, torch_dtype=torch.float32)
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    logger.info("SigLIP2 ready on %s", device)
    return processor, model, device


def embed_frame(frame_bgr: np.ndarray) -> np.ndarray:
    """Encode a BGR frame → L2-normalized (EMBED_DIM,) float32 vector."""
    import torch

    processor, model, device = _load_model()

    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)

    inputs = processor(images=img, return_tensors="pt")
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        features = model.get_image_features(**inputs)  # (1, EMBED_DIM)

    vec: np.ndarray = features[0].cpu().float().numpy()
    norm = np.linalg.norm(vec)
    if norm > 0.0:
        vec = vec / norm
    return vec
