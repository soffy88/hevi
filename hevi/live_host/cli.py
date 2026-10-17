"""赛博小雅 CLI：本地实时直播主持（stdin 弹幕循环）。

用法:
    python -m hevi.live_host.cli            # stdin 弹幕 → 逐句 TTS wav
    python -m hevi.live_host.cli --audio a.wav   # 单条音频输入跑一轮
    python -m hevi.live_host.cli --synthesize-questions out/  # 生成 3 条测试音频
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from hevi.live_host import EngineConfig, LiveHost
from hevi.live_host.ingest.audio_source import audio_file_source
from hevi.live_host.ingest.stdin_source import stdin_danmaku

logger = logging.getLogger(__name__)


def _synthesize_questions(out_dir: str) -> list[Path]:
    """用 Piper 合成 3 条中文测试提问音频（E2E 用）。"""
    from hevi.live_host.oprim.tts_piper import PiperTTS

    questions = [
        "小雅你好,能介绍一下你自己吗?",
        "今天天气怎么样,你有什么穿搭建议?",
        "可以讲一个关于科技的冷知识吗?",
    ]
    piper = PiperTTS()
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, q in enumerate(questions):
        p = d / f"q{i + 1}.wav"
        piper.synthesize(q, p)
        paths.append(p)
        print(f"合成提问 {i + 1}: {q} → {p}")
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="赛博小雅 全本地实时主持")
    parser.add_argument("--audio", help="单条音频文件(wav)，跑一轮")
    parser.add_argument("--workdir", default="audit/live_host/run")
    parser.add_argument("--tts", choices=["piper", "cosyvoice"], default="piper")
    parser.add_argument("--synthesize-questions", metavar="DIR", help="仅生成测试提问音频")
    parser.add_argument("--no-aigc-label", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg = EngineConfig(tts=args.tts)
    if args.no_aigc_label:
        cfg.aigc_label_enabled = False

    if args.synthesize_questions:
        _synthesize_questions(args.synthesize_questions)
        return 0

    host = LiveHost(cfg, workdir=args.workdir)

    if args.audio:
        out = host.turn_labeled(audio_file_source(args.audio))
        _report(out)
        return 0

    # stdin 弹幕循环
    print("赛博小雅已上线（Ctrl-D 退出）。输入弹幕文本：")
    for turn in stdin_danmaku():
        out = host.turn_labeled(turn)
        _report(out)
    return 0


def _report(out) -> None:
    print("—" * 40)
    print("提问:", out.question)
    print("回复:", out.reply_text)
    for u in out.utterances:
        print(f"  [{u.index}] {u.text} → {u.audio_path}")
    print("计时:", out.timing.to_dict(), "首音频=%.2fs" % out.timing.first_audio)
    print("—" * 40)


if __name__ == "__main__":
    sys.exit(main())
