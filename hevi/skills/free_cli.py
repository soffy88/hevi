"""hevi-free CLI —— 零成本动画视频通道(纯视觉真动画,不念文案)。

用法:
    uv run python -m hevi.skills.free_cli --text "一段中文内容..." --title "标题"
    uv run python -m hevi.skills.free_cli --json plan.json --out-dir out/
    uv run python -m hevi.skills.free_cli --text "..." --kind bar --w 1920 --h 1080

零成本: 无 LLM 云调用(默认)、无 TTS、无云视频 API、无素材下载 ——
内容 → 确定性分镜 → 每镜自包含动画 HTML → Chromium 录屏 → ffmpeg 拼接。
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from hevi.assembly.freevideo.templates import FRAME_KINDS
from hevi.assembly.freevideo.workflow import FreeVideoConfig, FreeVideoInput, free_video_workflow


def _llm_rewrite(text: str, title: str) -> str:
    """本地 ollama(qwen3-8b)把素材改写为口语化视频旁白(零成本,不走云)。

    失败时原样返回 —— 零成本通道不欠任何 API,LLM 是可选增强。
    """
    import json as _json
    import urllib.request

    prompt = (
        "你是短视频旁白编辑。把下面这段素材改写成口语化、有节奏、"
        "适合逐句分镜成视频的旁白(4-8 句,每句独立成段,句号结尾,不要标题)。\n\n"
        f"标题:{title}\n素材:{text}"
    )
    body = _json.dumps(
        {"model": "qwen3-8b", "prompt": prompt, "stream": False, "options": {"temperature": 0.7}}
    ).encode("utf-8")
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/generate", data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            out = _json.loads(resp.read().decode("utf-8")).get("response", "")
        # 去掉 qwen3 的 <think> 思考块与 markdown 痕迹,其余行全部采用。
        out = re.sub(r"<think>.*?</think>", "", out, flags=re.S)
        lines = [
            ln.strip() for ln in out.splitlines()
            if ln.strip() and not ln.strip().startswith(("#", "-", "*"))
        ]
        cleaned = "\n".join(lines)
        return cleaned if len(cleaned) >= len(text) * 0.3 else text
    except Exception as exc:
        print(f"free: 本地 LLM 不可用({exc}),退回原文案", file=sys.stderr)
        return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hevi-free: 零成本程序化动画视频")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", default="", help="中文内容/故事/要点(确定性分句成镜)")
    src.add_argument("--json", dest="plans_json", default="", help="结构化分镜 JSON 文件")
    parser.add_argument("--title", default="", help="视频标题(首末镜 kicker)")
    parser.add_argument("--kind", default=None, choices=FRAME_KINDS,
                        help="指定单一动画模板;缺省自动轮换")
    parser.add_argument("--palette", default="deep", choices=["deep", "paper"])
    parser.add_argument("--mood", dest="bgm_mood", default=None,
                        choices=["calm", "bright", "epic", "tense", "warm"],
                        help="免费程序化 BGM 情绪(给定时自动合成并混入成片)")
    parser.add_argument("--bgm-bpm", type=int, default=0, help="BGM 拍速(0=用 mood 预设)")
    parser.add_argument("--bgm-dur", type=float, default=0.0, help="BGM 时长(0=随成片)")
    parser.add_argument("--voice", default=None,
                        help="免费配音音色(edge_tts):zh_male_deep/zh_female_standard/... "
                             "(见 hevi.audio.edge_tts_custom.CURATED_VOICES)")
    parser.add_argument("--narration", default="", help="显式旁白文本;缺省自动拼接各帧 body")
    parser.add_argument("--llm", action="store_true",
                        help="先用本地 ollama(qwen3-8b)改写文案为口语化旁白,再分镜(零成本)")
    parser.add_argument("--w", type=int, default=1280)
    parser.add_argument("--h", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--dur", type=float, default=4.0, help="每镜秒数")
    parser.add_argument("--out-dir", type=Path, default=Path(".hevi_free"))
    args = parser.parse_args(argv)

    config = FreeVideoConfig(
        width=args.w, height=args.h, fps=args.fps,
        frame_duration=args.dur, palette=args.palette, frame_kind=args.kind,
        bgm_mood=args.bgm_mood, bgm_bpm=args.bgm_bpm, bgm_duration_s=args.bgm_dur,
        voice=args.voice, narration=args.narration,
    )

    text = args.text
    if args.llm:
        text = _llm_rewrite(text, args.title)
        print(f"free: 本地 LLM 改写文案({len(text)} 字)")

    input_data = FreeVideoInput(
        text=text,
        title=args.title,
        plans_json=Path(args.plans_json).read_text(encoding="utf-8") if args.plans_json else None,
    )

    res = asyncio.run(free_video_workflow(config, input_data, args.out_dir))
    if res["status"] != "completed":
        print(f"free: FAILED — {res.get('error')}", file=sys.stderr)
        return 1
    print(f"free: {res['status']}  {res['frames']} 帧  {res['resolution']}")
    for p in res.get("plan", []):
        print(f"  · {p['kind']:<11} {p['title'][:24]}  {p['duration']}s" +
              (f"  broll={p.get('broll')}" if p.get('broll') else ""))
    if res.get("bgm"):
        b = res["bgm"]
        print(f"free: BGM {b['mood']} @{b['bpm']:.0f}bpm {b['beats']}拍(程序化合成,零成本)")
    print(f"free: 成片 → {res['output_path']}  (零成本: 仅 CPU 渲染)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
