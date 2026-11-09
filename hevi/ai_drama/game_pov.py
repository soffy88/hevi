"""game_pov extras: first-person prompt guard, UI overlays, dialogue box, bridge.

Fonts: Noto Sans CJK / Noto Sans Mono CJK are SIL OFL 1.1 (commercially
usable, redistributable).  SimHei / Zpix are not used because their licences
are not confirmed for commercial redistribution on this machine.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

FFMPEG = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
NOTO = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
NOTO_MONO = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_LICENSE = "Noto Sans CJK / Noto Sans Mono CJK — SIL Open Font License 1.1"


def _font(size: int, mono: bool = False):
    from PIL import ImageFont

    path = NOTO_MONO if mono else NOTO
    try:
        return ImageFont.truetype(path, size=size, index=0)
    except TypeError:
        return ImageFont.truetype(path, size=size)


def prompt_guard(shot: dict[str, Any]) -> list[str]:
    """Return missing game_pov prompt clauses for one shot."""
    missing = []
    if str(shot.get("mode")) == "pov":
        info = shot.get("pov") or {}
        missing.extend(f"pov.{key}" for key in ("where", "looking", "next_move")
                       if not str(info.get(key) or "").strip())
        body = " ".join(str(info.get(k) or "") for k in ("where", "looking", "next_move", "body"))
        if not any(term in body for term in ("手", "袖", "鞋")):
            missing.append("pov.visible_body")
    if str(shot.get("mode")) == "third_person_pass":
        comp = shot.get("composition") or {}
        missing.extend(f"composition.{key}" for key in ("protagonist", "other", "camera")
                       if not str(comp.get(key) or "").strip())
    neg = " ".join(str(x) for x in shot.get("negatives") or [])
    missing.extend(f"negatives.{term}" for term in ("无字幕", "无文字", "无logo", "无水印", "不要音乐")
                   if term not in neg)
    return missing


def make_ui_png(text: str, out_png: Path, *, width: int = 420, height: int = 96, accent: str = "#E8E8E8") -> Path:
    """Transparent interaction prompt (e.g. 进入教室 / 接听电话)."""
    from PIL import Image, ImageDraw

    out_png.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((4, 4, width - 4, height - 4), radius=18,
                           fill=(12, 14, 18, 190), outline=(230, 230, 230, 230), width=3)
    font = _font(44)
    box = draw.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    draw.text(((width - tw) / 2, (height - th) / 2 - 4), text, font=font, fill=accent)
    img.save(out_png)
    return out_png


def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = round((t - int(t)) * 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def write_dialogue_box_ass(edit: dict[str, Any], out_ass: Path) -> Path:
    """Pixel-font game dialogue box on a blurred feathered band (lower third)."""
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Pixel,Noto Sans Mono CJK SC,46,&H00F2F2F2,&H00F2F2F2,&H00101010,&H90000000,1,0,0,0,100,100,2,0,1,3,0,2,90,90,250,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    lines.extend(
        f"Dialogue: 0,{_ass_time(float(row['start_s']))},{_ass_time(float(row['end_s']))},Pixel,,0,0,0,,"
        f"{str(row['text']).replace(chr(10), r'\\N')}"
        for row in edit.get("subtitles") or []
    )
    out_ass.parent.mkdir(parents=True, exist_ok=True)
    out_ass.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_ass


def _cmd(args: list[str]) -> None:
    subprocess.run(args, check=True)


def game_dialogue_box(video: Path, edit: dict[str, Any], out_video: Path) -> dict[str, Any]:
    """Copy the frame, blur+feather the lower band, then put pixel text on it."""
    ass = write_dialogue_box_ass(edit, out_video.parent / "dialogue_box.ass")
    vf = (
        "split[base][copy];"
        "[copy]crop=1080:520:0:1320,boxblur=18:3,eq=brightness=-0.12[blur];"
        "[blur]format=rgba,geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='if(lt(Y,90),255*Y/90,if(gt(Y,430),255*(520-Y)/90,255))'[mask];"
        "[base][mask]overlay=0:1320[band];"
        f"[band]ass={ass},format=yuv420p[v]"
    )
    _cmd([FFMPEG, "-y", "-v", "error", "-i", str(video), "-vf", vf, "-c:v", "libx264", "-preset",
          "veryfast", "-crf", "20", "-c:a", "copy", str(out_video)])
    return {"video": str(out_video), "ass": str(ass), "font_license": FONT_LICENSE}


def apply_ui_overlays(video: Path, edit: dict[str, Any], out_video: Path) -> dict[str, Any]:
    overlays = edit.get("ui_overlays") or []
    if not overlays:
        shutil.copy(video, out_video)
        return {"video": str(out_video), "overlays": []}
    inputs = ["-i", str(video)]
    filters = []
    last = "[0:v]"
    made = []
    for i, ui in enumerate(overlays, start=1):
        png = Path(str(ui.get("png") or ""))
        if not png.is_file():
            png = make_ui_png(str(ui.get("text") or "继续"), video.parent / f"ui_{i}.png")
            ui["png"] = str(png)
        inputs += ["-i", str(png)]
        start = float(ui.get("start_s") or 0)
        end = float(ui.get("end_s") or start + 2.0)
        x = int(ui.get("x") or 60)
        y = int(ui.get("y") or 1500)
        filters.append(f"[{i}:v]format=rgba[ui{i}]")
        filters.append(f"{last}[ui{i}]overlay={x}:{y}:enable='between(t,{start:.3f},{end:.3f})'[v{i}]")
        last = f"[v{i}]"
        made.append({"text": ui.get("text"), "png": str(png), "start_s": start, "end_s": end, "x": x, "y": y})
    filters.append(f"{last}format=yuv420p[vout]")
    _cmd([FFMPEG, "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters),
          "-map", "[vout]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
          "-c:a", "copy", str(out_video)])
    return {"video": str(out_video), "overlays": made}


def bridge_between(prev_clip: Path, next_clip: Path, out_clip: Path, *, provider: Any = None,
                   prompt: str = "两个视角之间的连续过渡，动作与光线连续，不出现新人物") -> dict[str, Any]:
    """First/last-frame bridge; offline falls back to a short dissolve."""
    work = out_clip.parent / "bridge"
    work.mkdir(parents=True, exist_ok=True)
    last = work / "last.png"
    first = work / "first.png"
    for src, dst, ss in ((prev_clip, last, "-sseof -0.06"), (next_clip, first, "-ss 0")):
        _cmd([FFMPEG, "-y", "-v", "error", ss, "-i", str(src), "-frames:v", "1", str(dst)])
    if provider is not None and provider.name != "offline" and provider.available()[0]:
        from .providers import VideoRequest

        req = VideoRequest(
            prompt=prompt, output_path=out_clip, duration_s=1.5, mode="first_last",
            first_frame=str(last), last_frame=str(first), image=str(last),
            reference_images=[str(last), str(first)],
        )
        res = provider.render(req)
        return {"method": "first_last", "provider": res.provider, "path": str(res.path)}
    # offline: freeze-frame dissolve, then trim one duplicated frame on each side.
    _cmd([FFMPEG, "-y", "-v", "error", "-loop", "1", "-t", "0.8", "-i", str(last),
          "-loop", "1", "-t", "0.8", "-i", str(first), "-filter_complex",
          "[0:v]scale=1080:1920,setsar=1[a];[1:v]scale=1080:1920,setsar=1[b];"
          "[a][b]xfade=transition=fade:duration=0.5:offset=0.3,format=yuv420p[v]",
          "-map", "[v]", "-r", "30", "-c:v", "libx264", "-crf", "20", str(out_clip)])
    return {"method": "offline_dissolve", "provider": "offline", "path": str(out_clip)}


def apply_game_pov_post(
    video: Path,
    edit: dict[str, Any],
    out_video: Path,
    *,
    dialogue_box: bool = True,
) -> dict[str, Any]:
    """Apply UI overlays then the game dialogue box to a finished cut."""
    box = None
    base = video
    if dialogue_box and edit.get("dialogue_box"):
        boxed = out_video.parent / "with_box.mp4"
        box = game_dialogue_box(video, edit, boxed)
        base = boxed
    ui = apply_ui_overlays(base, edit, out_video)
    report = {"video": str(out_video), "ui": ui, "dialogue_box": box,
              "font_license": FONT_LICENSE}
    (out_video.parent / "game_pov_post.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                                         encoding="utf-8")
    return report
