"""跨环境 parity 契约 —— 确定性渲染一致性 harness(3O 内化 Round 3,补"parity 契约"缺口)。

HyperFrames 有 htmlParityContract(跨环境同输出);Remotion 本身确定性,但 hevi-remotion
无显式 harness。这里补:
  1. 确定性前置校验:同一 composition + 同一 props → 输出应一致(配置级,零渲染成本)。
  2. 帧级 parity:渲染两次(如本地 vs 云端/两次本地)→ 抽帧哈希对比(可选,需真渲染)。

纯逻辑部分(可测):parity 判定(帧哈希列表比较)、渲染配置规范化(排序去抖)。
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ParityConfig:
    """parity 检查配置。"""

    composition_id: str
    props: dict[str, Any] = field(default_factory=dict)
    width: int = 1080
    height: int = 1440
    fps: int = 30


def normalize_render_config(config: ParityConfig) -> dict[str, Any]:
    """渲染配置规范化(确定性指纹):排序 props、固定字段集合。"""
    return {
        "composition_id": config.composition_id,
        "width": config.width,
        "height": config.height,
        "fps": config.fps,
        "props": json.dumps(config.props, sort_keys=True, ensure_ascii=False),
    }


def render_config_fingerprint(config: ParityConfig) -> str:
    """配置指纹:同配置必同指纹(零渲染成本的确定性基线)。"""
    raw = json.dumps(normalize_render_config(config), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def frame_hashes(video_path: Path, *, sample_every: int = 30) -> list[str]:
    """抽帧哈希列表(parity 帧级对比;失败抛 ParityError)。"""
    try:
        import av
    except ImportError as e:  # pragma: no cover - env guard
        raise ParityError(f"av 未安装: {e}") from e
    try:
        with av.open(str(video_path)) as container:
            hashes: list[str] = []
            for i, frame in enumerate(container.decode(video=0)):
                if i % sample_every != 0:
                    continue
                img = frame.to_image()  # type: ignore[no-untyped-call]
                thumb = img.convert("L").resize((16, 16)).tobytes()
                hashes.append(hashlib.sha256(thumb).hexdigest()[:12])
            return hashes
    except Exception as e:
        raise ParityError(f"frame extraction failed for {video_path}: {e}") from e


class ParityError(Exception):
    """parity 检查失败。"""


def compare_videos(a: Path, b: Path, *, sample_every: int = 30) -> dict[str, Any]:
    """两次渲染帧级对比:哈希序列相等判 parity 通过。"""
    ha = frame_hashes(a, sample_every=sample_every)
    hb = frame_hashes(b, sample_every=sample_every)
    if len(ha) != len(hb):
        return {"passed": False, "reason": f"frame count mismatch {len(ha)} vs {len(hb)}"}
    mismatches = [i for i, (x, y) in enumerate(zip(ha, hb, strict=False)) if x != y]
    return {
        "passed": not mismatches,
        "frames_compared": len(ha),
        "mismatched_frames": mismatches[:20],
        "mismatch_count": len(mismatches),
    }
