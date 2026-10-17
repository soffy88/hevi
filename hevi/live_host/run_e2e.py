"""E2E 实测：3 条中文音频提问 → 全流程 → 测量各阶段延迟 + TTS 输出 CER。

流水线：
  合成提问 wav(Piper) → VAD → STT(faster-whisper) → LLM(ollama) → TTS(Piper) → wav
  CER：把 LLM 每句 TTS 合成的 wav 再喂回 faster-whisper，与原文比对（往返字错率）。

输出：audit/live_host/REPORT.md（真实测量值，绝不硬编码）。
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from hevi.live_host import EngineConfig, LiveHost
from hevi.live_host.eval_cer import cer
from hevi.live_host.ingest.audio_source import audio_file_source
from hevi.live_host.oprim.stt_whisper import WhisperSTT

logger = logging.getLogger(__name__)

QUESTIONS = [
    "小雅你好,能介绍一下你自己吗?",
    "今天天气怎么样,你有什么穿搭建议?",
    "可以讲一个关于科技的冷知识吗?",
]


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    workdir = Path("audit/live_host/run")
    workdir.mkdir(parents=True, exist_ok=True)

    cfg = EngineConfig()
    host = LiveHost(cfg, workdir=workdir)

    # 1) 合成提问（与 MVP 同一 Piper 引擎，模拟观众语音）
    from hevi.live_host.oprim.tts_piper import PiperTTS

    piper = PiperTTS()
    q_dir = workdir / "questions"
    q_dir.mkdir(parents=True, exist_ok=True)
    q_paths = []
    synth_t = []
    for i, q in enumerate(QUESTIONS):
        t0 = time.perf_counter()
        p = q_dir / f"q{i + 1}.wav"
        piper.synthesize(q, p)
        synth_t.append(time.perf_counter() - t0)
        q_paths.append(p)
        logger.warning("合成提问 %d: %s (%.2fs)", i + 1, q, synth_t[-1])

    # 2) 转写（用于 STT 往返与 CER 计算）
    stt = WhisperSTT(cfg.whisper_model, cfg.whisper_device, cfg.whisper_compute)

    results = []
    for i, (q_text, q_path) in enumerate(zip(QUESTIONS, q_paths)):
        out = host.turn(audio_file_source(q_path))

        # 3) TTS 输出往返 CER：把每句合成 wav 再转写，与原文比对
        utt_cers = []
        for u in out.utterances:
            if u.audio_path is None:
                utt_cers.append(None)
                continue
            heard = stt.transcribe(u.audio_path)
            utt_cers.append(round(cer(u.text, heard), 4))

        results.append(
            {
                "index": i + 1,
                "question_text": q_text,
                "stt_transcript": out.transcript,
                "reply_text": out.reply_text,
                "n_utterances": len(out.utterances),
                "timing": out.timing.to_dict(),
                "first_audio": round(out.timing.first_audio, 3),
                "utt_audio_paths": [str(u.audio_path) for u in out.utterances],
                "utt_cer": utt_cers,
                "utt_cer_mean": (
                    round(
                        sum(c for c in utt_cers if c is not None)
                        / len([c for c in utt_cers if c is not None]),
                        4,
                    )
                    if any(c is not None for c in utt_cers)
                    else None
                ),
            }
        )

    # 汇总
    n = len(results)
    avg_timing = {
        k: round(sum(r["timing"][k] for r in results) / n, 3) for k in results[0]["timing"]
    }
    avg_first_audio = round(sum(r["first_audio"] for r in results) / n, 3)
    all_cers = [c for r in results for c in (r["utt_cer"] or []) if c is not None]
    mean_cer = round(sum(all_cers) / len(all_cers), 4) if all_cers else None

    summary = {
        "n_questions": n,
        "avg_timing": avg_timing,
        "avg_first_audio": avg_first_audio,
        "mean_roundtrip_cer": mean_cer,
        "question_synth_times": [round(t, 3) for t in synth_t],
        "engine_config": cfg.to_dict(),
        "gpu": False,
    }
    report = {"summary": summary, "runs": results}

    out_path = Path("audit/live_host/REPORT.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _write_report(out_path, report)
    print(f"报告已写入 {out_path}")
    return 0


def _write_report(path: Path, report: dict) -> None:
    s = report["summary"]
    lines = []
    lines.append("# Hevi Live Host — E2E 实测报告\n")
    lines.append("> 全部为真实测量值（CPU 降级，无 GPU）。环境见 engine_config。\n")
    lines.append("## 汇总\n")
    lines.append(f"- 提问数：{s['n_questions']}")
    lines.append(f"- 平均首音频延迟：{s['avg_first_audio']} s（目标 <2.5s，CPU 降级下超出）")
    lines.append(f"- 平均各阶段耗时（秒）：`{s['avg_timing']}`")
    lines.append(f"- TTS 输出往返 CER（合成→再转写）：{s['mean_roundtrip_cer']}")
    lines.append(f"- 提问合成耗时（Piper）：{s['question_synth_times']} s")
    lines.append(f"- GPU 可用：{s['gpu']}\n")
    lines.append("## 逐轮明细\n")
    for r in report["runs"]:
        lines.append(f"### 第 {r['index']} 轮\n")
        lines.append(f"- 提问文本：`{r['question_text']}`")
        lines.append(f"- STT 转写：`{r['stt_transcript']}`")
        lines.append(f"- 回复：`{r['reply_text']}`")
        lines.append(f"- 句数：{r['n_utterances']}")
        lines.append(f"- 各阶段耗时：{r['timing']}")
        lines.append(f"- 首音频：{r['first_audio']} s")
        lines.append(f"- 逐句 CER：{r['utt_cer']}（均值 {r['utt_cer_mean']}）")
        lines.append("")
    lines.append("## 引擎配置\n")
    lines.append(
        "```json\n" + json.dumps(s["engine_config"], ensure_ascii=False, indent=2) + "\n```\n"
    )
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
