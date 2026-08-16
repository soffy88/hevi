"""hevi-watch CLI —— 摄入侧 skill 的执行入口(含零配置预检)。

用法:
    uv run python -m hevi.skills.watch_cli <url|本地路径> --out-dir <dir> [--detail balanced] \
        [--budget N] [--whisper-fallback] [--contact-sheet] [--preflight]

输出:结构化 WatchResult 摘要(帧数/时长/转写首行/联络表路径/notes)。
--preflight:先跑环境预检(缺二进制给出 exit code 式报告,不阻断本地文件摄入)。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hevi.ingest.contact_sheet import build_contact_sheet
from hevi.ingest.preflight import check_env
from hevi.ingest.video_frames import WatchDetail
from hevi.ingest.video_watch import watch_video


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hevi-watch: 摄入侧视频理解")
    parser.add_argument("source", help="URL 或本地视频路径")
    parser.add_argument("--out-dir", type=Path, default=Path(".hevi_watch"), help="产物目录")
    parser.add_argument(
        "--detail", default="balanced", choices=[d.value for d in WatchDetail]
    )
    parser.add_argument("--budget", type=int, default=None, help="帧预算(默认按时长自动)")
    parser.add_argument("--whisper-fallback", action="store_true", help="无字幕时走 faster-whisper")
    parser.add_argument("--contact-sheet", action="store_true", help="额外生成联络表")
    parser.add_argument("--preflight", action="store_true", help="先跑环境预检")
    args = parser.parse_args(argv)

    if args.preflight:
        report = check_env(require_url_tools=str(args.source).startswith(("http://", "https://")))
        print(f"preflight: can_proceed={report.can_proceed}")
        if report.missing_binaries:
            print(f"  missing: {', '.join(report.missing_binaries)}")
        if report.notes:
            for note in report.notes:
                print(f"  note: {note}")
        if not report.can_proceed:
            return 2  # 缺关键二进制(与 claude-video setup exit code 语义一致)

    result = watch_video(
        args.source,
        args.out_dir,
        detail=WatchDetail(args.detail),
        budget=args.budget,
        whisper_fallback=args.whisper_fallback,
    )

    print(f"watch: {result.source}")
    print(f"  frames: {result.frame_count}  duration_s: {result.duration_s:.2f}")
    print(f"  detail: {result.detail.value}")
    if result.transcript:
        print(
            f"  transcript: {len(result.transcript)} segments; "
            f"首行: {result.transcript[0].text[:60]}"
        )
    else:
        print("  transcript: (无;看 notes)")
    for note in result.notes:
        print(f"  note: {note}")

    if args.contact_sheet and result.frames:
        sheet = build_contact_sheet(
            [f.path for f in result.frames],
            args.out_dir / "contact_sheet.jpg",
            cols=5,
            thumb_width=320,
        )
        print(f"  contact_sheet: {sheet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
