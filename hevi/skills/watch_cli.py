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
    parser.add_argument("--start", type=float, default=None, help="只看窗口起点(秒)")
    parser.add_argument("--end", type=float, default=None, help="只看窗口终点(秒)")
    parser.add_argument("--whisper-fallback", action="store_true", help="无字幕时走 faster-whisper")
    parser.add_argument("--contact-sheet", action="store_true", help="额外生成联络表")
    parser.add_argument("--preflight", action="store_true", help="先跑环境预检")
    parser.add_argument("--localize", action="store_true", help="转写后出 ASS 烧录计划(xiaohu 译制档)")
    parser.add_argument(
        "--execute-localize",
        action="store_true",
        help="执行真实译制事务(需要翻译 provider；可配合 --dub)",
    )
    parser.add_argument("--target-language", default="zh-CN", help="译入语种")
    parser.add_argument(
        "--translation-provider",
        default="llm_translate",
        choices=["llm_translate", "deep_translator", "deepl", "azure_translator"],
    )
    parser.add_argument("--dub", action="store_true", help="译制后按字幕时钟生成配音并替换音轨")
    parser.add_argument("--tts-engine", default="edge_tts", help="--dub 使用的 TTS engine")
    parser.add_argument("--bilingual", action="store_true", help="双语 ASS(需同时给译文,否则降级单语)")
    parser.add_argument("--speakers", action="store_true", help="停顿启发式说话人标签")
    parser.add_argument("--rough-cut", action="store_true", help="去掉语气词再出转写")
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
        start_s=args.start,
        end_s=args.end,
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

    segments = list(result.transcript)
    if args.rough_cut and segments:
        from hevi.ingest.speech_rough_cut import rough_cut

        kept, dropped = rough_cut(segments)
        print(f"  rough_cut: kept={len(kept)} dropped={len(dropped)}")
        segments = kept
    if args.speakers and segments:
        from hevi.ingest.speakers import label_speakers

        segments = label_speakers(segments)
        print(f"  speakers: {sorted({s.speaker for s in segments if s.speaker})}")
    video = ""
    if not str(args.source).startswith(("http://", "https://")):
        video = str(args.source)
    if args.localize:
        if args.execute_localize:
            if not video:
                print("  localize-error: 真实执行需要本地视频路径", file=sys.stderr)
                return 3
            import asyncio

            from hevi.production.media_workflows import video_localization_workflow

            localized = asyncio.run(
                video_localization_workflow(
                    {
                        "target_language": args.target_language,
                        "source_language": "auto",
                        "translation_provider": args.translation_provider,
                        "bilingual": bool(args.bilingual),
                        "dub": bool(args.dub),
                        "tts_engine": args.tts_engine,
                    },
                    {"source_video_path": video, "source_segments": segments},
                    args.out_dir,
                )
            )
            print(f"  localize: status={localized['status']} report={localized['report_path']}")
            if localized["status"] != "succeeded":
                print(f"  localize-error: {localized.get('error')}", file=sys.stderr)
                return 3
            print(f"  localized_video: {localized['findings']['output_video_path']}")
            return 0

        from hevi.ingest.video_localize import plan_localize

        loc = plan_localize(
            segments,
            bilingual=bool(args.bilingual),
            speakers=False,
            work_dir=args.out_dir,
            video_path=video,
        )
        print(f"  localize: ass={loc.ass_path} bilingual={loc.bilingual}")
        for note in loc.notes:
            print(f"  localize-note: {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
