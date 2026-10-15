#!/usr/bin/env python3
"""T2 xfade pack E2E 样片生成脚本。

生成 output/xfadepack_e2e/ 下：
  - xfadepack_e2e.mp4   : 5 镜头 × 4 种转场(含 3 个 custom), d=0.6s
  - xfadepack_hardcut.mp4 : 同素材硬切基线
  - contact_sheet.png   : 每个注册转场一行, 25%/50%/75% 三帧 + id 标签
  - record.json         : 真实命令、filter_complex、ffprobe、sha256

素材用有结构的 lavfi 源(testsrc2/smptehdbars/rgbtestsrc/testsrc),不用纯色——
纯色上看不出方向反了/伪彩乱码这类错误。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "xfadepack_e2e"
OUTPUT.mkdir(parents=True, exist_ok=True)

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

from hevi.assembly.assembler import build_xfade_chain
from hevi.assembly.xfade_transitions import ALL_TRANSITIONS

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def _probe(path: Path) -> dict:
    out = _run(
        [FFPROBE, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
    ).stdout
    return json.loads(out)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _video_info(path: Path) -> dict:
    p = _probe(path)
    v = next(s for s in p["streams"] if s["codec_type"] == "video")
    return {
        "duration": float(p["format"]["duration"]),
        "width": int(v["width"]),
        "height": int(v["height"]),
        "avg_frame_rate": v.get("avg_frame_rate"),
        "nb_frames": int(v["nb_frames"]) if "nb_frames" in v else None,
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def main() -> None:
    RECORD: dict = {}

    # ── 1. 生成 5 个有结构的 lavfi 镜头（每段 3s，1080x1920，30fps）──
    SHOT_DUR = 3.0
    WIDTH, HEIGHT = 1080, 1920
    FPS = 30
    XFADE_D = 0.6

    shot_configs = [
        ("testsrc2", None),
        ("smptehdbars", None),
        ("rgbtestsrc", None),
        ("testsrc", None),
        ("testsrc2", "drawbox=x=200:y=400:w=680:h=300:c=yellow:t=fill"),
    ]
    clips = []
    for i, (src, extra) in enumerate(shot_configs):
        c = OUTPUT / f"shot{i}.mp4"
        cmd = [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"{src}=duration={SHOT_DUR}:size={WIDTH}x{HEIGHT}:rate={FPS}",
        ]
        if extra:
            cmd += ["-vf", extra]
        cmd += ["-pix_fmt", "yuv420p", str(c)]
        _run(cmd)
        clips.append(c)
    RECORD["shots"] = [
        {"index": i, "source": s, "extra_vf": e, "path": str(c)}
        for i, ((s, e), c) in enumerate(zip(shot_configs, clips))
    ]

    # ── 2. 逐接缝转场成片（3 custom + 1 builtin）──────────────────────
    transitions = ["whip", "fade", "glitch", "zoom_punch"]
    fc, label, total = build_xfade_chain([SHOT_DUR] * 5, transitions, XFADE_D)

    e2e_out = OUTPUT / "xfadepack_e2e.mp4"
    inputs = []
    for c in clips:
        inputs.extend(["-i", str(c)])
    e2e_cmd = [
        FFMPEG,
        "-y",
        *inputs,
        "-filter_complex",
        fc,
        "-map",
        label,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        str(e2e_out),
    ]
    _run(e2e_cmd)

    RECORD["xfadepack_e2e"] = {
        "transitions": transitions,
        "custom_count": sum(
            1 for t in transitions if next(x for x in ALL_TRANSITIONS if x.id == t).kind == "custom"
        ),
        "xfade_d": XFADE_D,
        "command": e2e_cmd,
        "filter_complex": fc,
        "map_label": label,
        "expected_total": total,
        "ffprobe": _video_info(e2e_out),
    }
    print(
        f"✓ xfadepack_e2e.mp4  duration={RECORD['xfadepack_e2e']['ffprobe']['duration']:.3f}s  "
        f"size={RECORD['xfadepack_e2e']['ffprobe']['size_bytes']}B  "
        f"sha256={RECORD['xfadepack_e2e']['ffprobe']['sha256'][:16]}..."
    )

    # ── 3. 硬切基线（同素材，无重叠）──────────────────────────────────
    concat_list = OUTPUT / "concat.txt"
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in clips))
    hardcut_out = OUTPUT / "xfadepack_hardcut.mp4"
    hc_cmd = [
        FFMPEG,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        str(hardcut_out),
    ]
    _run(hc_cmd)
    RECORD["hardcut_baseline"] = {
        "command": hc_cmd,
        "concat_list": concat_list.read_text(),
        "ffprobe": _video_info(hardcut_out),
    }
    print(
        f"✓ xfadepack_hardcut.mp4  duration={RECORD['hardcut_baseline']['ffprobe']['duration']:.3f}s  "
        f"size={RECORD['hardcut_baseline']['ffprobe']['size_bytes']}B  "
        f"sha256={RECORD['hardcut_baseline']['ffprobe']['sha256'][:16]}..."
    )

    # ── 4. Contact sheet：每个注册转场一行 25%/50%/75% 三帧 + id 标签 ──
    #   A=testsrc2, B=smptehdbars（都有结构，纯色上看不出错误）。
    CELL_W, CELL_H = 192, 144
    LABEL_W = 150
    SHORT_D = 1.0
    SHORT_XFADE = 0.5
    N_FRAMES = 3
    FRACS = (0.25, 0.5, 0.75)
    off = SHORT_D - SHORT_XFADE  # 过渡起点在成片时间轴上的位置 = 0.5
    ROWS = len(ALL_TRANSITIONS)
    sheet_w = LABEL_W + CELL_W * N_FRAMES
    sheet_h = CELL_H * ROWS

    a_short = OUTPUT / "_a_short.mp4"
    b_short = OUTPUT / "_b_short.mp4"
    _run(
        [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=duration={SHORT_D}:size={CELL_W}x{CELL_H}:rate={FPS}",
            "-pix_fmt",
            "yuv420p",
            str(a_short),
        ]
    )
    _run(
        [
            FFMPEG,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"smptehdbars=duration={SHORT_D}:size={CELL_W}x{CELL_H}:rate={FPS}",
            "-pix_fmt",
            "yuv420p",
            str(b_short),
        ]
    )

    from PIL import Image, ImageDraw, ImageFont

    canvas = Image.new("RGB", (sheet_w, sheet_h), (20, 20, 20))
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(FONT, 15)
    except OSError:
        font = ImageFont.load_default()

    labels: list[str] = []
    for idx, trans in enumerate(ALL_TRANSITIONS):
        row_y = idx * CELL_H
        # 标签格
        draw.rectangle([0, row_y, LABEL_W - 1, row_y + CELL_H - 1], fill=(35, 35, 45))
        draw.text((6, row_y + 6), trans.id, fill=(255, 230, 120), font=font)
        draw.text((6, row_y + 26), trans.kind, fill=(150, 200, 255), font=font)
        labels.append(trans.id)

        fc_t, lbl_t, _ = build_xfade_chain([SHORT_D, SHORT_D], [trans.id], SHORT_XFADE)
        tmp = OUTPUT / f"_tmp_{idx}.mp4"
        _run(
            [
                FFMPEG,
                "-y",
                "-i",
                str(a_short),
                "-i",
                str(b_short),
                "-filter_complex",
                fc_t,
                "-map",
                lbl_t,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                str(tmp),
            ]
        )
        # 一次性解码整段,按帧号取 25/50/75%,避免 -ss 定位误差
        raw = subprocess.run(
            [FFMPEG, "-y", "-i", str(tmp), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True,
        ).stdout
        frames = memoryview(raw)
        fsz = CELL_W * CELL_H * 3
        for j, frac in enumerate(FRACS):
            fi = int(round((off + frac * SHORT_XFADE) * FPS))
            frame = Image.frombytes(
                "RGB", (CELL_W, CELL_H), bytes(frames[fi * fsz : (fi + 1) * fsz])
            )
            canvas.paste(frame, (LABEL_W + j * CELL_W, row_y))

    sheet_path = OUTPUT / "contact_sheet.png"
    canvas.save(sheet_path)
    RECORD["contact_sheet"] = {
        "path": str(sheet_path),
        "rows": ROWS,
        "frames_per_transition": list(FRACS),
        "cell": [CELL_W, CELL_H],
        "labels": labels,
        "size_bytes": sheet_path.stat().st_size,
    }
    print(f"✓ contact_sheet.png  {ROWS} rows × {N_FRAMES} frames  {sheet_path.stat().st_size}B")

    # 清理临时文件(仅本脚本在 OUTPUT 内生成的下划线前缀中间件)
    for p in [a_short, b_short] + [OUTPUT / f"_tmp_{i}.mp4" for i in range(len(ALL_TRANSITIONS))]:
        p.unlink(missing_ok=True)

    # ── 5. 写 record.json ─────────────────────────────────────────────
    record_path = OUTPUT / "record.json"
    record_path.write_text(json.dumps(RECORD, indent=2, ensure_ascii=False))
    print("✓ record.json written")
    print(f"\n产物目录: {OUTPUT}")
    for f in sorted(OUTPUT.iterdir()):
        print(f"  {f.name}  ({f.stat().st_size}B)")


if __name__ == "__main__":
    main()
