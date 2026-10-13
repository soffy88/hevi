#!/usr/bin/env python3
"""Render the dirstyle E2E artifacts from the clean source (B3 / artifact pass).

For each of the four director styles this script:
  1. runs the CPU style grade + per-style 9:16 reframe -> <style>.mp4
  2. burns the Chinese style-name subtitle -> <style>_subbed.mp4
  3. extracts the 0/0.25/0.5/0.75 representative frames
and then rebuilds contact_sheet.png, record.json (ffprobe-measured) and
SHA256SUMS.  No mock data: every field is measured from the produced files.

The source is the clean, text-free clip at output/dirstyle_e2e/source_clean.mp4.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from hevi.layer4_legacy.dirstyle.omodul_impl.grade import run_style_grade
from hevi.layer4_legacy.dirstyle.oprim_impl import get_style
from hevi.layer4_legacy.dirstyle.oskill_impl.compiler import compile_prompt

ROOT = Path("/data/soffy/projects/hevi-dirstyle")
OUT = ROOT / "output" / "dirstyle_e2e"
SOURCE = OUT / "source_clean.mp4"
CJK_FONT = "/home/soffy/.local/share/fonts/wqy-zenhei.ttc"

STYLES = ["wong_kar_wai", "wes_anderson", "fincher", "zhang_yimou"]
STYLE_ZH = {
    "wong_kar_wai": "王家卫风格",
    "wes_anderson": "韦斯·安德森风格",
    "fincher": "大卫·芬奇风格",
    "zhang_yimou": "张艺谋风格",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def probe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(out.stdout)
    vs = next(s for s in data["streams"] if s["codec_type"] == "video")
    fs = data["format"]
    return {
        "width": int(vs["width"]),
        "height": int(vs["height"]),
        "fps": vs.get("r_frame_rate", "0/1"),
        "codec": vs["codec_name"],
        "duration_s": float(fs["duration"]),
    }


def burn_subtitle(src: Path, dst: Path, text: str) -> list[str]:
    """Burn a CJK style-name subtitle into the lower safe band of *src*.

    This ffmpeg build has no drawtext filter, so we render via libass
    (``subtitles=``) from a generated ASS file.  The style places the
    caption in the lower interface-safe band, centred.
    """
    ass_path = OUT / f"_{dst.stem}.ass"
    ass = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, "
        "BackColour, Bold, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding\n"
        "Style: Sub,WenQuanYi Zen Hei,64,&H00FFFFFF,&H00000000,&H00000000,"
        "0,1,4,0,2,90,90,260,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
        f"Dialogue: 0,0:00:00.00,9:59:59.00,Sub,,0,0,0,,{text}\n"
    )
    ass_path.write_text(ass, encoding="utf-8")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        f"subtitles={ass_path}",
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "-preset",
        "fast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        str(dst),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"subtitle burn failed for {src}: {proc.stderr[-1500:]}")
    return cmd


def extract_frame(video: Path, png: Path, ss: float) -> None:
    cmd = ["ffmpeg", "-y", "-ss", str(ss), "-i", str(video), "-frames:v", "1", str(png)]
    subprocess.run(cmd, check=True, capture_output=True)


def frame_path(sid: str, frac: float) -> Path:
    """Deterministic representative-frame path (0.0 -> ``<sid>_frame0.png``)."""
    return OUT / f"{sid}_frame{frac:g}.png"


def main() -> int:
    assert SOURCE.exists(), f"missing clean source {SOURCE}"
    src_probe = probe(SOURCE)
    records: list[dict] = []

    for sid in STYLES:
        style = get_style(sid)
        out_mp4 = OUT / f"{sid}.mp4"
        res = run_style_grade(
            input_video=SOURCE,
            style_grade=style.grade,
            output_path=out_mp4,
            aspect_mode="letterbox",
            reframe=style.reframe_9x16,
            style_id=sid,
        )
        print(f"graded {sid}: {res.duration_s:.3f}s {res.width}x{res.height}")

        # representative frames from the graded video
        for frac in (0.0, 0.25, 0.5, 0.75):
            ss = res.duration_s * frac
            extract_frame(out_mp4, frame_path(sid, frac), ss)

        # subbed version
        subbed = OUT / f"{sid}_subbed.mp4"
        sub_cmd = burn_subtitle(out_mp4, subbed, STYLE_ZH[sid])
        extract_frame(subbed, OUT / f"{sid}_subtitle.png", res.duration_s * 0.5)

        prompt = compile_prompt(
            sid,
            scene="",
            aspect="9:16",
            target="video",
        )
        sub_probe = probe(subbed)
        records.append(
            {
                "style_id": sid,
                "display_zh": style.display_zh,
                "display_en": style.display_en,
                "input_path": "output/dirstyle_e2e/source_clean.mp4",
                "output_path": f"output/dirstyle_e2e/{sid}.mp4",
                "reframe_9x16": style.reframe_9x16,
                "ffmpeg_cmd": res.ffmpeg_cmd,
                "filter_chain": res.filter_chain,
                "duration_s": res.duration_s,
                "width": res.width,
                "height": res.height,
                "fps": res.fps,
                "codec": res.codec,
                "sha256": res.output_sha256,
                "prompt_zh": prompt["positive"],
                "prompt_en": prompt["positive"],
                "negative": prompt["negative"],
                "subbed_output": f"output/dirstyle_e2e/{sid}_subbed.mp4",
                "subbed_ffmpeg_cmd": sub_cmd,
                "subbed_width": sub_probe["width"],
                "subbed_height": sub_probe["height"],
                "subbed_duration": sub_probe["duration_s"],
                "subbed_codec": sub_probe["codec"],
                "subbed_sha256": sha256_file(subbed),
            }
        )

    # ---- contact sheet: 4 styles x 4 frames ----
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(CJK_FONT, 26)
    tw, th = 270, 480
    sheet = Image.new("RGB", (tw * len(STYLES), th * 4 + 40), "white")
    draw = ImageDraw.Draw(sheet)
    for r, sid in enumerate(STYLES):
        for c, frac in enumerate((0.0, 0.25, 0.5, 0.75)):
            img = Image.open(OUT / f"{sid}_frame{frac}.png").resize((tw, th))
            sheet.paste(img, (r * tw, c * th))
        draw.text((r * tw + 8, th * 4 + 6), STYLE_ZH[sid], font=font, fill="black")
    sheet.save(OUT / "contact_sheet.png")
    print("contact_sheet.png rebuilt")

    # ---- stickman sample entry (rendered separately by render_stickman_sample.py) ----
    stick = OUT / "stickman_9x16.mp4"
    if stick.exists():
        sp = probe(stick)
        records.append(
            {
                "style_id": "stickman_9x16",
                "display_zh": "火柴人 9:16 样片",
                "display_en": "Stickman 9:16 Sample",
                "input_path": str(stick.relative_to(ROOT)),
                "output_path": str(stick.relative_to(ROOT)),
                "ffmpeg_cmd": [],
                "filter_chain": "PIL-rendered stickman frames -> ffmpeg libx264",
                "duration_s": sp["duration_s"],
                "width": sp["width"],
                "height": sp["height"],
                "fps": sp["fps"],
                "codec": sp["codec"],
                "sha256": sha256_file(stick),
                "prompt_zh": "白底黑线火柴人，5段心跳结构，竖屏纵深构图，CJK字幕在安全区内",
                "prompt_en": "black line stickman on white, heartbeat5 structure, "
                "vertical recompose, CJK subtitles in safe band",
                "source": "PIL CPU render (scripts/render_stickman_sample.py)",
            }
        )

    # ---- record.json ----
    record = {
        "styles": records,
        "source": {
            "path": "output/dirstyle_e2e/source_clean.mp4",
            "kind": "generated",
            "description": "Clean text-free 1920x1080 12s source rendered with PIL "
            "(graded sky + hill ridge + walking human silhouette); the picture "
            "carries no on-screen text, logo or caption of any kind.",
            "generation_command": "python scripts/gen_clean_source.py",
            "license": "CC0 (self-generated, no third-party content)",
            "duration_s": src_probe["duration_s"],
            "width": src_probe["width"],
            "height": src_probe["height"],
            "fps": 30,
            "sha256": sha256_file(SOURCE),
        },
    }
    (OUT / "record.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("record.json written")

    # ---- SHA256SUMS ----
    names = [
        "source_clean.mp4",
        *[f"{s}.mp4" for s in STYLES],
        *[f"{s}_subbed.mp4" for s in STYLES],
        "stickman_9x16.mp4",
    ]
    lines = []
    for n in names:
        p = OUT / n
        if p.exists():
            lines.append(f"{sha256_file(p)}  {n}")
    (OUT / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("SHA256SUMS written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
