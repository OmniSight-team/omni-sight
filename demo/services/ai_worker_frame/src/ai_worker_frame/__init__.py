"""ai-worker-frame — Algorithm 2 SigLIP2 frame embedding service."""

from .embedder import EMBED_DIM, MODEL_ID, embed_frame
from .pipeline import FrameRecord, process_frame

__all__ = ["EMBED_DIM", "MODEL_ID", "embed_frame", "FrameRecord", "process_frame"]
