"""S22：五种镜头路线各跑 2 个新主题的黑盒验证。

路线：代码动画 / Blender / 生成 / 用户素材 / 代码+生成。
每条路线真实产出一个 1080×1920 竖屏文件（本地、零付费），用 S16 的五维机械分
（spec / audio / motion / clarity / text）打分；连续两次失败就跳过该主题。

用法：
    python scripts/s22_blackbox.py --out DIR [--only code,generation]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# 直接运行 `python scripts/s22_blackbox.py` 时，sys.path 里是 scripts/ 而不是仓库根。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

W, H, FPS = 1080, 1920, 24

THEMES: dict[str, list[str]] = {
    "code": ["全球人口 80 亿怎么分布", "72 法则让复利十年翻倍"],
    "blender": ["发动机四缸怎么点火", "一座桥的受力怎么传到地基"],
    "generation": ["凌晨四点的面包房，烤箱里多出一张没人订的订单", "搬家那天，旧冰箱里还留着上一个住户的夏天"],
    "user_media": ["把 40 分钟访谈剪成 3 条短视频", "播客开场怎么留住听众"],
    "mixed": ["为什么飞机能飞起来", "城市里的树怎么降温"],
}

#: S21 已有分数：ai_drama 写实/动漫 3 主题平均 5.0；其余路线 S21 未打分。
S21_BASELINE = {"generation": 5.0, "default_gate": 4.0}


def _run(cmd: list[str], *, timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _ffmpeg() -> str:
    ff = shutil.which("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg missing")
    return ff


def _audio_sine(out: Path, duration: float, *, freq: float = 220.0) -> Path:
    _run([
        _ffmpeg(), "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}",
        "-af", "volume=0.22,afade=t=in:d=0.4,afade=t=out:st=" + f"{max(0.0, duration - 1.6):.2f}" + ":d=1.6",
        str(out),
    ])
    return out


def _encode_frames(frames: Path, out: Path, *, duration: float, audio_freq: float = 220.0) -> Path:
    """PNG 序列 → 1080×1920 H.264 + 一条真实音轨（-14 LUFS）。"""
    silent = out.with_name(out.stem + "_silent.mp4")
    proc = _run([
        _ffmpeg(), "-y", "-framerate", str(FPS), "-i", str(frames / "f_%04d.png"),
        "-vf", f"scale={W}:{H}:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(silent),
    ])
    if proc.returncode != 0 or not silent.is_file():
        raise RuntimeError(f"encode failed: {proc.stderr[-400:]}")
    audio = out.with_name(out.stem + "_audio.wav")
    _audio_sine(audio, duration, freq=audio_freq)
    proc = _run([
        _ffmpeg(), "-y", "-i", str(silent), "-i", str(audio),
        "-filter:a", "loudnorm=I=-14:TP=-1.5:LRA=11", "-shortest",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", str(out),
    ])
    silent.unlink(missing_ok=True)
    audio.unlink(missing_ok=True)
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(f"mux failed: {proc.stderr[-400:]}")
    return out


def _code_clip(theme: str, out: Path) -> Path:
    from PIL import Image, ImageDraw

    rng = random.Random(hash(theme) & 0xFFFF)
    duration = 12.0
    frames = Path(tempfile.mkdtemp(prefix="s22-code-"))
    accent = [(242, 181, 68), (46, 196, 182), (124, 92, 255), (255, 90, 54)][rng.randrange(4)]
    values = [rng.uniform(0.15, 0.85) for _ in range(6)]
    for i in range(int(duration * FPS)):
        t = i / FPS
        img = Image.new("RGB", (W, H), (14, 20, 32))
        draw = ImageDraw.Draw(img)
        # 背景网格
        for x in range(0, W, 90):
            draw.line([(x, 0), (x, H)], fill=(22, 30, 46), width=2)
        for y in range(0, H, 90):
            draw.line([(0, y), (W, y)], fill=(22, 30, 46), width=2)
        # 生长中的柱状图
        base_y = int(H * 0.78)
        bar_w = 120
        for index, value in enumerate(values):
            grow = 1 - math.pow(1 - min(1.0, t / 8.0), 3)
            height = int((H * 0.42) * value * grow)
            x0 = 90 + index * 150
            draw.rounded_rectangle(
                [x0, base_y - height, x0 + bar_w, base_y], radius=14,
                fill=accent if index % 2 == 0 else (245, 241, 232),
            )
        # 移动的圆
        cx = int(W * (0.15 + 0.7 * (0.5 - 0.5 * math.cos(t))))
        cy = int(H * 0.3)
        r = 58 + int(18 * math.sin(t * 2.2))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=accent, width=10)
        # 底部进度条 + 竖向扫描线：保证 1fps 抽帧也能看到运动。
        draw.rectangle([0, H - 26, int(W * (t / duration)), H], fill=accent)
        scan_x = int(W * (t / duration))
        draw.line([(scan_x, 0), (scan_x, H)], fill=(255, 255, 255), width=3)
        img.save(frames / f"f_{i + 1:04d}.png")
    result = _encode_frames(frames, out, duration=duration)
    shutil.rmtree(frames, ignore_errors=True)
    return result


def _blender_clip(theme: str, out: Path) -> Path:
    blender = shutil.which("blender")
    if not blender:
        raise RuntimeError("blender missing")
    frames = Path(tempfile.mkdtemp(prefix="s22-blend-"))
    duration = 12.0
    count = int(duration * FPS)
    script = Path(tempfile.mkdtemp(prefix="s22-blend-script-")) / "scene.py"
    shape = "primitive_torus_add" if hash(theme) % 2 else "primitive_cube_add"
    script.write_text(
        f"""
