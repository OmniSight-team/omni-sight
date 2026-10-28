#
# Copyright (C) 2024 Apple Inc. All Rights Reserved.
# MobileCLIP's text encoder, from `mobile_clip.py` and `mobile_clip_transformer.py` of
# OpenGVLab/InternVideo2_CLIP_S (see __init__.py), which borrowed it from apple/ml-cvnets:
# cvnets/layers/multi_head_attention.py and cvnets/text_encoders/transformer.py.
#
"""MobileCLIP's text encoder: a causal pre-norm transformer over open_clip's tokens; the end
token's features, projected to 512.

The `nn.Sequential` layouts are kept, empty slots included, because the checkpoint's
parameter names count their positions (`pre_norm_ffn.4.weight`)."""

import math

import torch
from torch import Tensor, nn
from torch.nn import functional as F


class LayerNormFP32(nn.LayerNorm):
    """Layer normalisation computed in float32."""

    def forward(self, x: Tensor) -> Tensor:
        inp_dtype = x.dtype
        return super().forward(x.to(torch.float32)).to(inp_dtype)


def get_normalization_layer(norm_type, num_features):
    if norm_type == "layer_norm":
        return nn.LayerNorm(num_features)
    if norm_type == "layer_norm_fp32":
        return LayerNormFP32(num_features)
    raise NotImplementedError(f"Option: {norm_type} not supported.")


class LearnablePositionalEmbedding(nn.Module):
    def __init__(self, num_embeddings: int, embedding_dim: int, interpolation_mode: str = "bilinear"):
        super().__init__()
        self.pos_embed = nn.Parameter(torch.empty(1, 1, num_embeddings, embedding_dim))
        self.embedding_dim = embedding_dim
        self.num_embeddings = num_embeddings
        self.interpolation_mode = interpolation_mode

    def forward(self, seq_len: int) -> Tensor:
        pos_embed = self.pos_embed
        if seq_len != self.num_embeddings:
            pos_embed = F.interpolate(pos_embed, size=(seq_len, self.embedding_dim), mode=self.interpolation_mode)
        return pos_embed.reshape(1, seq_len, self.embedding_dim)


class PositionalEmbedding(nn.Module):
    def __init__(self, num_embeddings: int, embedding_dim: int):
        super().__init__()
        self.pos_embed = LearnablePositionalEmbedding(num_embeddings=num_embeddings, embedding_dim=embedding_dim)

    def forward(self, seq_len: int) -> Tensor:
        return self.pos_embed(seq_len)


class MultiHeadAttention(nn.Module):
    """Multi-head self-attention (the cross-attention path is not used by the text encoder)."""

    def __init__(self, embed_dim: int, num_heads: int, bias: bool = True):
        super().__init__()
        self.qkv_proj = nn.Linear(in_features=embed_dim, out_features=3 * embed_dim, bias=bias)
        self.out_proj = nn.Linear(in_features=embed_dim, out_features=embed_dim, bias=bias)
        self.head_dim = embed_dim // num_heads
        self.scaling = self.head_dim ** -0.5
        self.num_heads = num_heads
        self.embed_dim = embed_dim

    def forward(self, x_q: Tensor, attn_mask: Tensor | None = None) -> Tensor:
        b_sz, S_len, _ = x_q.shape
        # [N, S, C] --> [N, S, 3, h, c] --> [N, h, 3, S, c]
        qkv = self.qkv_proj(x_q).reshape(b_sz, S_len, 3, self.num_heads, -1)
        qkv = qkv.transpose(1, 3).contiguous()
        query, key, value = qkv[:, :, 0], qkv[:, :, 1], qkv[:, :, 2]

        query = query * self.scaling
        attn = torch.matmul(query, key.transpose(-1, -2))  # [N, h, S, S]
        if attn_mask is not None:
            attn = attn + attn_mask.unsqueeze(1)  # [N, S, S] --> [N, 1, S, S]

        attn = torch.softmax(attn.float(), dim=-1).to(attn.dtype)
        out = torch.matmul(attn, value)  # [N, h, S, c]
        out = out.transpose(1, 2).reshape(b_sz, S_len, -1)
        return self.out_proj(out)


class TransformerEncoder(nn.Module):
    """Pre-norm transformer layer."""

    def __init__(self, embed_dim: int, ffn_latent_dim: int, num_heads: int = 8, transformer_norm_layer: str = "layer_norm"):
        super().__init__()
        self.pre_norm_mha = nn.Sequential(
            get_normalization_layer(norm_type=transformer_norm_layer, num_features=embed_dim),
            MultiHeadAttention(embed_dim, num_heads, bias=True),
            nn.Identity(),  # dropout
        )
        self.pre_norm_ffn = nn.Sequential(
            get_normalization_layer(norm_type=transformer_norm_layer, num_features=embed_dim),
            nn.Linear(in_features=embed_dim, out_features=ffn_latent_dim, bias=True),
            nn.GELU(),
            nn.Identity(),  # dropout
            nn.Linear(in_features=ffn_latent_dim, out_features=embed_dim, bias=True),
            nn.Identity(),  # dropout
        )

    def forward(self, x: Tensor, attn_mask: Tensor | None = None) -> Tensor:
        res = x
        x = self.pre_norm_mha[0](x)
        x = self.pre_norm_mha[1](x, attn_mask=attn_mask)
        x = x + res
        return x + self.pre_norm_ffn(x)


class TextTransformer(nn.Module):
    def __init__(self, cfg: dict, projection_dim: int):
        super().__init__()
        model_dim = cfg["dim"]
        n_layers = cfg["n_transformer_layers"]
        if cfg["model_name"] != "base":
            raise ValueError(f"Unrecognized text encoder variant {cfg['model_name']}")
        self.embedding_layer = nn.Embedding(embedding_dim=model_dim, num_embeddings=cfg["vocab_size"])
        self.positional_embedding = PositionalEmbedding(num_embeddings=cfg["context_length"], embedding_dim=model_dim)
        ffn_dim = int(math.ceil(model_dim * cfg["ffn_multiplier_per_layer"] / 16.0) * 16.0)
        self.transformer = nn.ModuleList([
            TransformerEncoder(
                embed_dim=model_dim,
                num_heads=cfg["n_heads_per_layer"],
                ffn_latent_dim=ffn_dim,
                transformer_norm_layer=cfg["norm_layer"],
            )
            for _ in range(n_layers)
        ])
        self.final_layer_norm = get_normalization_layer(num_features=model_dim, norm_type=cfg["norm_layer"])
        self.projection_layer = nn.Parameter(torch.empty(model_dim, projection_dim))
        self.causal_masking = cfg["causal_masking"]

    def forward(self, text_tokens: Tensor) -> Tensor:
        """[batch, context_length] token ids -> [batch, projection_dim]."""
        token_emb = self.embedding_layer(text_tokens)
        seq_len = token_emb.shape[1]
        token_emb = token_emb + self.positional_embedding(seq_len).to(token_emb.dtype)

        attn_mask = None
        if self.causal_masking:
            mask = torch.full((seq_len, seq_len), float("-inf")).triu_(1)
            attn_mask = mask.unsqueeze(0).expand(text_tokens.shape[0], -1, -1).to(device=token_emb.device, dtype=token_emb.dtype)

        for layer in self.transformer:
            token_emb = layer(token_emb, attn_mask=attn_mask)
        token_emb = self.final_layer_norm(token_emb)

        # The end-of-text token's features (it has the highest id in each sequence).
        token_emb = token_emb[torch.arange(text_tokens.shape[0]), text_tokens.argmax(dim=-1)]
        return token_emb @ self.projection_layer
