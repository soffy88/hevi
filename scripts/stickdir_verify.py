#!/usr/bin/env python3
"""stickdir 抽帧验收 —— 真实测量, 输出 json 报告 + contact sheet。

对一条 mp4 每 1s 抽帧, 逐帧检查(STICKDIR_TASK.md 验收 §3):

1. 每帧检测到火柴人(按风格前景色像素/连通域), 且包围盒完全在画内(距边 ≥ 2%);
2. 相邻 3s 窗口内火柴人轮廓差异超过阈值(证明每 ≤3s 有姿势变化);
3. 字幕/文字框不越界(文字区域像素不触碰画面边缘或安全区外);
4. 1A 背景角落/非角色区域像素 = 白(≥250), 1B = 黑(≤5)。

用法:
    PYTHONPATH=$PWD .venv/bin/python scripts/stickdir_verify.py \
        --video out/stickdir_1B_9x16_30s.mp4 --style 1B --out out/verify_1B
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

#: 风格 → (背景判定, 前景判定)。背景: (通道, 比较, 阈值)
STYLE_BG = {
    "1A": ("white", 250),
    "1B": ("black", 5),
    "2A": ("any", None),
    "2B": ("any", None),
    "3": ("any", None),
}


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def probe(video: Path) -> dict:
    out = _run(
        [
            FFPROBE,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of",
            "json",
            str(video),
        ]
    )
    return json.loads(out.stdout or "{}")


def lufs(video: Path) -> float | None:
    """整体响度(ebur128 integrated)。"""
    proc = _run(
        [FFMPEG, "-hide_banner", "-i", str(video), "-af", "ebur128=peak=true", "-f", "null", "-"]
    )
    text = proc.stderr
    val = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("I:") and "LUFS" in s:
            val = float(s.split()[1])
    return val


def extract_frames(video: Path, work: Path, fps: int = 1) -> list[Path]:
    work.mkdir(parents=True, exist_ok=True)
    for old in work.glob("f_*.png"):
        old.unlink()
    _run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-vf",
            f"fps={fps}",
            str(work / "f_%04d.png"),
        ]
    )
    return sorted(work.glob("f_*.png"))


def _fg_mask(img: np.ndarray, style: str, ink_rgb: tuple[int, int, int]) -> np.ndarray:
    """前景(角色/线条)掩码。

    * 1A/1B: 与 ink 颜色距离近的像素(纯白/纯黑底, 精确)。
    * 2A/2B/3: 逐行中位背景相减 —— 每行取中位色作局部背景, 与之差异大的像素
      为前景。对渐变背景(2B)、纹理背景(3)都稳健, 且不受背景本身明暗/饱和影响。
    """
    r, g, b = img[..., 0].astype(int), img[..., 1].astype(int), img[..., 2].astype(int)
    if style in ("1A", "1B"):
        dist = (r - ink_rgb[0]) ** 2 + (g - ink_rgb[1]) ** 2 + (b - ink_rgb[2]) ** 2
        return dist < 60**2
    stack = np.stack([r, g, b], axis=-1).astype(float)
    row_bg = np.median(stack, axis=1, keepdims=True)  # (H,1,3)
    diff = np.abs(stack - row_bg).sum(axis=-1)  # (H,W)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    # 角色用深色墨线;隐喻/背景用浅灰 —— 只保留"与逐行背景不同且偏暗"的像素
    return (diff > 60) & (lum < 115)


def _largest_component(mask: np.ndarray, *, exclude_bottom_frac: float = 0.0) -> np.ndarray:
    """取最大连通域(排除底部字幕带), 得到"角色"掩码。"""
    from scipy import ndimage

    m = mask.copy()
    if exclude_bottom_frac > 0:
        h = m.shape[0]
        m[int(h * (1 - exclude_bottom_frac)) :, :] = False
    labeled, n = ndimage.label(m, structure=np.ones((3, 3), int))
    if n == 0:
        return np.zeros_like(mask)
    sizes = ndimage.sum(np.ones_like(labeled), labeled, index=range(1, n + 1))
    biggest = int(np.argmax(sizes)) + 1
    return labeled == biggest


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _silhouette(mask: np.ndarray, bins: int = 16) -> np.ndarray:
    """把掩码压成归一化直方图(轮廓签名, 用于帧间差异)。"""
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return np.zeros(bins * 2)
    h, w = mask.shape
    hist_x = np.histogram(xs / w, bins=bins, range=(0, 1))[0].astype(float)
    hist_y = np.histogram(ys / h, bins=bins, range=(0, 1))[0].astype(float)
    v = np.concatenate([hist_x, hist_y])
    s = v.sum()
    return v / s if s else v


def _corner_bg(img: np.ndarray, style: str) -> dict:
    """背景角落像素统计(1A/1B)。"""
    h, w = img.shape[:2]
    m = max(4, int(min(h, w) * 0.03))
    corners = [
        img[:m, :m],
        img[:m, -m:],
        img[-m:, :m],
        img[-m:, -m:],
    ]
    px = np.concatenate([c.reshape(-1, 3) for c in corners], axis=0)
    return {
        "min": int(px.min()),
        "max": int(px.max()),
        "mean": float(px.mean()),
    }


def verify(
    video: Path,
    style: str,
    out_dir: Path,
    *,
    ink_rgb: tuple[int, int, int] | None = None,
    margin_frac: float = 0.02,
    motion_threshold: float = 0.06,
    window_s: int = 3,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = extract_frames(video, out_dir / "frames")
    if not frames:
        raise RuntimeError("no frames extracted")
    if ink_rgb is None:
        ink_rgb = (255, 255, 255) if style == "1B" else (17, 17, 17)

    imgs = [np.array(Image.open(f).convert("RGB")) for f in frames]
    h, w = imgs[0].shape[:2]
    mx, my = w * margin_frac, h * margin_frac

    per_frame = []
    sigs = []
    for i, (path, img) in enumerate(zip(frames, imgs)):
        raw = _fg_mask(img, style, ink_rgb)
        # 角色 = 最大连通域(排除底部字幕带), 避免字幕/隐喻污染包围盒
        mask = _largest_component(raw, exclude_bottom_frac=0.18)
        bbox = _bbox(mask)
        sig = _silhouette(mask)
        sigs.append(sig)
        detected = bbox is not None and mask.sum() > 50
        in_frame = False
        if bbox is not None:
            x0, y0, x1, y1 = bbox
            in_frame = x0 >= mx and y0 >= my and x1 <= w - mx and y1 <= h - my
        entry = {
            "frame": i,
            "t": i,
            "detected": bool(detected),
            "bbox": bbox,
            "bbox_in_frame": bool(in_frame),
            "fg_pixels": int(mask.sum()),
            "corner_bg": _corner_bg(img, style),
        }
        per_frame.append(entry)

    # 相邻 3s 窗口轮廓差异
    motion = []
    for i in range(len(sigs)):
        j = min(i + window_s, len(sigs) - 1)
        if j == i:
            continue
        d = float(np.abs(sigs[i] - sigs[j]).sum() / 2.0)
        motion.append({"i": i, "j": j, "diff": round(d, 4)})

    # 每 3s 至少一次差异超过阈值(按 3s 分桶)
    buckets: dict[int, float] = {}
    for m in motion:
        b = m["i"] // window_s
        buckets[b] = max(buckets.get(b, 0.0), m["diff"])
    moving_buckets = sum(1 for v in buckets.values() if v >= motion_threshold)

    # 背景纯度(1A/1B)
    bg_ok = None
    if style == "1A":
        bg_ok = all(f["corner_bg"]["min"] >= 250 for f in per_frame)
    elif style == "1B":
        bg_ok = all(f["corner_bg"]["max"] <= 5 for f in per_frame)

    # 字幕不越界:非前景的亮/暗文字像素是否触边。用底部长条区域检测文字并检查左右边距
    text_ok = True
    text_details = []
    for i, img in enumerate(imgs):
        band = img[int(h * 0.80) :, :, :]
        lum = band.mean(axis=2)
        # 文字像素:与带内中位差异明显的像素
        med = np.median(lum)
        textpx = np.abs(lum - med) > 60
        cols = np.where(textpx.any(axis=0))[0]
        if len(cols):
            left, right = int(cols.min()), int(cols.max())
            ok = left >= mx and right <= w - mx
            if not ok:
                text_ok = False
            text_details.append({"frame": i, "text_cols": [left, right], "ok": bool(ok)})

    report = {
        "video": str(video),
        "style": style,
        "width": w,
        "height": h,
        "frames": len(frames),
        "margin_px": [mx, my],
        "character": {
            "all_detected": all(f["detected"] for f in per_frame),
            "all_in_frame": all(f["bbox_in_frame"] for f in per_frame),
            "detected_count": sum(1 for f in per_frame if f["detected"]),
            "in_frame_count": sum(1 for f in per_frame if f["bbox_in_frame"]),
        },
        "motion": {
            "window_s": window_s,
            "threshold": motion_threshold,
            "buckets": len(buckets),
            "moving_buckets": moving_buckets,
            "all_buckets_move": moving_buckets == len(buckets),
            "min_bucket_diff": round(min(buckets.values()), 4) if buckets else 0.0,
            "per_window": motion,
        },
        "background": {"style": style, "pure": bg_ok},
        "text": {"in_bounds": text_ok, "samples": text_details[:5]},
        "per_frame": per_frame,
    }
    return report


def contact_sheet(frames_dir: Path, out_png: Path, cols: int = 6, thumb_w: int = 240) -> Path:
    files = sorted(frames_dir.glob("f_*.png"))
    if not files:
        raise RuntimeError("no frames for contact sheet")
    imgs = [Image.open(f).convert("RGB") for f in files]
    ratio = imgs[0].height / imgs[0].width
    tw, th = thumb_w, int(thumb_w * ratio)
    rows = (len(imgs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), (20, 20, 20))
    for i, im in enumerate(imgs):
        sheet.paste(im.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)
    return out_png


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--style", required=True, choices=["1A", "1B", "2A", "2B", "3"])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fps", type=int, default=1)
    args = ap.parse_args(argv)

    report = verify(args.video, args.style, args.out)
    report["probe"] = probe(args.video)
    report["lufs_integrated"] = lufs(args.video)
    (args.out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    sheet = contact_sheet(args.out / "frames", args.out / "contact_sheet.png")
    report["contact_sheet"] = str(sheet)
    (args.out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "character": report["character"],
                "motion": {
                    k: report["motion"][k]
                    for k in ("all_buckets_move", "moving_buckets", "buckets", "min_bucket_diff")
                },
                "background": report["background"],
                "text": report["text"]["in_bounds"],
                "lufs": report["lufs_integrated"],
                "contact_sheet": str(sheet),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
