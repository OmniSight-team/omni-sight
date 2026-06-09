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

MODEL_ID = "google/siglip2-base-patch16-224"
EMBED_DIM = 768


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
    pixel_values = inputs["pixel_values"].to(device)

    with torch.no_grad():
        vision_out = model.vision_model(pixel_values=pixel_values)
        pooled = vision_out.pooler_output  # (1, hidden_size)
        if hasattr(model, "visual_projection"):
            pooled = model.visual_projection(pooled)

    vec: np.ndarray = pooled[0].cpu().float().numpy()  # (EMBED_DIM,)
    norm = np.linalg.norm(vec)
    if norm > 0.0:
        vec = vec / norm
    return vec
