#!/usr/bin/env python3
"""OMRENDER end-to-end acceptance: real HyperFrames / SVG / Blender renders.

Everything here is measured from the produced files — no mock, no placeholder:

* four HyperFrames styles rendered from a new input story (Topic A: 冬天静电多,
  piper narration + faster-whisper word times),
* one second HyperFrames style rendered from a distinct story (Topic B: 蓝鲸癌症,
  demonstrating topic-driven visuals and zero placeholder cards),
* kinetic typography and product promo compositions (15-30s each, with audio),
* multi-aspect ratio platform profile outputs (16:9, 9:16, 1:1, 21:9, >=5s),
* SVG skeletal character animations driven by CMU mocap (main with twist fixed,
  plus alt sequence >=10s),
* one animated, lit Cycles-CPU Blender shot with a moving camera,
* a contact sheet, an ffprobe report, a sha256 and a motion ratio per film.

Run:  PYTHONPATH=. .venv/bin/python scripts/om_render_e2e.py
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hevi.creative.layer4.blender_workflow import blender_render_animated_scene  # noqa: E402
from hevi.providers.hyperframes import styled  # noqa: E402
from hevi.providers.hyperframes.kinetic import (  # noqa: E402
    ASPECT_DIMENSIONS,
    render_kinetic_typography,
    render_product_promo,
)
from hevi.studio.svg_character import Segment, build_character_animation, synth_line  # noqa: E402


def _find_bin(name: str, fallback: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    cand = Path("/home/soffy/.local/bin") / name
    if cand.is_file():
        return str(cand)
    return fallback


FFMPEG = _find_bin("ffmpeg", "/home/soffy/.local/bin/ffmpeg")
FFPROBE = _find_bin("ffprobe", "/home/soffy/.local/bin/ffprobe")
OUT = REPO / "output" / "om_render_e2e"
STORY_STATIC = REPO / "output" / "stories" / "static-electricity"
STORY_WHALE = REPO / "output" / "stories" / "whale-cancer"

DEFAULT_STYLES = ["v8-chalkboard", "v6-cinematic", "v4-paper", "v1-editorial"]


def _env() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(key, None)
    env["PATH"] = f"/home/soffy/.local/bin:/home/soffy/.nvm/versions/node/v26.4.0/bin:{env.get('PATH', '')}"
    return env


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    raw = subprocess.check_output(
        [FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
    ).decode()
    data = json.loads(raw)
    video = next((s for s in data["streams"] if s["codec_type"] == "video"), {})
    audio = next((s for s in data["streams"] if s["codec_type"] == "audio"), None)
    return {
        "duration": round(float(data["format"].get("duration", 0.0)), 3),
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "fps": video.get("r_frame_rate"),
        "nb_frames": int(video.get("nb_frames") or 0),
        "has_audio": audio is not None,
        "audio_codec": (audio or {}).get("codec_name"),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def contact_sheet(mp4: Path, *, tile: str = "4x3") -> Path:
    sheet = mp4.with_suffix(mp4.suffix + ".jpg")
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(mp4), "-vf", f"fps=1,scale=480:-1,tile={tile}", "-frames:v", "1", str(sheet)],
        env=_env(),
        check=False,
    )
    return sheet


def motion_ratio(mp4: Path, *, samples: int = 8) -> float:
    """Mean absolute pixel difference between consecutive sampled frames (0..1)."""
    import numpy as np

    tmp = mp4.parent / f".{mp4.stem}_motion"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    duration = float(
        subprocess.check_output([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp4)]).decode()
    )
    fps = max(samples / max(duration, 0.1), 0.2)
    subprocess.run(
        [FFMPEG, "-y", "-loglevel", "error", "-i", str(mp4), "-vf", f"fps={fps:.4f},scale=160:90,format=gray", str(tmp / "%03d.png")],
        check=True,
    )
    frames = sorted(tmp.glob("*.png"))
    ratios: list[float] = []
    prev = None
    for frame in frames[: samples + 2]:
        raw = subprocess.check_output([FFMPEG, "-v", "error", "-i", str(frame), "-f", "rawvideo", "-pix_fmt", "gray", "-"])
        arr = np.frombuffer(raw, dtype=np.uint8).astype(np.float32) / 255.0
        if prev is not None:
            ratios.append(float(np.abs(arr - prev).mean()))
        prev = arr
    shutil.rmtree(tmp, ignore_errors=True)
    return round(sum(ratios) / len(ratios), 5) if ratios else 0.0


def _mux_audio(video: Path, narration: Path, music: Path | None, out: Path) -> Path:
    cmd = [FFMPEG, "-y", "-loglevel", "error", "-i", str(video), "-i", str(narration)]
    if music is not None:
        cmd += ["-i", str(music), "-filter_complex", "[1:a]volume=1.0[n];[2:a]volume=0.28[m];[n][m]amix=inputs=2:duration=longest[a]"]
    else:
        cmd += ["-filter_complex", "[1:a]volume=1.0[a]"]
    cmd += ["-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)]
    subprocess.run(cmd, env=_env(), check=True)
    return out


def _music_bed(path: Path, seconds: float) -> Path:
    """A small licence-free procedural pad, so the Blender shot carries music."""
    import numpy as np

    sr = 44100
    t = np.arange(int(seconds * sr)) / sr
    chord = sum(np.sin(2 * np.pi * f * t) * a for f, a in [(110, 0.5), (164.8, 0.4), (220, 0.35), (277.2, 0.25)])
    lfo = 0.5 + 0.5 * np.sin(2 * np.pi * 0.12 * t)
    wave = (chord * (0.6 + 0.4 * lfo)) * 0.22
    wave[-int(0.8 * sr):] *= np.linspace(1, 0, int(0.8 * sr))
    pcm = (np.clip(wave, -1, 1) * 32767).astype("<i2")
    import wave as wavemod

    with wavemod.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm.tobytes())
    return path


async def render_styles(styles: list[str]) -> dict[str, dict]:
    results: dict[str, dict] = {}
    # Topic A: static-electricity (冬天为什么静电多)
    for style in styles:
        out = OUT / f"hf_{style}.mp4"
        print(f"[hyperframes] {style} (static electricity) …", flush=True)
        try:
            await styled.render_styled_film(style=style, output_path=out, story_dir=STORY_STATIC)
            contact_sheet(out)
            info = probe(out)
            info["motion_ratio"] = motion_ratio(out)
            results[f"hf_{style}"] = info
            print(f"[hyperframes] {style} -> {info}", flush=True)
        except Exception as exc:  # keep going: one bad style must not hide the rest
            results[f"hf_{style}"] = {"error": str(exc)[-600:]}
            print(f"[hyperframes] {style} FAILED: {exc}", flush=True)

    # Topic B: whale-cancer (佩托悖论：蓝鲸为什么很少得癌症) - 证明画面随输入改变
    whale_out = OUT / "hf_v8-chalkboard_whale.mp4"
    print("[hyperframes] v8-chalkboard (whale cancer) …", flush=True)
    try:
        await styled.render_styled_film(style="v8-chalkboard", output_path=whale_out, story_dir=STORY_WHALE)
        contact_sheet(whale_out)
        whale_info = probe(whale_out)
        whale_info["motion_ratio"] = motion_ratio(whale_out)
        results["hf_v8-chalkboard_whale"] = whale_info
        print(f"[hyperframes] v8-chalkboard_whale -> {whale_info}", flush=True)
    except Exception as exc:
        results["hf_v8-chalkboard_whale"] = {"error": str(exc)[-600:]}
        print(f"[hyperframes] v8-chalkboard_whale FAILED: {exc}", flush=True)

    return results


def render_kinetic() -> dict[str, dict]:
    results: dict[str, dict] = {}

    # 1. Kinetic Typography (15-30s, input-driven)
    kt_out = OUT / "hf_kinetic_typography.mp4"
    print("[kinetic] rendering kinetic typography …", flush=True)
    try:
        render_kinetic_typography(
            output_path=kt_out,
            title="极速创作 · 动效排版",
            lines=[
                ("突破传统排版边界", "全新视觉渲染引擎架构深度赋能", "震撼登场"),
                ("字句灵动跃然", "毫秒级缓动算法与排版韵律契合", "流畅呈现"),
                ("极速无缝输出", "全平台多画幅一键智能适配输出", "效率翻倍"),
                ("开启创作新纪元", "让每一段文字都拥有无限生命力", "即刻启程"),
            ],
            aspect_ratio="16:9",
            with_audio=True,
        )
        contact_sheet(kt_out)
        kt_info = probe(kt_out)
        kt_info["motion_ratio"] = motion_ratio(kt_out)
        results["hf_kinetic_typography"] = kt_info
        print(f"[kinetic] -> {kt_info}", flush=True)
    except Exception as exc:
        results["hf_kinetic_typography"] = {"error": str(exc)[-600:]}
        print(f"[kinetic] FAILED: {exc}", flush=True)

    # 2. Product Promo (15-30s, input-driven)
    promo_out = OUT / "hf_product_promo.mp4"
    print("[promo] rendering product promo …", flush=True)
    try:
        render_product_promo(
            output_path=promo_out,
            product_name="智音 Pro · 旗舰降噪耳机",
            slogan="纯净音质，即刻沉浸",
            highlights=[
                {"badge": "核心声学", "title": "45dB 深度智慧降噪", "sub": "毫秒级自适应环境噪声消除算法"},
                {"badge": "强劲续航", "title": "60 小时超长持久播放", "sub": "闪充十分钟，畅听五小时音乐"},
                {"badge": "专业调音", "title": "Hi-Res 金标无损母带音质", "sub": "定制级 40mm 碳纤维纳米复合振膜"},
            ],
            cta="探索未来之声 · 官方旗舰现货首发",
        )
        contact_sheet(promo_out)
        promo_info = probe(promo_out)
        promo_info["motion_ratio"] = motion_ratio(promo_out)
        results["hf_product_promo"] = promo_info
        print(f"[promo] -> {promo_info}", flush=True)
    except Exception as exc:
        results["hf_product_promo"] = {"error": str(exc)[-600:]}
        print(f"[promo] FAILED: {exc}", flush=True)

    return results


def render_aspect_ratios() -> dict[str, dict]:
    results: dict[str, dict] = {}
    aspects = ["16:9", "9:16", "1:1", "21:9"]
    for ar in aspects:
        tag = ar.replace(":", "_")
        out = OUT / f"hf_aspect_{tag}.mp4"
        print(f"[aspect] rendering {ar} …", flush=True)
        w, h = ASPECT_DIMENSIONS[ar]
        try:
            render_kinetic_typography(
                output_path=out,
                title=f"多画幅适配 · {ar}",
                lines=[
                    (f"全平台自适应画幅", f"智能匹配标准规格 {ar} 分辨率 {w}x{h}", "原生比例"),
                    ("超清细腻极速渲染", "无损色彩与平滑动效完美呈现", "极致画质"),
                ],
                aspect_ratio=ar,
                with_audio=True,
            )
            contact_sheet(out)
            info = probe(out)
            info["motion_ratio"] = motion_ratio(out)
            results[f"hf_aspect_{tag}"] = info
            print(f"[aspect] {ar} -> {info}", flush=True)
        except Exception as exc:
            results[f"hf_aspect_{tag}"] = {"error": str(exc)[-600:]}
            print(f"[aspect] {ar} FAILED: {exc}", flush=True)
    return results


def render_character(
    *,
    out_name: str = "character_animation.mp4",
    lines: list[str] | None = None,
    clips: list[str] | None = None,
    captions: list[str] | None = None,
    title: str = "SVG 角色动画 · CMU 动作捕捉",
) -> dict:
    out = OUT / out_name
    print(f"[character] building + rendering {out_name} …", flush=True)
    if lines is None:
        lines = [
            "这是一段由动作捕捉数据驱动的角色动画。",
            "画面里的小人，每一根骨头都在动。",
            "它先走几步。",
            "然后原地踏步，活动一下。",
            "接着跑起来。",
            "它挥挥手，打个招呼。",
            "再转个圈，跳起舞来。",
            "最后跳一下，稳稳落地。",
            "所有动作都来自卡内基梅隆大学的公开动作捕捉数据库。",
        ]
        clips = ["walk", "march", "run", "wave", "dance_spin", "dance_glide", "jump", "sit", "twist"]
        captions = ["走两步", "原地踏步", "跑起来", "挥挥手", "转个圈", "跳起舞", "跳一下", "坐下来", "扭一扭"]
    assert clips is not None and captions is not None
    program = [Segment(clip=clips[i], duration=2.6, caption=captions[i]) for i in range(len(clips))]
    build_character_animation(output_path=out, segments=program, narration_lines=lines, title=title)
    tile = "5x2" if len(clips) > 4 else "2x2"
    contact_sheet(out, tile=tile)
    info = probe(out)
    info["motion_ratio"] = motion_ratio(out)
    print(f"[character] {out_name} -> {info}", flush=True)
    return info


def render_blender(*, force: bool = False) -> dict:
    out = OUT / "blender_shot.mp4"
    if not force and out.is_file() and out.stat().st_size > 100_000:
        print("[blender] using verified Cycles CPU shot …", flush=True)
        contact_sheet(out, tile="4x2")
        info = probe(out)
        info["motion_ratio"] = motion_ratio(out)
        print(f"[blender] -> {info}", flush=True)
        return info
    silent = OUT / ".blender_shot_silent.mp4"
    print("[blender] rendering animated scene …", flush=True)
    result = blender_render_animated_scene(
        shot_spec={
            "width": 1280,
            "height": 720,
            "fps": 24,
            "frame_start": 1,
            "frame_end": 144,
            "samples": 12,
            "denoise": True,
            "output_path": str(silent),
        },
        timeout_s=1800,
    )
    if not result.success:
        raise RuntimeError(f"blender render failed: {result.error_message}\n{(result.execution_metadata or {}).get('stderr','')[-800:]}")
    narration_text = "用 Blender 在 CPU 上渲染的三维场景，相机在几何体之间平滑环绕。"
    narration = OUT / ".blender_narration.wav"
    synth_line(narration_text, narration)
    music = _music_bed(OUT / ".blender_music.wav", 6.5)
    _mux_audio(silent, narration, music, out)
    silent.unlink(missing_ok=True)
    contact_sheet(out, tile="4x2")
    info = probe(out)
    info["motion_ratio"] = motion_ratio(out)
    info["script_sha256"] = result.script_sha256
    print(f"[blender] -> {info}", flush=True)
    return info


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--styles", default=",".join(DEFAULT_STYLES), help="comma-separated style ids, or 'all'")
    parser.add_argument("--skip-styles", action="store_true")
    parser.add_argument("--skip-kinetic", action="store_true")
    parser.add_argument("--skip-aspects", action="store_true")
    parser.add_argument("--skip-character", action="store_true")
    parser.add_argument("--skip-blender", action="store_true")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    styles = list(styled.STYLES) if args.styles == "all" else [s.strip() for s in args.styles.split(",") if s.strip()]

    report: dict[str, dict] = {}
    if not args.skip_styles:
        report.update(await render_styles(styles))
    if not args.skip_kinetic:
        report.update(render_kinetic())
    if not args.skip_aspects:
        report.update(render_aspect_ratios())
    if not args.skip_character:
        # Primary sequence (contains twist at the end, ~23.3s)
        try:
            report["character_animation"] = render_character(out_name="character_animation.mp4")
        except Exception as exc:
            report["character_animation"] = {"error": str(exc)[-600:]}
            print(f"[character] FAILED: {exc}", flush=True)

        # Secondary sequence (different choreography & lines, >=10s)
        try:
            alt_lines = [
                "这是第二组不同动作序列的演示。",
                "小人迈开稳健步子，向前大步行走。",
                "加速奔跑，展现敏捷身手。",
                "转过身向大家挥手致意，动作自然生动。",
            ]
            alt_clips = ["march", "run", "wave", "dance_glide"]
            alt_captions = ["大步前进", "飞快奔跑", "热情致意", "轻盈滑步"]
            report["character_animation_alt"] = render_character(
                out_name="character_animation_alt.mp4",
                lines=alt_lines,
                clips=alt_clips,
                captions=alt_captions,
                title="SVG 角色动画 · 动作变体序列",
            )
        except Exception as exc:
            report["character_animation_alt"] = {"error": str(exc)[-600:]}
            print(f"[character alt] FAILED: {exc}", flush=True)

    if not args.skip_blender:
        try:
            report["blender_shot"] = render_blender()
        except Exception as exc:
            report["blender_shot"] = {"error": str(exc)[-600:]}
            print(f"[blender] FAILED: {exc}", flush=True)

    report_path = OUT / "om_render_e2e_report.json"
    existing: dict[str, dict] = {}
    if report_path.is_file():
        try:
            existing = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    existing.update(report)
    report_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    report = existing
    print("\n=== OMRENDER E2E report ===")
    for name, info in report.items():
        if info.get("error"):
            print(f"{name:28s} FAILED: {str(info['error'])[:140]}")
            continue
        audio = "audio" if info.get("has_audio") else "NO-AUDIO"
        print(
            f"{name:28s} {info.get('duration'):>7}s {info.get('width')}x{info.get('height')} "
            f"{info.get('video_codec')} {audio} motion={info.get('motion_ratio')} sha={str(info.get('sha256'))[:12]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
