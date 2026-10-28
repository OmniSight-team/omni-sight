"""InternVideo2 clip and text encoder (OMNI-706), Algorithm 2 lines 2-3 (Phase A Appendix B.2):

    W_s ← uniform_subsample(W, 8 frames @ 224 x 224)
    e_c ← InternVideo2_clip(W_s); e_c ← e_c / ||e_c||

and the same model's text tower for a search query (Algorithm 3 line 2), so a query and a
clip land in the same space. Like encoder.py (D-30), the same code runs here on the CPU
and on Colab's GPU: it imports nothing from this service but the model code beside it
(`app/internvideo2`, copied from the checkpoint, D-33), takes the checkpoint's folder and a
device, and computes in float32 on both.

On the laptop only the text side is loaded (D-32): `video=False` reads only the text
tower's weights.
"""

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import torch
from safetensors import safe_open

# Relative, so the tests can load `app` under another name (query and ingestion also have
# a top-level package called `app`).
from .internvideo2.text import TextTransformer
from .internvideo2.vision import InternVideo2

# The retrieval space: the vision features (768) are projected to 512 by `vision_align`,
# and the text tower projects to 512 too. Phase A writes 768 (D-33).
EMBEDDING_DIM = 512
NUM_FRAMES = 8
IMAGE_SIZE = 224
# The checkpoint's own transform (its modeling_internvideo2encoder.py): every frame resized
# to 224 x 224 (bicubic, aspect ratio not kept), scaled to [0, 1], ImageNet mean and std.
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
# Only the weights and the config are downloaded; never the checkpoint's code.
ALLOW_PATTERNS = ["config.json", "model.safetensors"]
UNIT_TOLERANCE = 1e-4


