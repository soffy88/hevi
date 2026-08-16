"""草图编辑子系统 —— 编辑执行 / 结构对比 / 评分校准(3O 内化 Round 3e,来源 dramaclaw sketch_edit_*)。

dramaclaw 的 sketch 子系统在"选择/闸门"(hevi.sketch_storyboard 已内化)之外还有:
  - **编辑执行**(sketch_edit_execute):对草图应用确定性编辑操作(裁切/重构图/去网格线/
    上色提示),产物可复核;
  - **结构对比**(sketch_comparer):草图 vs 上色图的结构一致性(边缘/轮廓,非像素);
  - **评分校准**(sketch_scorer + label_validation):覆盖率/构图/风格匹配的可解释评分;
  - **pose 提示**(sketch_pose_service):给草图叠 pose 骨架参考线。

本模块为 hevi 暂驻(待上游 `oskill.sketch_edit`),全部纯 PIL 可测。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 支持的结构对比采样(边缘近似:灰度缩略 + 差值)。
_STRUCTURE_GRID = 16


@dataclass
class SketchEditOp:
    """一个确定性编辑操作。"""

    op: str  # crop | reframe | grayscale | remove_grid | overlay_pose
    params: dict[str, Any] = field(default_factory=dict)
    note: str = ""


@dataclass
class SketchEditResult:
    """编辑产物 + 复核信息。"""

    out_path: Path
    applied: list[str] = field(default_factory=list)  # 已应用的 op 名
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "out_path": str(self.out_path),
            "applied": self.applied,
            "warnings": self.warnings,
        }


class SketchEditorError(Exception):
    """草图编辑失败。"""


def apply_sketch_edits(
    sketch_path: str | Path,
    out_path: str | Path,
    ops: list[SketchEditOp],
) -> SketchEditResult:
    """顺序应用编辑操作(纯 PIL,确定性;未知 op 记 warning 跳过)。"""
    from PIL import Image, ImageDraw

    src = Path(sketch_path)
    if not src.exists():
        raise SketchEditorError(f"sketch not found: {src}")
    try:
        img = Image.open(src).convert("RGB")
    except Exception as e:
        raise SketchEditorError(f"cannot open {src}: {e}") from e

    result = SketchEditResult(out_path=Path(out_path))
    for op in ops:
        if op.op == "crop":
            box = op.params.get("box")
            if isinstance(box, (list, tuple)) and len(box) == 4:
                crop_box = tuple(int(v) for v in box)
                img = img.crop(crop_box)  # type: ignore[arg-type]
                result.applied.append("crop")
            else:
                result.warnings.append("crop: 缺 box")
        elif op.op == "reframe":
            # 重构图:等比外扩/内缩到目标宽高(contain),白底补边(安全区纪律)
            target_w = int(op.params.get("width", img.width))
            target_h = int(op.params.get("height", img.height))
            canvas = Image.new("RGB", (target_w, target_h), (255, 255, 255))
            img.thumbnail((target_w, target_h))
            canvas.paste(img, ((target_w - img.width) // 2, (target_h - img.height) // 2))
            img = canvas
            result.applied.append("reframe")
        elif op.op == "grayscale":
            img = img.convert("L").convert("RGB")
            result.applied.append("grayscale")
        elif op.op == "remove_grid":
            # 去网格线:对 3x3/5x5 接缝的白色/近白线条做中值糊化(近似)
            # 网格线通常位于比例位置;这里做全图轻中值(3px)弱化接缝,确定性可复现
            img = img.filter(ImageFilter_MEDIAN(3))
            result.applied.append("remove_grid")
        elif op.op == "overlay_pose":
            # 叠 pose 骨架参考线(简单火柴人占位:头圆 + 躯干/四肢线段)
            overlay = img.copy()
            draw = ImageDraw.Draw(overlay, "RGBA")
            pose = op.params.get("pose", {})
            cx = int(pose.get("cx", img.width // 2))
            cy = int(pose.get("cy", img.height // 2))
            scale = float(pose.get("scale", 1.0)) * min(img.width, img.height) / 8.0
            head_r = max(int(scale * 0.5), 6)
            head_y = cy - int(scale * 1.6)
            draw.ellipse(
                (cx - head_r, head_y - head_r, cx + head_r, head_y + head_r),
                outline=(255, 60, 60, 220), width=3,
            )
            neck = (cx, head_y)
            hip = (cx, cy)
            draw.line([neck, hip], fill=(255, 60, 60, 220), width=3)
            leg_y = cy + int(scale * 1.6)
            arm_y = cy - int(scale * 0.4)
            draw.line([hip, (cx - int(scale * 1.1), leg_y)], fill=(255, 60, 60, 220), width=3)
            draw.line([hip, (cx + int(scale * 1.1), leg_y)], fill=(255, 60, 60, 220), width=3)
            draw.line([neck, (cx - int(scale * 1.3), arm_y)], fill=(255, 60, 60, 220), width=3)
            draw.line([neck, (cx + int(scale * 1.3), arm_y)], fill=(255, 60, 60, 220), width=3)
            img = overlay
            result.applied.append("overlay_pose")
        else:
            result.warnings.append(f"unknown op {op.op!r}")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return result


def _median3(img: Any) -> Any:
    from PIL import ImageFilter

    return img.filter(ImageFilter.MedianFilter(3))


ImageFilter_MEDIAN = _median3


def structure_difference(a_path: str | Path, b_path: str | Path) -> float:
    """结构一致性:两图 16×16 灰度的均差(轮廓级,非像素级);0 = 结构一致。"""
    from PIL import Image

    def _thumb(p: Path) -> bytes:
        img = Image.open(p).convert("L").resize((_STRUCTURE_GRID, _STRUCTURE_GRID))
        return img.tobytes()

    a = _thumb(Path(a_path))
    b = _thumb(Path(b_path))
    return sum(abs(x - y) for x, y in zip(a, b, strict=False)) / (len(a) * 255.0)


def score_sketch_with_labels(
    *,
    coverage: float,
    composition_ok: bool,
    style_match: float,
    labels_valid: bool = True,
    label_violations: list[str] | None = None,
) -> dict[str, Any]:
    """可解释评分:覆盖率/构图闸门/风格匹配 + 标注校验(编辑后标签是否仍成立)。"""
    violations = list(label_violations or [])
    base = 1.5 * coverage + 0.5 * style_match
    if not composition_ok:
        base = 0.0
    if not labels_valid:
        base *= 0.5
        violations.append("labels_invalid")
    return {
        "score": round(base, 3),
        "coverage": coverage,
        "composition_ok": composition_ok,
        "style_match": style_match,
        "labels_valid": labels_valid,
        "label_violations": violations,
    }
