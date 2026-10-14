#!/usr/bin/env python3
"""task_2（14_8bit 财经图表）数值标签可读性检查（r6 B2）。

r5 阻断：8bit 把整帧按 1/8 量化，CJK 文字与数字被毁（「887」→「SS7」、「609」→「G09」）。
r6 修复后要求：task_2 每个数值标签 OCR 读出 206/309/392/609/887 全对（这里按数据实际值 253/306/392/609/887）。

本脚本对渲染出的全分辨率帧跑本地 OCR（RapidOCR / onnxruntime，CPU-only，不用云 API），
从图上直接读数字标签，逐个和 data.series 的期望值比对。OCR 读不到或读错 → 非零退出。

用法：
  uv run --no-project --python 3.12 --with rapidocr-onnxruntime --with pillow \
    scripts/artmotion_ocr_check.py <帧目录或单个 png> --expect 253,306,392,609,887
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:  # pragma: no cover - 明确报错，不兜底
    print("需要 rapidocr-onnxruntime（本地 OCR，CPU-only）：uv run --with rapidocr-onnxruntime ...", file=sys.stderr)
    raise SystemExit(2)

from PIL import Image


def read_digits(img_path: Path) -> list[str]:
    """OCR 一张图，返回所有识别出的字符串（数字标签与标题都可能命中）。"""
    ocr = RapidOCR()
    res, _ = ocr(str(img_path))
    if not res:
        return []
    return [str(r[1]) for r in res]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="帧目录（取其中所有 png）或单个 png")
    ap.add_argument("--expect", required=True, help="逗号分隔的期望数值（data.series 的 value）")
    ap.add_argument("--min-match", type=int, default=None, help="至少命中多少个期望值（默认全部）")
    a = ap.parse_args()

    expect = [s.strip() for s in a.expect.split(",") if s.strip()]
    need = a.min_match if a.min_match is not None else len(expect)

    p = Path(a.path)
    imgs = sorted(p.glob("*.png")) if p.is_dir() else [p]
    if not imgs:
        print(f"没有帧：{a.path}", file=sys.stderr)
        return 1

    found_all: set[str] = set()
    print(f"OCR {len(imgs)} 帧，期望数值：{expect}")
    for img in imgs:
        texts = read_digits(img)
        joined = " ".join(texts)
        nums = set(re.findall(r"\d{2,4}", joined))
        hit = [e for e in expect if e in nums]
        found_all.update(hit)
        miss = [e for e in expect if e not in found_all]
        print(f"  {img.name}: 识别 {nums or '（无）'}  本帧命中 {hit}  累计命中 {sorted(found_all)}")
    ok = len(found_all) >= need
    print(f"\n{'PASS' if ok else 'FAIL'}：命中 {len(found_all)}/{len(expect)}（要求 ≥{need}）")
    if not ok:
        print(f"  未读出：{[e for e in expect if e not in found_all]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