def uniform_indices(start: int, end: int, count: int = NUM_FRAMES) -> list[int]:
    """`uniform_subsample`: `count` frame indices spread evenly over [start, end], the
    middle of each of `count` equal parts, as the checkpoint's own "middle" sampling
    (its demo.py, `get_frame_indices`). A span shorter than `count` frames is padded with
    its last frame, as there, rather than read outside it."""
    if end < start:
        raise ValueError(f"empty span [{start}, {end}]")
    parts = min(count, end + 1 - start)
    edges = np.linspace(start, end + 1, parts + 1).astype(int)
    indices = [int((edges[i] + edges[i + 1] - 1) // 2) for i in range(parts)]
    return indices + [indices[-1]] * (count - parts)


def read_clip(video_path: str | Path, indices: Sequence[int]) -> list[np.ndarray]:
    """The frames at `indices` of a video file, as RGB arrays (H x W x 3, uint8)."""
    import cv2  # only where clips are read from files (Colab, scripts); not in the service

    capture = cv2.VideoCapture(str(video_path))
    try:
        frames = []
        for index in indices:
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok:
                raise ValueError(f"{video_path}: cannot read frame {index}")
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        return frames
    finally:
        capture.release()


class ClipTextEncoder:
    def __init__(self, model_dir: str | Path, device: str = "cpu", *, video: bool = True) -> None:
        from open_clip.tokenizer import SimpleTokenizer

        folder = Path(model_dir)
        weights = folder / "model.safetensors"
        config = json.loads((folder / "config.json").read_text())["model"]
        self.device = device

        text_cfg = config["text_encoder"]
        # The tokenizer the checkpoint was trained with: open_clip's for ViT-B-16 (its
        # mobile_clip.py), which lowercases and cleans the text itself; 77 tokens.
        self.tokenizer = SimpleTokenizer(context_length=text_cfg["text_cfg"]["context_length"])
        self.text = TextTransformer(text_cfg["text_cfg"], projection_dim=text_cfg["embed_dim"])
        _load(self.text, weights, "text_encoder.")
        self.text.to(device).eval()

        self.vision = self.align = None
        if video:
            cfg = config["vision_encoder"]
            if cfg["sep_pos_embed"] or cfg["use_flash_attn"] or cfg["use_fused_mlp"] or cfg["use_fused_rmsnorm"]:
                raise ValueError("this checkpoint's config asks for a path the copied model code does not have")
            self.vision = InternVideo2(
                in_chans=cfg["in_chans"], patch_size=cfg["patch_size"], img_size=cfg["img_size"],
                qkv_bias=cfg["qkv_bias"], embed_dim=cfg["embed_dim"], num_heads=cfg["num_heads"],
                mlp_ratio=cfg["mlp_ratio"], init_values=cfg["init_values"],
                qk_normalization=cfg["qk_normalization"], depth=cfg["depth"],
                attn_pool_num_heads=cfg["attn_pool_num_heads"], clip_embed_dim=cfg["clip_embed_dim"],
                num_frames=cfg["num_frames"], tubelet_size=cfg["tubelet_size"],
            )
            self.align = torch.nn.Sequential(
                torch.nn.LayerNorm(cfg["clip_embed_dim"]),
                torch.nn.Linear(cfg["clip_embed_dim"], cfg["align_dim"]),
            )
            _load(self.vision, weights, "vision_encoder.")
            _load(self.align, weights, "vision_align.")
            self.vision.to(device).eval()
            self.align.to(device).eval()

    @torch.inference_mode()
    def encode_clips(self, clips: Sequence[Sequence[np.ndarray]]) -> np.ndarray:
        """One unit-length 512-D row per clip; each clip is NUM_FRAMES RGB frames in time
        order (H x W x 3, uint8, any size)."""
        if self.vision is None:
            raise RuntimeError("loaded with video=False: only the text side is here (D-32)")
        batch = []
        for frames in clips:
            if len(frames) != NUM_FRAMES:
                raise ValueError(f"a clip is {NUM_FRAMES} frames, got {len(frames)}")
            batch.append(_prepare(frames))
        video = torch.stack(batch).to(self.device).permute(0, 2, 1, 3, 4)  # B, C, T, H, W
        return _unit_rows(self.align(self.vision(video)))

    @torch.inference_mode()
    def encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        tokens = self.tokenizer(list(texts)).to(self.device)
        return _unit_rows(self.text(tokens))


def _prepare(frames: Sequence[np.ndarray]) -> torch.Tensor:
    """T x C x 224 x 224, float, normalised: the checkpoint's transform."""
    from torchvision.transforms import InterpolationMode
    from torchvision.transforms.functional import normalize, resize

    tensor = torch.from_numpy(np.stack(frames)).permute(0, 3, 1, 2)  # T, C, H, W, uint8
    tensor = resize(tensor, [IMAGE_SIZE, IMAGE_SIZE], interpolation=InterpolationMode.BICUBIC)
    return normalize(tensor.float().div(255.0), MEAN, STD)


def _load(module: torch.nn.Module, weights: Path, prefix: str) -> None:
    """The weights under `prefix`, in float32; every parameter of `module` must be there
    and nothing else under the prefix."""
    with safe_open(str(weights), "pt") as source:
        state = {key[len(prefix):]: source.get_tensor(key).float() for key in source.keys() if key.startswith(prefix)}
    module.float()
    module.load_state_dict(state, strict=True)


def _unit_rows(features: torch.Tensor) -> np.ndarray:
    vectors = torch.nn.functional.normalize(features.float(), dim=-1).cpu().numpy()
    if vectors.ndim != 2 or vectors.shape[1] != EMBEDDING_DIM:
        raise ValueError(f"expected {EMBEDDING_DIM}-D embeddings, got shape {vectors.shape}")
    norms = np.linalg.norm(vectors, axis=1)
    if not np.all(np.isfinite(vectors)) or np.any(np.abs(norms - 1.0) > UNIT_TOLERANCE):
        raise ValueError(f"embeddings are not finite unit vectors (norms {norms.min()}..{norms.max()})")
    return vectors
