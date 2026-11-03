"""preflight.first_frame —— 首帧验真。

诚实边界（写进代码，不许绕过）：
- 本机无 OCR（tesseract 未装），伪文字**无法自动判定**：只出人工目视项，
  绝不谎称“已验无伪文字”。
- 本机无人脸识别模型：与定妆的“漂移检查”只能用色彩直方图距离作
  粗信号（场景一变距离就变），超阈只判 WARN“须人工比对”，
  绝不判“脸漂移”或“脸一致”。
- 画幅／尺寸／文件存在是硬查：FAIL 拦住。

直方图阈值 HIST_REVIEW_THRESHOLD 的标定见 BACKTEST.md：商鞅 13 拍
与定妆的距离分布不支持用该信号区分 beat08，因此阈值只拦极端值，
日常帧一律走人工比对清单。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from hevi.preflight.beats import Beat
from hevi.preflight.findings import Finding

ASPECT_TOLERANCE = 0.05
HIST_REVIEW_THRESHOLD = 0.90  # 只拦极端偏离；日常漂移靠人工清单

# 每帧必出的人工目视项（伪文字／脸／画风三项，缺一不可）。
HUMAN_CHECKLIST = (
    "目视：画面有无伪文字（牌匾／题字／招牌／书页上的无意义字形）",
    "目视：出场人物脸与定妆是否同一人（发型／服饰／面部特征）",
    "目视：画风是否与定妆同一画风（有无写实／绘画跳变）",
)


def _histogram(path: Path) -> list[float]:
    from PIL import Image

    im = Image.open(path).convert("RGB").resize((64, 64))
    hist = [0.0] * (256 * 3)
    pixels = list(im.getdata())
    for r, g, b in pixels:
        hist[r] += 1
        hist[256 + g] += 1
        hist[512 + b] += 1
    n = max(1, len(pixels))
    return [x / n for x in hist]


def _hist_distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def check_first_frame(
    beat: Beat,
    character_sheets: dict[str, str | Path] | None = None,
) -> tuple[list[Finding], list[str]]:
    """返回 (findings, human_checklist)。"""
    findings: list[Finding] = []
    checklist: list[str] = list(HUMAN_CHECKLIST)
    sheets = character_sheets or {}

    if not beat.first_frame:
        findings.append(Finding(
            "WARN", "first_frame_missing",
            "无首帧引用：图生视频缺首帧锚点，人物／场景一致性无从锁定",
            beat_id=beat.beat_id,
        ))
        return findings, checklist

    frame = Path(beat.first_frame)
    if not frame.exists():
        findings.append(Finding(
            "FAIL", "first_frame_not_found",
            f"首帧文件不存在：{frame}",
            beat_id=beat.beat_id,
        ))
        return findings, checklist

    try:
        from PIL import Image

        with Image.open(frame) as im:
            width, height = im.size
    except Exception as exc:  # noqa: BLE001 - 打不开就是 FAIL
        findings.append(Finding(
            "FAIL", "first_frame_unreadable",
            f"首帧无法读取：{exc}",
            beat_id=beat.beat_id,
        ))
        return findings, checklist

    findings.append(Finding(
        "INFO", "first_frame_size",
        f"首帧 {width}x{height}",
        beat_id=beat.beat_id,
        detail={"width": width, "height": height},
    ))

    # 画幅匹配（目标画幅 16:9 → 1.7778，9:16 → 0.5625）
    target_ratio = {"16:9": 16 / 9, "9:16": 9 / 16}.get(beat.aspect)
    if target_ratio is not None:
        ratio = width / height if height else 0.0
        if abs(ratio - target_ratio) > ASPECT_TOLERANCE:
            findings.append(Finding(
                "FAIL", "aspect_mismatch",
                f"首帧画幅 {ratio:.3f} 与目标 {beat.aspect}（{target_ratio:.3f}）不匹配",
                beat_id=beat.beat_id,
                detail={"ratio": round(ratio, 4), "target": round(target_ratio, 4)},
            ))

    # 直方图粗信号：只报告距离，超极端阈才 WARN，且措辞不许写成脸判定。
    distances: dict[str, float] = {}
    for ch in beat.characters:
        sheet = sheets.get(ch.char_id) or (
            Path(ch.sheet_path) if ch.sheet_path else None
        )
        if sheet and Path(sheet).exists():
            try:
                d = _hist_distance(_histogram(frame), _histogram(Path(sheet)))
                distances[ch.char_id] = round(d, 4)
            except Exception:  # noqa: BLE001 - 直方图失败只丢信号，不阻塞
                pass
    if distances:
        worst = max(distances.values())
        findings.append(Finding(
            "INFO", "histogram_distance",
            f"首帧与定妆直方图距离：{distances}（粗信号，非人脸判定）",
            beat_id=beat.beat_id, detail={"distances": distances},
        ))
        if worst > HIST_REVIEW_THRESHOLD:
            findings.append(Finding(
                "WARN", "histogram_far",
                f"首帧与定妆直方图距离 {worst:.3f} 偏大：须人工比对脸／画风后再发",
                beat_id=beat.beat_id, detail={"distances": distances},
            ))

    return findings, checklist


def contact_sheet(
    frame: str | Path,
    sheets: list[str | Path],
    out_path: str | Path,
) -> Path:
    """把首帧与定妆拼成一张横向比对图，供人工目视。返回输出路径。"""
    from PIL import Image

    paths = [Path(frame), *[Path(s) for s in sheets]]
    images = []
    for p in paths:
        with Image.open(p) as im:
            images.append(im.convert("RGB").copy())
    thumb_h = 256
    thumbs = []
    for im in images:
        w, h = im.size
        thumbs.append(im.resize((int(w * thumb_h / h), thumb_h)))
    total_w = sum(t.width for t in thumbs)
    sheet = Image.new("RGB", (total_w, thumb_h), (255, 255, 255))
    x = 0
    for t in thumbs:
        sheet.paste(t, (x, 0))
        x += t.width
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
