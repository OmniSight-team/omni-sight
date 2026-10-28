"""InternVideo2's video encoder, from `internvideo2_clip_vision.py` (see __init__.py).

A ViT over 8 frames of 16 x 16 patches (patch 14 at 224) with one joint space-time
position embedding, then attention pooling to one 768-D vector per clip.
"""

import torch
import torch.nn.functional as F
from torch import nn


class CrossAttention(nn.Module):
    def __init__(self, dim, num_heads=8, qkv_bias=False, qk_scale=None, attn_head_dim=None, out_dim=None):
        super().__init__()
        if out_dim is None:
            out_dim = dim
        self.num_heads = num_heads
        head_dim = dim // num_heads
        if attn_head_dim is not None:
            head_dim = attn_head_dim
        all_head_dim = head_dim * self.num_heads
        self.scale = qk_scale or head_dim ** -0.5
        assert all_head_dim == dim

        self.q = nn.Linear(dim, all_head_dim, bias=False)
        self.k = nn.Linear(dim, all_head_dim, bias=False)
        self.v = nn.Linear(dim, all_head_dim, bias=False)

        if qkv_bias:
            self.q_bias = nn.Parameter(torch.zeros(all_head_dim))
            self.k_bias = nn.Parameter(torch.zeros(all_head_dim))
            self.v_bias = nn.Parameter(torch.zeros(all_head_dim))
        else:
            self.q_bias = None
            self.k_bias = None
            self.v_bias = None

        self.proj = nn.Linear(all_head_dim, out_dim)

    def forward(self, x, k=None, v=None):
        B, N, C = x.shape
        N_k = k.shape[1]
        N_v = v.shape[1]

        q = F.linear(input=x, weight=self.q.weight, bias=self.q_bias)
        q = q.reshape(B, N, 1, self.num_heads, -1).permute(2, 0, 3, 1, 4).squeeze(0)  # (B, N_head, N_q, dim)

        k = F.linear(input=k, weight=self.k.weight, bias=self.k_bias)
        k = k.reshape(B, N_k, 1, self.num_heads, -1).permute(2, 0, 3, 1, 4).squeeze(0)

        v = F.linear(input=v, weight=self.v.weight, bias=self.v_bias)
        v = v.reshape(B, N_v, 1, self.num_heads, -1).permute(2, 0, 3, 1, 4).squeeze(0)

        q = q * self.scale
        attn = q @ k.transpose(-2, -1)  # (B, N_head, N_q, N_k)
        attn = attn.softmax(dim=-1)

        x = (attn @ v).transpose(1, 2).reshape(B, N, -1)
        return self.proj(x)


class AttentionPoolingBlock(nn.Module):
    """`AttentiveBlock` with the mean token as the query: one vector out per clip."""

    def __init__(self, dim, num_heads, qkv_bias=False, qk_scale=None, norm_layer=nn.LayerNorm, attn_head_dim=None, out_dim=None):
        super().__init__()
        self.norm1_q = norm_layer(dim)
        self.norm1_k = norm_layer(dim)
        self.norm1_v = norm_layer(dim)
        self.cross_attn = CrossAttention(
            dim, num_heads=num_heads, qkv_bias=qkv_bias, qk_scale=qk_scale, attn_head_dim=attn_head_dim, out_dim=out_dim
        )

    def forward(self, x):
        x_q = self.norm1_q(x.mean(1, keepdim=True))
        x_k = self.norm1_k(x)
        x_v = self.norm1_v(x)
        return self.cross_attn(x_q, k=x_k, v=x_v).squeeze(1)


class RMSNorm(nn.Module):
    def __init__(self, hidden_size, eps=1e-6):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(hidden_size))
        self.variance_epsilon = eps

    def forward(self, hidden_states):
        input_dtype = hidden_states.dtype
        hidden_states = hidden_states.to(torch.float32)
        variance = hidden_states.pow(2).mean(-1, keepdim=True)
        hidden_states = hidden_states * torch.rsqrt(variance + self.variance_epsilon)
        return self.weight * hidden_states.to(input_dtype)


class LayerScale(nn.Module):
    def __init__(self, dim, init_values=1e-5):
        super().__init__()
        self.gamma = nn.Parameter(init_values * torch.ones(dim))

    def forward(self, x):
        return x * self.gamma


class Attention(nn.Module):
    def __init__(self, dim, num_heads=8, qkv_bias=False, norm_layer=nn.LayerNorm, qk_normalization=False):
        super().__init__()
        assert dim % num_heads == 0, "dim should be divisible by num_heads"
        self.num_heads = num_heads
        head_dim = dim // num_heads
        self.scale = head_dim ** -0.5

        self.qkv = nn.Linear(dim, dim * 3, bias=qkv_bias)
        self.proj = nn.Linear(dim, dim)

        self.qk_normalization = qk_normalization
        self.q_norm = norm_layer(dim) if qk_normalization else nn.Identity()
        self.k_norm = norm_layer(dim) if qk_normalization else nn.Identity()

    def forward(self, x):
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, C // self.num_heads).permute(2, 0, 3, 1, 4)
        q, k, v = qkv.unbind(0)

        if self.qk_normalization:
            B_, H_, N_, D_ = q.shape
            q = self.q_norm(q.transpose(1, 2).flatten(-2, -1)).view(B_, N_, H_, D_).transpose(1, 2)
            k = self.k_norm(k.transpose(1, 2).flatten(-2, -1)).view(B_, N_, H_, D_).transpose(1, 2)

        # softmax(q k^T * scale) v, as the original's naive path, through PyTorch's fused
        # kernel: the same result without holding the full attention matrix (B x 16 x 2049 x
        # 2049 floats, 8 GiB at batch 32), which ran a 22 GiB GPU out of memory (OMNI-706).
        x = F.scaled_dot_product_attention(q, k, v, scale=self.scale)
        x = x.transpose(1, 2).reshape(B, N, C)
        return self.proj(x)


