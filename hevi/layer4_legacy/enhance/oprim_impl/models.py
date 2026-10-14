"""Local model registry + pure-torch architectures for the enhancement ops.

Everything here is CPU-only and offline after the one-time weight fetch.  The
architectures are re-implemented directly against the published state-dict
layouts so that no ``basicsr`` build is required for Real-ESRGAN (GFPGAN reuses
the upstream ``gfpgan`` package, which *is* installed in ``.venv-om``).

Weight sources are domestic mirrors (``ghfast.top``) as required by the task.
"""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
import torch.nn.functional as F

from hevi.layer4_legacy.enhance.oprim_impl._bootstrap import ensure_importable

logger = logging.getLogger(__name__)

#: Weight catalogue: file name -> (mirror URL, sha-less size hint).
_GH = "https://ghfast.top/https://github.com"
WEIGHTS: dict[str, str] = {
    "RealESRGAN_x2plus.pth": f"{_GH}/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
    "RealESRGAN_x4plus.pth": f"{_GH}/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
    "GFPGANv1.4.pth": f"{_GH}/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth",
    "detection_Resnet50_Final.pth": f"{_GH}/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth",
    "parsing_parsenet.pth": f"{_GH}/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth",
}

_REPO = Path(__file__).resolve().parents[4]


class ModelUnavailable(RuntimeError):
    """A required local weight or dependency is missing (fail-closed)."""


def models_dir() -> Path:
    env = os.environ.get("HEVI_ENHANCE_MODELS")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "hevi" / "enhance"


