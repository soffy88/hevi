#!/usr/bin/env python3
"""报告 4 条 E2E 的逐帧文字包围盒越界检查结果（r5 B3）。

权威检查在 render.py 里：渲染时逐帧（30fps ≥ 2fps）量出本帧所有字的屏幕包围盒
（fillText/strokeText 的实测坐标，含相机变换），越出画面内缩 5% 的安全区就记一条 violation，
落盘成 <mp4>.textsafe.json；produce.py 把它读进 record.json 的 text_safe，并作为
text_in_safe_area 门禁（violations>0 即红灯）。

本脚本不做第二次图像检测（对成片做 Canny 猜文字框并不可靠，会假阳/假阴），
只从各条 record.json 读出那次真实逐帧检查的结果，汇总打印，供 DONE 引用。
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "output/artmotion_e2e"
    tasks = ["task_0", "task_1", "task_2", "task_3_comparison"]
    rows = []
    ok = True
    for task_id in tasks:
        rec_path = out_dir / task_id / "record.json"
        if not rec_path.is_file():
            print(f"{task_id}: 缺 record.json（{rec_path}）")
            ok = False
            continue
        rec = json.loads(rec_path.read_text())["records"][0]
        ts = rec.get("text_safe")
        if not ts:
            print(f"{task_id}: 无 text_safe（逐帧越界检查未产出）")
            ok = False
            continue
        rows.append((task_id, ts))
        tag = "PASS" if ts["violations"] == 0 else "FAIL"
        print(
            f"{task_id}: {tag}  {ts['violations']}/{ts['frames']} 帧越出安全区"
            f"（{ts['width']}x{ts['height']} @ {ts['fps']}fps, safe={ts['safe_frac']:.0%}）"
        )
        if ts["violations"]:
            ok = False
            for v in ts.get("first", [])[:5]:
                print(f"    越界 t={v['t']}s bbox={v['bbox']}")
    total = sum(ts["frames"] for _, ts in rows)
    print(f"\n合计 {len(rows)} 条 / {total} 帧，全部 {('通过' if ok else '未通过')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
