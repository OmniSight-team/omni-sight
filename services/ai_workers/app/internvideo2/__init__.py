"""InternVideo2-CLIP-S's model code, copied into the repo (OMNI-706, D-33).

Source: Hugging Face `OpenGVLab/InternVideo2_CLIP_S` at revision
`1f9fca1389fd883defc652634d95a21121c85a8c`:

- `vision.py` from `internvideo2_clip_vision.py` (InternVideo2, OpenGVLab, Apache-2.0)
- `text.py` from `mobile_clip.py` and `mobile_clip_transformer.py` (MobileCLIP's text
  encoder, Copyright (C) 2024 Apple Inc., Apple's MobileCLIP licence; borrowed there from
  apple/ml-cvnets)

The checkpoint ships this code beside its weights; running it from there means executing
files downloaded from the internet, so it is kept here instead, read once and fixed with
the pinned weights. Only the weights (`model.safetensors`) are downloaded.

What was changed, and only this: inference only. Removed the flash-attention and fused
paths (the checkpoint's config turns them off, and `flash_attn` cannot be installed
without CUDA), training-only parts (drop path, gradient checkpointing, weight
initialisation: every weight is loaded from the checkpoint), and the image-only path.
Module and parameter names are unchanged, so the checkpoint loads with every key matched.
One computation is written differently: the video encoder's self-attention uses PyTorch's
`scaled_dot_product_attention` instead of building the attention matrix by hand, the same
result to float rounding (max difference 5e-8 on a 2049-token clip) without the 8 GiB
matrix that ran a 22 GiB GPU out of memory at batch 32.
"""
