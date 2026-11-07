"""标题卡短片：Pillow 文字层 + Motion Prompt 标题动效（ffmpeg 近似）+ 可选画面质感，CPU 合成。

动效词汇来自 showheyohtaki/motion-prompt（MIT License (c) 2026 Shohei Ohtaki）；ffmpeg 表达式为 hevi 自写近似。
node-canvas 逐帧渲染不做（ubuntu26 无 node/canvas，不装大依赖）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

from hevi.avcraft.obase.media import ffmpeg_bin
from hevi.avcraft.obase.text_layer import render_text_png
from hevi.avcraft.oskill.motion import SUPPORTED, motion_spec_to_ffmpeg


def title_card_compose(text: str, out: str | Path, *, motion: str = "mask-reveal", w: int = 1080, h: int = 1920,
                       duration: float = 3.0, fps: int = 30, bg: str = "#111318", color: str = "#FFFFFF",
                       fontsize: int | None = None, font: str | None = None, start: float = 0.3,
                       strength: float = 1.0, y_frac: float = 0.45, looks: list[str] | tuple = ("vignette",),
                       fade_out: float = 0.4, crf: int = 23, workdir: str | Path | None = None) -> dict:
    """生成标题卡 mp4。motion ∈ 标题类（pop-in/mask-reveal/typewriter/fade-in 或其 id）；looks 为 vf 类（vignette/film-grain/black-and-white…）。

    返回 {out, motion, looks, filter_complex, credits, w, h, duration}。
    """
    spec = motion_spec_to_ffmpeg(motion, duration=duration, w=w, h=h, fps=fps, start=start, strength=strength,
                                 y_frac=y_frac)
    if spec["kind"] != "title":
        raise ValueError(f"{motion} is not a title motion; title ones: "
                         f"{[k for k, v in SUPPORTED.items() if v[0] == 'title']}")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="titlecard_"))
    tmp.mkdir(parents=True, exist_ok=True)
    fs = fontsize or max(24, int(min(w, h) * 0.085))
    layer = render_text_png(text, tmp / "title.png", fontsize=fs, color=color, font=font)
    if layer["w"] > w:  # 太长按比例缩字
        fs = int(fs * (w * 0.92) / layer["w"])
        layer = render_text_png(text, tmp / "title.png", fontsize=fs, color=color, font=font)
    if spec["id"] == "006":
        spec = motion_spec_to_ffmpeg(motion, duration=duration, w=w, h=h, fps=fps, start=start,
                                     strength=strength, y_frac=y_frac, char_x=layer["char_x"])
    credits = [spec["credit"]]
    post = []
    for lk in looks or ():
        ls = motion_spec_to_ffmpeg(lk, duration=duration, w=w, h=h, fps=fps, strength=strength)
        if ls["kind"] != "vf":
            raise ValueError(f"look {lk} is not a single-stream vf")
        post.append(ls["filter"])
        credits.append(ls["credit"])
    if fade_out:
        post.append(f"fade=t=out:st={max(0.0, duration - fade_out):g}:d={fade_out:g}")
    post.append("format=yuv420p")
    fc = spec["filter"].replace("[v]", "[vt]") + ";[vt]" + ",".join(post) + "[v]"
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", f"color=c={bg.replace('#', '0x')}:s={w}x{h}:r={fps}:d={duration:g}",
           "-loop", "1", "-framerate", str(fps), "-t", f"{duration:g}", "-i", layer["path"],
           "-filter_complex", fc, "-map", "[v]", "-t", f"{duration:g}", "-r", str(fps),
           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return {"out": str(out), "motion": spec["slug"], "looks": list(looks or ()), "filter_complex": fc,
            "credits": credits, "w": w, "h": h, "duration": duration, "text_layer": layer}


def _main() -> None:
    ap = argparse.ArgumentParser(description="Motion Prompt 标题卡（CPU/ffmpeg）")
    ap.add_argument("text")
    ap.add_argument("out")
    ap.add_argument("--motion", default="mask-reveal")
    ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--dur", type=float, default=3.0)
    ap.add_argument("--looks", default="vignette")
    a = ap.parse_args()
    w, h = map(int, a.size.split("x"))
    r = title_card_compose(a.text, a.out, motion=a.motion, w=w, h=h, duration=a.dur,
                           looks=[x for x in a.looks.split(",") if x])
    r.pop("text_layer", None)
    print(json.dumps(r, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    _main()
