"""VoiceStudio capability and workflow-plan CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hevi.audio.speech_platform import build_batch_plan
from hevi.voicepro.omodul.platform import (
    list_gallery_profiles,
    list_model_catalog,
    plan_audiobook,
    plan_dictation,
    plan_dubbing,
    plan_watermark,
    platform_diagnostics,
    route_model,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="voice-studio: local-first speech platform")
    sub = parser.add_subparsers(dest="verb", required=True)
    sub.add_parser("catalog", help="模型、声线和诊断")
    route = sub.add_parser("route", help="本地优先路由")
    route.add_argument("--kind", choices=["tts", "asr", "llm"], default="tts")
    route.add_argument("--preferred")
    dubbing = sub.add_parser("dubbing", help="配音计划")
    dubbing.add_argument("--source-video", required=True)
    dubbing.add_argument("--target-language", required=True)
    audiobook = sub.add_parser("audiobook", help="有声书计划")
    audiobook.add_argument("--source-document", required=True)
    dictation = sub.add_parser("dictation", help="听写计划")
    dictation.add_argument("--engine", default="faster_whisper")
    watermark = sub.add_parser("watermark", help="AudioSeal 计划")
    watermark.add_argument("--audio-path", required=True)
    batch = sub.add_parser("batch", help="从 JSON 文件预检批量语音")
    batch.add_argument("--input", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.verb == "catalog":
        payload = {
            "models": list_model_catalog(),
            "voices": list_gallery_profiles(),
            "diagnostics": platform_diagnostics(),
        }
    elif args.verb == "route":
        payload = route_model(kind=args.kind, preferred=args.preferred)
    elif args.verb == "dubbing":
        payload = plan_dubbing(
            source_video=args.source_video,
            target_language=args.target_language,
        )
    elif args.verb == "audiobook":
        payload = plan_audiobook(source_document=args.source_document)
    elif args.verb == "dictation":
        payload = plan_dictation(engine=args.engine)
    elif args.verb == "watermark":
        payload = plan_watermark(audio_path=args.audio_path)
    else:
        try:
            items = json.loads(args.input.read_text(encoding="utf-8"))
            if not isinstance(items, list):
                raise ValueError("batch input must be a JSON array")
            payload = build_batch_plan(items)
        except (OSError, ValueError, TypeError) as exc:
            print(f"batch input failed: {exc}", file=sys.stderr)
            return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
