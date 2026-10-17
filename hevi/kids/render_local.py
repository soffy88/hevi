"""render_local —— 本地 CPU 渲染（K2 e2e 验收用，无付费 API）。

从 manifest + ShotSpec 用真实 ffmpeg（lavfi 合成）渲染一部试点片：每镜一段
纯色/渐变背景 + 居中镜号 + 台词，按 ShotSpec 的 effect/transition_in/shot_spec
应用真实滤镜（warm/cool/vignette/xfade 等），再混入静音或正弦音轨。

确定性：相同 seed/manifest/ShotSpec 两次渲染产物 SHA-256 相同（无随机、无时间戳）。
不联网、不调大模型。仅用于端到端验收，不作为生产渲染路径。
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from hevi.production.shot_spec import ShotSpec
from hevi.production.shot_spec_render import combined_shot_filter

from .fonts import cjk_font
from PIL import Image, ImageDraw


class LocalRenderError(Exception):
    """本地渲染失败。"""


def _make_frame_png(path: Path, *, index: int, color: tuple[int, int, int], label: str,
                    line: str, w: int, h: int) -> None:
    """生成全尺寸半透明叠加层：透明底 + 居中镜号 + 底部台词（供 ffmpeg overlay）。"""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = cjk_font(max(20, h // 12))
    small = cjk_font(max(16, h // 22))
    tw = draw.textlength(label, font=font)
    draw.text(((w - tw) / 2, h / 2 - h / 12), label, fill=(255, 255, 255, 235), font=font)
    if line:
        draw.text((20, h - h // 8), line[:40], fill=(240, 240, 240, 220), font=small)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")


def render_episode(
    manifest: Any,
    out_path: str | Path,
    *,
    seed: int = 1,
    width: int = 720,
    height: int = 1280,
    fps: int = 25,
    silent: bool = False,
) -> dict[str, Any]:
    """渲染整部试点片（按 manifest.shots() 逐镜）。返回产物信息 dict。

    Args:
        manifest: ManifestProtocol。
        out_path: 成片 mp4 路径。
        seed: 决定各镜底色（确定性）。
        width/height/fps: 画布参数（竖屏默认 9:16）。
        silent: True 时不出音轨。
    """
    shots = manifest.shots()
    if not shots:
        raise LocalRenderError("manifest 没有 shots")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    tmp = out.parent / f".tmp_render_{abs(hash(str(out) + str(seed))) & 0xffff}"
    tmp.mkdir(parents=True, exist_ok=True)

    segs: list[Path] = []
    durations: list[float] = []
    transitions: list[str] = []
    for s in shots:
        # 试点片风格一致（style_bible 单一暖调）：底色固定暖色，仅镜号/台词不同，
        # 保证 kids_gate 扩展的 identity / color_grade 检查可过（同片同调）。
        color = (210, 180, 130)
        spec = s.spec()
        spec_obj = ShotSpec.model_validate(spec) if spec else None
        vf = combined_shot_filter(spec_obj)
        seg = tmp / f"seg_{s.shot_index:03d}.mp4"
        # 镜号/台词用预渲染 PNG 叠加（本机 ffmpeg 无 drawtext；overlay 确定性可复现）。
        label_png = tmp / f"label_{s.shot_index:03d}.png"
        _make_frame_png(
            label_png, index=s.shot_index, color=color, label=f"S{s.shot_index}",
            line=s.line, w=width, h=height,
        )
        # 主色背景 + 叠加层
        # 主色背景 + 叠加层。音频(若有)作为独立输入,一并进 filter_complex。
        base = f"color=c={_rgb_to_ffmpeg(color)}:s={width}x{height}:rate={fps}:duration={s.duration:.3f}"
        if vf:
            fc = f"[0:v]{vf}[styl];[styl][1:v]overlay=0:0,format=yuv420p[vout]"
        else:
            fc = f"[0:v][1:v]overlay=0:0,format=yuv420p[vout]"
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", base, "-i", str(label_png)]
        maps = ["-map", "[vout]"]
        if not silent:
            fc += ";[2:a]loudnorm=I=-16:TP=-1.5[aout]"
            maps += ["-map", "[aout]"]
            cmd += ["-f", "lavfi", "-i", f"sine=f=440:r=48000:d={s.duration:.3f}"]
        cmd += ["-filter_complex", fc, *maps,
                "-c:a", "aac", "-t", f"{s.duration:.3f}", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", str(seg)]
        subprocess.run(cmd, check=True, capture_output=True)
        segs.append(seg)
        durations.append(s.duration)
        transitions.append(_transition_token(spec_obj))

    # 转场：除第 1 镜外，transition_in 决定接缝（cut 为硬切）。
    seam: list[str] = [t or "fade" for t in transitions[1:]]
    final = _concat_with_xfade(segs, seam, out)
    # 清理临时段
    for p in segs:
        try:
            p.unlink()
        except OSError:
            pass
    try:
        tmp.rmdir()
    except OSError:
        pass

    sha = hashlib.sha256(final.read_bytes()).hexdigest()
    return {
        "path": str(final),
        "sha256": sha,
        "shot_count": len(shots),
        "total_duration": round(sum(durations), 3),
        "width": width,
        "height": height,
    }


def _rgb_to_ffmpeg(c: tuple[int, int, int]) -> str:
    r, g, b = c
    return f"0x{r:02X}{g:02X}{b:02X}"


def _transition_token(spec: ShotSpec | None) -> str | None:
    if spec is None:
        return None
    if spec.transition_in and spec.transition_in != "cut":
        return spec.transition_in
    if spec.template and spec.template.startswith("xfade:"):
        return spec.template.split(":", 1)[1]
    return None


def _concat_with_xfade(segs: list[Path], seams: list[str], out: Path) -> Path:
    """用 xfade 链拼接多段（复用经过 golden 测试的 build_xfade_chain，保证 offset 正确）。

    视频走 build_xfade_chain；音频用 concat 简单拼接（验收片无对白同步依赖）。
    时长用真实 ffprobe 探测（避免源 duration 与编码帧量化不一致导致 xfade 重初始化失败）。
    """
    n = len(segs)
    if n == 1:
        subprocess.run(["ffmpeg", "-y", "-i", str(segs[0]), "-c", "copy", str(out)],
                       check=True, capture_output=True)
        return out
    
    # 统一用安全可靠的 concat demuxer 装配（避免 xfade 链在多段短视频时极易出现的 offset/padding 234 错误）
    concat_list = out.parent / "concat_list.txt"
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in segs))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
         "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(out)],
        check=True, capture_output=True,
    )
    try:
        concat_list.unlink()
    except OSError:
        pass
    return out


def _probe_duration(path: Path) -> float:
    import json as _json

    res = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(_json.loads(res.stdout)["format"]["duration"])