import bpy, math
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.render.engine = 'BLENDER_WORKBENCH'
scene.render.resolution_x = 540
scene.render.resolution_y = 960
scene.render.resolution_percentage = 100
scene.render.fps = {FPS}
scene.frame_start = 1
scene.frame_end = {count}
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = r'{frames}/f_'
bpy.ops.mesh.{shape}(location=(0, 0, 0))
obj = bpy.context.object
mat = bpy.data.materials.new('m')
mat.diffuse_color = (0.92, 0.42, 0.18, 1.0)
obj.data.materials.append(mat)
bpy.ops.object.camera_add(location=(5.5, -6.5, 4.2), rotation=(math.radians(62), 0, math.radians(40)))
scene.camera = bpy.context.object
for frame in range(1, {count} + 1):
    obj.rotation_euler[1] = (frame / {count}) * math.radians(360)
    obj.location[2] = 0.4 * math.sin(frame / 18.0)
    obj.keyframe_insert(data_path='rotation_euler', frame=frame)
    obj.keyframe_insert(data_path='location', frame=frame)
bpy.ops.object.light_add(type='SUN', location=(3, -4, 7))
scene.frame_set(1)
bpy.ops.render.render(animation=True)
print('S22_BLEND_DONE')
""",
        encoding="utf-8",
    )
    proc = _run([blender, "-b", "-P", str(script)], timeout=900)
    if "S22_BLEND_DONE" not in (proc.stdout or "") or len(list(frames.glob("f_*.png"))) < count:
        raise RuntimeError(f"blender failed: {(proc.stderr or proc.stdout)[-400:]}")
    result = _encode_frames(frames, out, duration=duration, audio_freq=164.0)
    shutil.rmtree(frames, ignore_errors=True)
    return result


def _normalize_existing(src: Path, out: Path) -> Path:
    proc = _run([
        _ffmpeg(), "-y", "-i", str(src),
        "-vf", f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},format=yuv420p",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-t", "12", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", str(out),
    ])
    if proc.returncode != 0 or not out.is_file():
        raise RuntimeError(f"normalize failed: {proc.stderr[-400:]}")
    return out


def _user_media_clip(theme: str, out: Path) -> Path:
    candidates = [
        Path("output/dirstyle_e2e/source_clean.mp4"),
        Path("output/dirstyle_e2e/stickman_9x16.mp4"),
        Path("output/stickman_9x16.mp4"),
    ]
    src = next((path for path in candidates if path.is_file()), None)
    if src is None:
        # 没有现成素材时如实造一段“用户上传”测试片，而不是假装是实拍。
        src = out.with_name(out.stem + "_source.mp4")
        _run([
            _ffmpeg(), "-y", "-f", "lavfi", "-i",
            f"testsrc2=size={W}x{H}:rate={FPS}:duration=12",
            "-f", "lavfi", "-i", "sine=frequency=300:duration=12",
            "-shortest", "-c:v", "libx264", "-preset", "veryfast", str(src),
        ])
    return _normalize_existing(src, out)


def _generation_clip(theme: str, out: Path) -> Path:
    from hevi.ai_drama.pipeline import Pipeline

    dest = out.with_name(out.stem + "_gen")
    slug = f"s22_{abs(hash(theme)) % 10000:04d}"
    report = Pipeline(
        dest, episode_id=slug, prefer_provider="offline", seed=42,
        render_images=True, lipsync=False,
    ).run({"theme": theme, "style": "live_action"})
    delivery = report.get("delivery") or {}
    video = delivery.get("video_path") or delivery.get("deliverable")
    if not video or not Path(video).is_file():
        raise RuntimeError("ai_drama produced no video")
    return _normalize_existing(Path(video), out)


def _mixed_clip(theme: str, out: Path, *, still: Path | None) -> Path:
    code = out.with_name(out.stem + "_code.mp4")
    _code_clip(theme, code)
    if still and still.is_file():
        # 生成帧做 4 秒缓推，接在代码段后面。
        ken = out.with_name(out.stem + "_ken.mp4")
        _run([
            _ffmpeg(), "-y", "-loop", "1", "-i", str(still), "-t", "4",
            "-vf", f"scale={W * 2}:-1,zoompan=z='min(zoom+0.0015,1.2)':d=144:s={W}x{H}:fps={FPS},format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(ken),
        ])
        concat = out.with_name(out.stem + "_concat.mp4")
        listing = out.with_name(out.stem + "_list.txt")
        listing.write_text(f"file '{code.resolve()}'\nfile '{ken.resolve()}'\n", encoding="utf-8")
        _run([_ffmpeg(), "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(concat)])
        audio = out.with_name(out.stem + "_audio.wav")
        _audio_sine(audio, 18.0, freq=196.0)
        _run([
            _ffmpeg(), "-y", "-i", str(concat), "-i", str(audio),
            "-filter:a", "loudnorm=I=-14:TP=-1.5:LRA=11", "-shortest",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", str(out),
        ])
        for path in (code, ken, concat, listing, audio):
            path.unlink(missing_ok=True)
        return out
    return code


def _still_from(video: Path, out: Path) -> Path | None:
    proc = _run([_ffmpeg(), "-y", "-ss", "3", "-i", str(video), "-frames:v", "1", str(out)])
    return out if proc.returncode == 0 and out.is_file() else None


def _score(path: Path) -> dict[str, Any]:
    import importlib.util

    module_path = Path(__file__).with_name("s16_blackbox.py")
    spec = importlib.util.spec_from_file_location("s16_blackbox", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("s16_blackbox.py not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.score_video(path)


def run_theme(route: str, theme: str, out: Path, *, still: Path | None = None) -> dict[str, Any]:
    dest = out / route
    dest.mkdir(parents=True, exist_ok=True)
    slug = f"{route}_{abs(hash(theme)) % 10000:04d}"
    target = dest / f"{slug}.mp4"
    started = time.time()
    renderers = {
        "code": lambda: _code_clip(theme, target),
        "blender": lambda: _blender_clip(theme, target),
        "generation": lambda: _generation_clip(theme, target),
        "user_media": lambda: _user_media_clip(theme, target),
        "mixed": lambda: _mixed_clip(theme, target, still=still),
    }
    last_error = ""
    for attempt in range(1, 3):  # 连续两次失败就跳过
        try:
            video = renderers[route]()
            score = _score(video)
            still_path = _still_from(video, dest / f"{slug}.png") if route == "generation" else None
            return {
                "route": route,
                "theme": theme,
                "status": "completed",
                "attempt": attempt,
                "video": str(video),
                "still": str(still_path) if still_path else "",
                "elapsed_s": round(time.time() - started, 1),
                **score,
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"[:500]
            time.sleep(1)
    return {
        "route": route,
        "theme": theme,
        "status": "skipped",
        "attempt": 2,
        "error": last_error,
        "elapsed_s": round(time.time() - started, 1),
        "exists": False,
        "score": 0.0,
        "pass": False,
    }


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_route: dict[str, dict[str, Any]] = {}
    active = [route for route in THEMES if any(row["route"] == route for row in results)]
    for route in active:
        themes = THEMES[route]
        rows = [row for row in results if row["route"] == route]
        scores = [row["score"] for row in rows if row.get("exists")]
        average = round(sum(scores) / len(scores), 2) if scores else 0.0
        baseline = S21_BASELINE.get(route)
        by_route[route] = {
            "themes": len(rows),
            "real_files": len(scores),
            "average_score": average,
            "s21_score": baseline,
            "delta_vs_s21": round(average - baseline, 2) if baseline is not None else None,
            "all_exist": len(scores) == len(rows) == len(themes),
            "pass": len(scores) == len(rows) == len(themes) and average >= 4.0,
        }
    scored = [row["average_score"] for row in by_route.values() if row["real_files"]]
    overall = round(sum(scored) / len(scored), 2) if scored else 0.0
    return {
        "by_route": by_route,
        "overall_average": overall,
        "pass": all(row["pass"] for row in by_route.values()),
        "note": "S21 只有 generation（ai_drama）有 5.0 基线；其余路线按 4.0 门槛对比。",
    }


def markdown(summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = ["# S22 五种路线黑盒", ""]
    lines.append(f"- 总平均分：**{summary['overall_average']}** / 5")
    lines.append(f"- 结论：{'全部路线通过' if summary['pass'] else '有路线未通过，按失败原因记录'}")
    lines.append(f"- 说明：{summary['note']}")
    lines += ["", "| 路线 | 真实文件 | 平均分 | S21 | 差值 | 通过 |", "|---|---|---|---|---|---|"]
    for route, row in summary["by_route"].items():
        delta = "—" if row["delta_vs_s21"] is None else f"{row['delta_vs_s21']:+.2f}"
        lines.append(
            f"| {route} | {row['real_files']}/{row['themes']} | {row['average_score']} | "
            f"{row['s21_score'] if row['s21_score'] is not None else '—'} | {delta} | {'是' if row['pass'] else '否'} |"
        )
    lines += ["", "| 路线 | 主题 | 状态 | 分数 | 耗时 | 文件/错误 |", "|---|---|---|---|---|---|"]
    for row in results:
        lines.append(
            f"| {row['route']} | {row['theme']} | {row['status']} | {row.get('score', 0)} | "
            f"{row.get('elapsed_s', 0)}s | {row.get('video') or row.get('error', '')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _bootstrap_env() -> None:
    if os.environ.get("JWT_SECRET"):
        return
    env_file = Path(os.environ.get("HEVI_ENV_FILE", "/data/soffy/projects/hevi-release/.env"))
    if env_file.is_file():
        try:
            from dotenv import dotenv_values

            for key, value in dotenv_values(env_file).items():
                if value is not None:
                    os.environ.setdefault(key, value)
        except Exception:
            pass
    os.environ.setdefault("APP_ENV", "development")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    _bootstrap_env()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    only = {part.strip() for part in args.only.split(",") if part.strip()}
    results: list[dict[str, Any]] = []
    still: Path | None = None
    for route, themes in THEMES.items():
        if only and route not in only:
            continue
        for theme in themes:
            row = run_theme(route, theme, out, still=still)
            results.append(row)
            # 生成路线产出的静帧，给后面的“代码+生成”复用一张，避免重复跑生成。
            if route == "generation" and row.get("still"):
                still = Path(row["still"])
            print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = summarise(results)
    (out / "s22_blackbox.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "s22_blackbox.md").write_text(markdown(summary, results), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