class Mlp(nn.Module):
    def __init__(self, in_features, hidden_features=None, out_features=None, act_layer=nn.GELU):
        super().__init__()
        out_features = out_features or in_features
        hidden_features = hidden_features or in_features
        self.fc1 = nn.Linear(in_features, hidden_features)
        self.act = act_layer()
        self.fc2 = nn.Linear(hidden_features, out_features)

    def forward(self, x):
        return self.fc2(self.act(self.fc1(x)))


class Block(nn.Module):
    def __init__(self, dim, num_heads, mlp_ratio=4.0, qkv_bias=False, init_values=None, act_layer=nn.GELU,
                 norm_layer=nn.LayerNorm, qk_normalization=False):
        super().__init__()
        self.norm1 = norm_layer(dim)
        self.attn = Attention(dim, num_heads=num_heads, qkv_bias=qkv_bias, norm_layer=norm_layer, qk_normalization=qk_normalization)
        self.ls1 = LayerScale(dim, init_values=init_values) if init_values else nn.Identity()
        self.norm2 = norm_layer(dim)
        self.mlp = Mlp(in_features=dim, hidden_features=int(dim * mlp_ratio), act_layer=act_layer)
        self.ls2 = LayerScale(dim, init_values=init_values) if init_values else nn.Identity()

    def forward(self, x):
        x = x + self.ls1(self.attn(self.norm1(x)))
        x = x + self.ls2(self.mlp(self.norm2(x)))
        return x


class PatchEmbed(nn.Module):
    """3D image to patch embedding."""

    def __init__(self, img_size=224, patch_size=16, in_chans=3, embed_dim=768, num_frames=8, tubelet_size=1):
        super().__init__()
        self.grid_size = (num_frames // tubelet_size, img_size // patch_size, img_size // patch_size)  # (T, H, W)
        self.num_patches = self.grid_size[0] * self.grid_size[1] * self.grid_size[2]
        self.proj = nn.Conv3d(
            in_channels=in_chans, out_channels=embed_dim,
            kernel_size=(tubelet_size, patch_size, patch_size),
            stride=(tubelet_size, patch_size, patch_size),
        )

    def forward(self, x):
        x = self.proj(x)
        return x.flatten(3).permute(0, 2, 3, 1)  # B x C x T x HW => B x T x HW x C


class InternVideo2(nn.Module):
    def __init__(
        self,
        in_chans: int = 3,
        patch_size: int = 14,
        img_size: int = 224,
        qkv_bias: bool = False,
        embed_dim: int = 1408,
        num_heads: int = 16,
        mlp_ratio: float = 48 / 11,
        init_values: float = 1e-5,
        qk_normalization: bool = True,
        depth: int = 40,
        attn_pool_num_heads: int = 16,
        clip_embed_dim: int = 768,
        num_frames: int = 8,
        tubelet_size: int = 1,
    ):
        super().__init__()
        self.embed_dim = embed_dim
        self.patch_embed = PatchEmbed(img_size, patch_size, in_chans, embed_dim, num_frames=num_frames, tubelet_size=tubelet_size)
        self.cls_token = nn.Parameter(torch.zeros(1, 1, embed_dim))
        # Joint space-time position embedding (the config's sep_pos_embed is false).
        self.pos_embed = nn.Parameter(torch.zeros(1, self.patch_embed.num_patches + 1, embed_dim))

        norm_layer = lambda dim: RMSNorm(dim, eps=1e-6)  # noqa: E731
        self.blocks = nn.ModuleList([
            Block(embed_dim, num_heads, mlp_ratio, qkv_bias=qkv_bias, norm_layer=norm_layer,
                  init_values=init_values, qk_normalization=qk_normalization)
            for _ in range(depth)
        ])
        self.clip_projector = AttentionPoolingBlock(
            dim=embed_dim, num_heads=attn_pool_num_heads, qkv_bias=True, qk_scale=None,
            norm_layer=lambda dim: nn.LayerNorm(dim, eps=1e-5), out_dim=clip_embed_dim,
        )

    def forward(self, x):
        """x: B x C x T x H x W -> B x clip_embed_dim."""
        x = self.patch_embed(x.type(self.patch_embed.proj.weight.dtype))
        B, T, L, C = x.shape  # T: temporal; L: spatial
        x = x.view([B, T * L, C])
        x = torch.cat((self.cls_token.expand(B, -1, -1), x), dim=1)
        x = x + self.pos_embed
        for blk in self.blocks:
            x = blk(x)
        return self.clip_projector(x)
