"""annotation_revision —— 帧标注 → 确定性 ShotSpecPatch（RENOISE_EVAL §3.5 / K2 交付物 2）。

把人在画面上画的标注（pin/arrow/freehand/rect/ellipse/text）+ 时间码
（``sourceTimeMs``）→ 确定性 ``ShotSpecPatch{shot_index, from_revision, changes,
advisory, source_refs}``，严格按 §3.5 映射表。

设计要点（对齐 RENOISE canvas 方法学，不复制其原文）：
  - 确定性：同一输入两次产生的 patch 字节一致（用 ``sorted``/固定顺序）。
  - 干净原图与标注图分离：``render_annotated`` 把标注烧到同尺寸 PNG（作为
    annotationGuide 用），``authoritative_source`` 原图不受影响。
  - 仅显式映射的字段进 ``changes``；未知标注只进 ``advisory``，不静默改。
  - ≥2 个时间码锚点 → ``requiresTemporalRangeClarification=true``，不自动出区间 patch。
  - 时间码落在镜外 → 拒绝（抛 ``AnnotationRejected``）。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .fonts import cjk_font

# §3.5 明确映射（标注类型 → ShotSpec 字段方向）。
_PIN_MAPS_TO = "camera"
_ARROW_MAPS_TO = "camera"
_FREEHAND_MAPS_TO = "effect"
_RECT_ELLIPSE_MAPS_TO = "effect"
_TEXT_MAPS_TO = "subtitle_style"


class AnnotationError(Exception):
    """标注输入非法。"""


class AnnotationRejected(Exception):
    """标注被拒绝（如时间码落在镜外）。"""


class AnnotationTemporalClarification(Exception):
    """≥2 个时间码锚点，需区间澄清，不自动出 patch。"""

    def __init__(self, anchor_count: int) -> None:
        self.anchor_count = anchor_count
        super().__init__(
            f"{anchor_count} 个时间码锚点，语义未确认前不自动生成区间 patch"
        )


@dataclass
class AnnotationMark:
    """一条标记图形（归一化坐标 0–1，相对目标素材）。"""

    kind: str
    nx: float
    ny: float
    nw: float = 0.0
    nh: float = 0.0
    direction: str | None = None
    note: str | None = None
    color: tuple[int, int, int] = (255, 80, 80)

    @property
    def is_known(self) -> bool:
        return self.kind in {"pin", "arrow", "freehand", "rect", "ellipse", "text"}


@dataclass
class AnnotationInput:
    """一次标注修订请求的入参。"""

    shot_index: int
    from_revision: int = 0
    marks: list[AnnotationMark] = field(default_factory=list)
    source_time_ms: list[float] = field(default_factory=list)
    authoritative_source: str | None = None
    note: str | None = None


@dataclass
class ShotSpecPatch:
    """确定性 ShotSpec 修订补丁。"""

    shot_index: int
    from_revision: int
    changes: dict[str, Any] = field(default_factory=dict)
    advisory: list[str] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    requires_temporal_range_clarification: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_index": self.shot_index,
            "from_revision": self.from_revision,
            "changes": dict(sorted(self.changes.items())),
            "advisory": sorted(self.advisory),
            "source_refs": self.source_refs,
            "requires_temporal_range_clarification": self.requires_temporal_range_clarification,
        }

    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()


_ARROW_CAMERA = {
    "right": "pan_right",
    "left": "pan_left",
    "up": "tilt_up",
    "down": "tilt_down",
}


def _resolve_shot_time_window(manifest: Any, shot_index: int) -> tuple[float, float, bool]:
    """返回 (start_ms, end_ms, is_last) 该镜在成片时间轴上的区间及是否为最后一镜。"""
    shots = manifest.shots()
    acc = 0.0
    for idx, s in enumerate(shots):
        start = acc * 1000.0
        end = (acc + s.duration) * 1000.0
        is_last = (idx == len(shots) - 1)
        if s.shot_index == shot_index:
            return start, end, is_last
        acc += s.duration
    raise AnnotationError(f"manifest 无镜 S{shot_index}")


def build_patch(manifest: Any, annotation: AnnotationInput) -> ShotSpecPatch:
    """从标注构建 ShotSpecPatch。确定性，严格按 §3.5 映射。

    规则：
      - 校验输入合法性（坐标 [0,1]，有限数值，from_revision >= 0 等）。
      - ≥2 个时间码锚点 → 抛 AnnotationTemporalClarification（不出 patch）。
      - 时间码落在镜外（半开区间 [start, end)，最后一镜含 end） → 抛 AnnotationRejected。
      - 箭头方向规范化及冲突过滤、effect 冲突降级 advisory。
    """
    import math
    from .manifest_adapter import ManifestProtocol

    if not isinstance(manifest, ManifestProtocol):
        raise AnnotationError("manifest must be loaded via manifest_adapter")

    if not isinstance(annotation.from_revision, int) or annotation.from_revision < 0:
        raise AnnotationError(f"from_revision 必须是非负整数，got {annotation.from_revision}")
    for t in annotation.source_time_ms:
        if not (isinstance(t, (int, float)) and math.isfinite(t)):
            raise AnnotationError(f"时间码必须是有限数值，got {t}")
    for m in annotation.marks:
        if not (isinstance(m.nx, (int, float)) and math.isfinite(m.nx) and 0 <= m.nx <= 1 and
                isinstance(m.ny, (int, float)) and math.isfinite(m.ny) and 0 <= m.ny <= 1 and
                isinstance(m.nw, (int, float)) and math.isfinite(m.nw) and 0 <= m.nw <= 1 and
                isinstance(m.nh, (int, float)) and math.isfinite(m.nh) and 0 <= m.nh <= 1):
            raise AnnotationError(f"标注坐标/宽高越界或非法: nx={m.nx}, ny={m.ny}, nw={m.nw}, nh={m.nh}")

    start_ms, end_ms, is_last = _resolve_shot_time_window(manifest, annotation.shot_index)

    anchors = annotation.source_time_ms
    if len(anchors) >= 2:
        raise AnnotationTemporalClarification(len(anchors))

    if anchors:
        t = anchors[0]
        in_range = (start_ms <= t <= end_ms) if is_last else (start_ms <= t < end_ms)
        if not in_range:
            raise AnnotationRejected(
                f"时间码 {t:.1f}ms 落在 S{annotation.shot_index} 镜外 "
                f"[{start_ms:.1f},{end_ms:.1f})ms"
            )

    patch = ShotSpecPatch(
        shot_index=annotation.shot_index,
        from_revision=annotation.from_revision,
    )

    camera_actions: list[str] = []
    effect_actions: list[str] = []
    subtitle_advices: list[str] = []

    for m in annotation.marks:
        if not m.is_known:
            patch.advisory.append(f"未知标注类型 '{m.kind}'，未自动修改")
            continue
        if m.kind == "pin":
            camera_actions.append("push_in")
        elif m.kind == "arrow":
            dir_str = m.direction if m.direction in _ARROW_CAMERA else None
            if dir_str in _ARROW_CAMERA:
                camera_actions.append(_ARROW_CAMERA[dir_str])
            else:
                patch.advisory.append(f"arrow 方向非法或大小写不匹配 ('{m.direction}')，未自动修改")
        elif m.kind == "freehand":
            effect_actions.append("sharpen")
        elif m.kind in ("rect", "ellipse"):
            effect_actions.append("vignette")
        elif m.kind == "text":
            subtitle_advices.append(m.note or "（空批注）")

    # 检查相机方向矛盾（left+right 或 up+down）
    unique_cams = sorted(set(camera_actions))
    if ("pan_left" in unique_cams and "pan_right" in unique_cams) or \
       ("tilt_up" in unique_cams and "tilt_down" in unique_cams):
        patch.advisory.append("检测到互相矛盾的机位方向，未自动修改 camera")
        # 移除矛盾的相机动作
        camera_actions = [c for c in camera_actions if c not in ("pan_left", "pan_right", "tilt_up", "tilt_down")]

    if camera_actions:
        patch.changes["camera"] = "+".join(sorted(set(camera_actions)))

    if effect_actions:
        # ShotSpec 的 effect 只能是一个单值（如 vignette 或 sharpen），若有多个，选最高优先级（vignette）并把其余写入 advisory
        primary_effect = "vignette" if "vignette" in effect_actions else effect_actions[0]
        patch.changes["effect"] = primary_effect
        for eff in effect_actions:
            if eff != primary_effect:
                patch.advisory.append(f"合并多个 effect 标注：保留 '{primary_effect}'，将 '{eff}' 转入 advisory")

    for a in subtitle_advices:
        patch.advisory.append(f"台词/字幕修订建议：{a}")

    if annotation.authoritative_source:
        p = Path(annotation.authoritative_source)
        ref: dict[str, Any] = {"asset": str(p)}
        if p.exists():
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            ref["asset_sha256"] = sha
            ref["sha256"] = sha
        if anchors:
            ref["time_ms"] = anchors[0]
        patch.source_refs.append(ref)

    return patch


def dry_run_diff(spec: dict[str, Any], patch: ShotSpecPatch) -> dict[str, dict[str, Any]]:
    """对 spec 应用 patch 前后的字段 diff 比较（dry-run diff API）。"""
    updated = apply_patch(spec, patch)
    diff = {}
    keys = set(spec.keys()) | set(updated.keys())
    for k in sorted(keys):
        b = spec.get(k)
        a = updated.get(k)
        if b != a:
            diff[k] = {"before": b, "after": a}
    return diff


def apply_patch(spec: dict[str, Any], patch: ShotSpecPatch) -> dict[str, Any]:
    """把 patch.changes 应用到 ShotSpec dict 并通过 ShotSpec 校验。

    若校验失败（如包含非法字段、未知转场、未知 sfx、无效 duration 等）抛 AnnotationError。
    """
    from hevi.production.shot_spec import ShotSpec, merge_patch

    valid_fields = set(ShotSpec.model_fields.keys())
    for k in patch.changes:
        if k not in valid_fields:
            raise AnnotationError(f"未知 ShotSpec 字段 '{k}'")

    try:
        base = ShotSpec.model_validate(spec)
        merged = merge_patch(base, patch.changes)
        return merged.to_dict()
    except Exception as e:
        raise AnnotationError(f"apply_patch 失败（ShotSpec 校验不通过）: {e}") from e


def render_annotated(
    source: str | Path,
    marks: list[AnnotationMark],
    out_path: str | Path,
) -> Path:
    """把标注烧到与源同尺寸的 PNG（annotationGuide 用；不改动 authoritative 原图）。"""
    src_path = Path(source).resolve()
    out_p = Path(out_path).resolve()
    if src_path == out_p:
        raise AnnotationError("render_annotated 输出路径不得与 authoritative_source 相同（防止覆盖原图）")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(source).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)
    cjk = cjk_font(max(14, int(min(w, h) * 0.03)))

    for m in marks:
        cx, cy = int(m.nx * w), int(m.ny * h)
        bw, bh = max(8, int(m.nw * w)), max(8, int(m.nh * h))
        if m.kind == "pin":
            r = max(8, int(min(w, h) * 0.02))
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=m.color, width=3)
            draw.line((cx, cy, cx, cy - r * 2), fill=m.color, width=3)
        elif m.kind == "arrow":
            L = max(16, int(min(w, h) * 0.05))
            dx, dy = 0, 0
            if m.direction == "right":
                dx = L
            elif m.direction == "left":
                dx = -L
            elif m.direction == "up":
                dy = -L
            elif m.direction == "down":
                dy = L
            draw.line((cx, cy, cx + dx, cy + dy), fill=m.color, width=4)
            if dx or dy:
                draw.ellipse((cx + dx - 4, cy + dy - 4, cx + dx + 4, cy + dy + 4), fill=m.color)
        elif m.kind == "freehand":
            draw.ellipse((cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2), outline=m.color, width=3)
        elif m.kind == "rect":
            draw.rectangle((cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2), outline=m.color, width=3)
        elif m.kind == "ellipse":
            draw.ellipse((cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2), outline=m.color, width=3)
        elif m.kind == "text" and m.note:
            draw.text((cx, cy), m.note, fill=m.color, font=cjk)

    img.save(out, "PNG")
    return out