def weight_path(name: str, *, download: bool = False) -> Path:
    """Resolve a weight file; optionally fetch it from the domestic mirror."""
    dest = models_dir() / name
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    if not download:
        raise ModelUnavailable(
            f"missing weight {name} at {dest}; run scripts/om_quality_install_enhance.sh"
        )
    url = WEIGHTS.get(name)
    if not url:
        raise ModelUnavailable(f"no download URL registered for {name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("downloading %s -> %s", url, dest)
    # Never route weight downloads through the small-bandwidth SSH proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    tmp = dest.with_suffix(dest.suffix + ".part")
    with opener.open(url, timeout=600) as resp, tmp.open("wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    tmp.replace(dest)
    return dest


def load_torch(path: Path, key: str = "params_ema") -> dict[str, Any]:
    """Load a checkpoint dict, tolerating both ``params`` and ``params_ema``."""
    sd = torch.load(str(path), map_location="cpu", weights_only=True)
    if isinstance(sd, dict) and key in sd:
        return sd[key]
    if isinstance(sd, dict) and "params" in sd:
        return sd["params"]
    return sd


# ---------------------------------------------------------------------------
# Real-ESRGAN RRDBNet (BSD-3-Clause, xinntao/Real-ESRGAN) — re-implemented.
# ---------------------------------------------------------------------------


def pixel_unshuffle(x: torch.Tensor, scale: int) -> torch.Tensor:
    """Inverse of pixel-shuffle: (B,C,H,W) -> (B,C*scale^2,H/scale,W/scale)."""
    b, c, hh, hw = x.size()
    out_ch = c * scale**2
    out_h = hh // scale
    out_w = hw // scale
    x_view = x.view(b, c, out_h, scale, out_w, scale)
    return x_view.permute(0, 1, 3, 5, 2, 4).reshape(b, out_ch, out_h, out_w)


class ResidualDenseBlock(nn.Module):
    def __init__(self, num_feat: int = 64, num_grow_ch: int = 32) -> None:
        super().__init__()
        self.conv1 = nn.Conv2d(num_feat, num_grow_ch, 3, 1, 1)
        self.conv2 = nn.Conv2d(num_feat + num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv3 = nn.Conv2d(num_feat + 2 * num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv4 = nn.Conv2d(num_feat + 3 * num_grow_ch, num_grow_ch, 3, 1, 1)
        self.conv5 = nn.Conv2d(num_feat + 4 * num_grow_ch, num_feat, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x1 = self.lrelu(self.conv1(x))
        x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
        x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
        x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
        x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
        return x5 * 0.2 + x


class RRDB(nn.Module):
    def __init__(self, num_feat: int, num_grow_ch: int = 32) -> None:
        super().__init__()
        self.rdb1 = ResidualDenseBlock(num_feat, num_grow_ch)
        self.rdb2 = ResidualDenseBlock(num_feat, num_grow_ch)
        self.rdb3 = ResidualDenseBlock(num_feat, num_grow_ch)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.rdb1(x)
        out = self.rdb2(out)
        out = self.rdb3(out)
        return out * 0.2 + x


class RRDBNet(nn.Module):
    """Real-ESRGAN generator.

    Matches ``basicsr.archs.rrdbnet_arch.RRDBNet``: for ``scale=2`` the input is
    pixel-unshuffled (``num_in_ch * 4``) and the two upsample stages then yield a
    net 2x.  There is deliberately **no** global residual add (the official
    forward returns ``conv_last(...)`` directly).
    """

    def __init__(
        self,
        num_in_ch: int = 3,
        num_out_ch: int = 3,
        num_feat: int = 64,
        num_block: int = 23,
        num_grow_ch: int = 32,
        scale: int = 4,
    ) -> None:
        super().__init__()
        self.scale = scale
        if scale == 2:
            num_in_ch = num_in_ch * 4
        elif scale == 1:
            num_in_ch = num_in_ch * 16
        self.conv_first = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
        self.body = nn.Sequential(*[RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
        self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.scale == 2:
            feat = pixel_unshuffle(x, 2)
        elif self.scale == 1:
            feat = pixel_unshuffle(x, 4)
        else:
            feat = x
        feat = self.conv_first(feat)
        feat = feat + self.conv_body(self.body(feat))
        feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
        feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
        return self.conv_last(self.lrelu(self.conv_hr(feat)))


def load_realesrgan(scale: int) -> RRDBNet:
    """Build + load the Real-ESRGAN generator for ``scale`` in {2,4}."""
    if scale == 2:
        name = "RealESRGAN_x2plus.pth"
    elif scale == 4:
        name = "RealESRGAN_x4plus.pth"
    else:
        raise ModelUnavailable(f"Real-ESRGAN scale {scale} unsupported (use 2 or 4)")
    path = weight_path(name, download=True)
    net = RRDBNet(scale=scale)
    state = load_torch(path)
    missing, unexpected = net.load_state_dict(state, strict=False)
    if missing or unexpected:
        raise ModelUnavailable(
            f"Real-ESRGAN state dict mismatch for {name}: "
            f"missing={list(missing)[:4]} unexpected={list(unexpected)[:4]}"
        )
    net.eval()
    return net


# ---------------------------------------------------------------------------
# GFPGAN (TencentARC/GFPGAN) — upstream package, research weights (default off).
# ---------------------------------------------------------------------------


def require_gfpgan() -> Any:
    if not ensure_importable("gfpgan"):
        raise ModelUnavailable(
            "gfpgan not importable; run scripts/om_quality_install_enhance.sh "
            "(installs into the isolated .venv-om)"
        )
    from gfpgan.archs.gfpganv1_clean_arch import GFPGANv1Clean

    return GFPGANv1Clean


def load_gfpgan() -> Any:
    """Build + load the GFPGANv1.4 clean generator on CPU."""
    GFPGANv1Clean = require_gfpgan()
    path = weight_path("GFPGANv1.4.pth", download=True)
    net = GFPGANv1Clean(
        out_size=512,
        num_style_feat=512,
        channel_multiplier=2,
        decoder_load_path=None,
        fix_decoder=False,
        num_mlp=8,
        input_is_latent=True,
        different_w=True,
        narrow=1,
        sft_half=True,
    )
    state = load_torch(path)
    net.load_state_dict(state, strict=True)
    net.eval()
    return net


__all__ = [
    "WEIGHTS",
    "ModelUnavailable",
    "RRDB",
    "RRDBNet",
    "ResidualDenseBlock",
    "load_gfpgan",
    "load_realesrgan",
    "models_dir",
    "pixel_unshuffle",
    "require_gfpgan",
    "weight_path",
]
