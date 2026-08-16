"""交互动画核心 —— 输入→帧映射 / 帧预算 / 资源形式决策 / 图集预算(3O 内化 Round 3i)。

来源: oil-oil/oil-motion —— "把 AI 生成的连续动作接入网页交互"(滚动/鼠标/拖动/
触摸/设备方向)。这是 hevi 全新的能力域:此前全部产出是"视频文件",这里是
"可交互的网页动画资源"(图集/可 seek MP4 + 交互代码)。

本模块为 hevi 暂驻(待上游 `oskill.interactive_motion`):全部确定性数学可测 ——
  1. interactive_frame_budget:按控制方式/驱动范围估算独立姿态数
     (滚动 24 帧/屏、拖拽 48-72、环形 72-120)
  2. map_input_to_frame:一维 progress / 环形角度 → 目标帧
  3. ring_shortest_delta:环形最短距离(快速反向不闪烁的阻尼基础)
  4. decide_resource_form:资源形式决策表(透明/帧数/尺寸/控制方式 → 形式)
  5. atlas_budget:单元尺寸 vs 纹理上限 vs 解码内存(RGBA = W×H×4)
  6. build_atlas_manifest:图集清单(帧数/列行/单元/静止帧/参数映射)
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: 控制方式 → 每单位驱动范围的采样密度(帧)。
FRAMES_PER_SCROLL_PAGE = 24
FRAMES_PER_DRAG_CHECK = 48  # 短距离拖拽起点
FRAMES_PER_RING = 72  # 环形方向起点
MAX_TEXTURE = 4096


@dataclass
class AtlasManifest:
    """图集清单(运行时定位帧的唯一真相)。"""

    frames: int
    cols: int
    rows: int
    cell_width: int
    cell_height: int
    anchor: tuple[float, float]  # 主体锚点(单元内归一化 0-1)
    mapping: str  # "scroll" | "ring" | "drag" | "state"
    static_frames: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames": self.frames,
            "cols": self.cols,
            "rows": self.rows,
            "cell_width": self.cell_width,
            "cell_height": self.cell_height,
            "anchor": list(self.anchor),
            "mapping": self.mapping,
            "static_frames": self.static_frames,
        }


def interactive_frame_budget(
    control_kind: str, *, scroll_pages: float = 1.0, span_ratio: float = 1.0
) -> int:
    """按控制方式估算独立姿态数(帧数 ≠ FPS,是可访问姿态数)。

    - scroll:每视口高度 20-28 帧,基线 24 帧/屏。
    - drag/pointer:短距离 48-72,起步 48。
    - ring:环形方向 72-120,起步 72。
    - state:少量 hover/click 状态,每状态 ~8 帧。
    """
    kind = control_kind.strip().lower()
    if kind in ("scroll", "vertical"):
        return max(int(scroll_pages * FRAMES_PER_SCROLL_PAGE), 1)
    if kind in ("drag", "pointer", "mouse"):
        return max(int(FRAMES_PER_DRAG_CHECK * span_ratio), 1)
    if kind in ("ring", "orientation", "device-orientation"):
        return max(int(FRAMES_PER_RING * span_ratio), 1)
    if kind in ("state", "hover", "click"):
        return 8
    raise ValueError(f"unknown control_kind {control_kind!r}")


def map_input_to_frame(
    input_value: float, frame_count: int, *, mapping: str = "scroll"
) -> int:
    """输入 → 目标帧(确定性)。

    - scroll/drag(一维):progress 0-1 → 帧(0..count-1),clamp。
    - ring(环形角度,弧度):mod(angle, 2π)/2π → 帧,环形连续。
    """
    if frame_count <= 1:
        return 0
    if mapping in ("scroll", "drag", "pointer", "vertical", "horizontal"):
        progress = max(0.0, min(1.0, input_value))
        return min(frame_count - 1, int(progress * (frame_count - 1)))
    if mapping in ("ring", "orientation"):
        normalized = (input_value % (2 * math.pi)) / (2 * math.pi)
        return min(frame_count - 1, int(normalized * frame_count))
    raise ValueError(f"unknown mapping {mapping!r}")


def ring_shortest_delta(target: int, current: int, frame_count: int) -> int:
    """环形最短距离(带符号):快速反向不闪烁的阻尼基础。

    delta ∈ (-count/2, count/2];current 沿最短方向追 target。
    """
    if frame_count <= 0:
        return 0
    raw = (target - current) % frame_count
    if raw > frame_count / 2:
        raw -= frame_count
    return round(raw)


def decide_resource_form(
    *,
    transparency: bool,
    frames: int,
    display_size: tuple[int, int],
    control_kind: str,
    target_browser: str = "modern",
) -> str:
    """资源形式决策表(runtime.md):

    - 透明 + 帧数 < 300 + 任意跳转 → webp_atlas(一次请求,随机访问稳定)
    - 一维高分辨率 + 频繁 seek → keyframe_mp4
    - 长顺序滚动 → seekable_video(压缩率最高)
    - 高频随机 + 浏览器目标明确(WebCodecs) → webcodecs
    - 少量 hover/click → short_clips
    - 图集超纹理上限 → sliced_atlas(由调用方结合 atlas_budget 判断)
    """
    kind = control_kind.strip().lower()
    if kind in ("state", "hover", "click"):
        return "short_clips"
    if target_browser.lower() == "webcodecs":
        return "webcodecs"
    if kind in ("ring", "orientation") or transparency:
        # 环形/透明角色 → 图集系(需随机访问稳定)
        w, h = display_size
        if w > 0 and h > 0 and frames > 0 and w * h * frames > MAX_TEXTURE * MAX_TEXTURE:
            return "sliced_atlas"
        return "webp_atlas"
    if frames > 300:
        return "seekable_video"
    return "keyframe_mp4"


@dataclass
class AtlasBudget:
    """图集预算结果。"""

    cell_width: int
    cell_height: int
    cols: int
    rows: int
    texture_width: int
    texture_height: int
    decode_memory_mb: float
    within_texture_limit: bool
    notes: list[str] = field(default_factory=list)


def atlas_budget(
    *,
    display_size: tuple[int, int],
    dpr: float,
    frames: int,
    max_texture: int = MAX_TEXTURE,
) -> AtlasBudget:
    """图集预算:单元 = 显示尺寸 × DPR(禁止低分辨率放大),列行按帧数排布,
    检查纹理上限 + 解码内存(RGBA = 宽×高×4)。超限 → within_texture_limit=False。
    """
    dw, dh = display_size
    cell_w = max(int(dw * dpr), 1)
    cell_h = max(int(dh * dpr), 1)
    cols = max(math.ceil(math.sqrt(frames * cell_w / max(cell_h, 1))), 1)
    rows = max(math.ceil(frames / cols), 1)
    tex_w = cols * cell_w
    tex_h = rows * cell_h
    memory_mb = tex_w * tex_h * 4 / (1024 * 1024)
    notes: list[str] = []
    if tex_w > max_texture or tex_h > max_texture:
        notes.append(
            f"图集 {tex_w}x{tex_h} 超纹理上限 {max_texture}: 优先分片或视频解码,"
            "不要缩小单元强行装入单张"
        )
    return AtlasBudget(
        cell_width=cell_w,
        cell_height=cell_h,
        cols=cols,
        rows=rows,
        texture_width=tex_w,
        texture_height=tex_h,
        decode_memory_mb=round(memory_mb, 2),
        within_texture_limit=tex_w <= max_texture and tex_h <= max_texture,
        notes=notes,
    )


def build_atlas_manifest(
    *,
    frames: int,
    cols: int,
    rows: int,
    cell_width: int,
    cell_height: int,
    anchor: tuple[float, float] = (0.5, 0.5),
    mapping: str = "scroll",
    static_frames: list[int] | None = None,
) -> AtlasManifest:
    """图集清单(JSON 可序列化)。"""
    return AtlasManifest(
        frames=frames,
        cols=cols,
        rows=rows,
        cell_width=cell_width,
        cell_height=cell_height,
        anchor=anchor,
        mapping=mapping,
        static_frames=list(static_frames or []),
    )


def atlas_css_background(manifest: AtlasManifest) -> str:
    """CSS:background-size = columns×100% rows×100%(切帧只改 background-position)。"""
    return f"{manifest.cols * 100}% {manifest.rows * 100}%"


def save_atlas_manifest(manifest: AtlasManifest, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return p
