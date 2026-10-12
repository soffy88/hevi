#!/usr/bin/env python
"""OMQUALITY E2E —— 真跑一遍后期增强 / 审片 / Backlot 审批与回放。

用法(仓库根目录):
    .venv/bin/python scripts/om_quality_e2e.py [--out output/om_quality_e2e] [--fast]

产物全部落在 ``output/om_quality_e2e/``, 每一件都用 ffprobe / sha256 实测并写进
``om_quality_e2e_manifest.json``。**禁止造假**: 任何一步量不出来就记 ``unmeasured``,
绝不用占位文件顶替; 脚本最后用 ``GATES`` 逐条判定, 不满足就以非零码退出。

四段:
  A 后期增强  —— 对一条**已有成片**做抠像 / 2x 超分 / 人脸修复 / 调色, 出前后对比图
  B 审片      —— 对 3 条已有成片出审片报告(ffprobe / 4 点抽帧 / 响度静音 / 字幕越界 /
                 幻灯片风险), 并拿排产前定死的交付承诺对账; 另建一条**幻灯片压力样本**
                 (真实成片抽帧拼的静帧片 + 真 SRT) 证明判红这条路径真的会红
  C Backlot   —— 走真 HTTP 栈: 登记分镜(自动实测缩略图与质量分) → 审批门
                 approve/reject 写回 → 联络表 PNG → REPLAY 回放清单 + 真 mp4
  D 收尾      —— 3O lint 与基线比对 + 全量产物 sha256 清单

零付费 API, 全 CPU, 全本地权重。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

REAL_VIDEO_DIR = REPO / "artifacts" / "real_video" / "20261005T160434Z"

#: 审片的三条**已有成片**(不是本次造的)。
REVIEW_TARGETS: tuple[tuple[str, Path], ...] = (
    ("FINAL", REAL_VIDEO_DIR / "final" / "FINAL.mp4"),
    ("scene_interview_sub", REAL_VIDEO_DIR / "artifacts" / "scene_interview_sub.mp4"),
    ("nasa-earth-iss", REAL_VIDEO_DIR / "artifacts" / "nasa-earth-iss-0001_finecut.mp4"),
)


# ---------------------------------------------------------------------------
# 基础工具: 一切都量, 不猜
# ---------------------------------------------------------------------------


def ffprobe(path: Path) -> dict[str, Any]:
    """Real ffprobe of a media file (streams + format). Raises on failure."""
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"ffprobe failed for {path}: {proc.stderr.strip()[-300:]}")
    data = json.loads(proc.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    width = int(video.get("width", 0)) if video else 0
    height = int(video.get("height", 0)) if video else 0
    num, _, den = (video.get("avg_frame_rate") or "0/1").partition("/") if video else ("0", "", "1")
    fps = round(float(num) / float(den), 3) if den and float(den) else 0.0
    return {
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": int(fmt.get("size", 0)),
        "duration_s": round(float(fmt.get("duration", 0.0)), 3),
        "width": width,
        "height": height,
        "fps": fps,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "has_audio": audio is not None,
        "nb_frames": int(video.get("nb_frames", 0)) if video else 0,
    }


def measure_image(path: Path) -> dict[str, Any]:
    """Measure a real PNG/JPEG with PIL (no ffprobe for stills)."""
    from PIL import Image, ImageStat

    with Image.open(path) as im:
        rgb = im.convert("RGB")
        stat = ImageStat.Stat(rgb.convert("L"))
        return {
            "path": str(path),
            "width": im.width,
            "height": im.height,
            "mode": im.mode,
            "mean_luma": round(float(stat.mean[0]), 3),
            "stdev_luma": round(float(stat.stddev[0]), 3),
            "size_bytes": path.stat().st_size,
        }


def sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def log(msg: str) -> None:
    print(f"[omq] {msg}", flush=True)


def crop_center(src: Path, dest: Path, width: int, height: int) -> Path:
    """Real centre crop via ffmpeg (keeps the pipeline honest: same decoder)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    probe = ffprobe(src)
    sw, sh = probe["width"], probe["height"]
    cw, ch = min(width, sw), min(height, sh)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vf",
            f"crop={cw}:{ch}:{(sw - cw) // 2}:{(sh - ch) // 2}",
            "-frames:v",
            "1",
            str(dest),
        ],
        check=True,
        capture_output=True,
    )
    return dest


def extract_frames(src: Path, dest_dir: Path, *, count: int = 4) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, ts in enumerate(_sample_timestamps(src, count)):
        dest = dest_dir / f"f{i:02d}_{ts:.2f}s.png"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{ts:.3f}",
                "-i",
                str(src),
                "-frames:v",
                "1",
                str(dest),
            ],
            check=True,
            capture_output=True,
        )
        if dest.is_file():
            paths.append(dest)
    return paths


def _sample_timestamps(src: Path, count: int) -> list[float]:
    duration = ffprobe(src)["duration_s"]
    if duration <= 0:
        return [0.0]
    # 25% / 50% / 75% … 不取 0 和尾帧(首尾常是黑场, 会误判黑帧)
    return [duration * (i + 1) / (count + 1) for i in range(count)]


def make_slideshow_stress_case(src: Path, out_dir: Path, *, slides: int = 6) -> tuple[Path, Path]:
    """Render a real slideshow film out of real frames of a finished film.

    This is the canonical silent-downgrade artefact the review gate exists to
    catch: a "deck" of stills with a narration track.  Every pixel comes from
    the finished film, the audio is the finished film's own audio, and a real
    SRT is written next to it so the subtitle/text-dependence path is exercised
    too.  It is labelled as constructed by this E2E — it is a stress case, not
    a pre-existing deliverable.
    """
    from hevi.layer4_legacy.review.oprim_impl.frames import build_contact_sheet

    work = out_dir / "slideshow"
    frames_dir = work / "slides"
    frames_dir.mkdir(parents=True, exist_ok=True)
    probe = ffprobe(src)
    duration = probe["duration_s"]
    picks: list[Path] = []
    for i in range(slides):
        ts = duration * (i + 1) / (slides + 1)
        dest = frames_dir / f"slide{i:02d}.png"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{ts:.3f}",
                "-i",
                str(src),
                "-vf",
                f"scale={min(640, probe['width'])}:-2",
                "-frames:v",
                "1",
                str(dest),
            ],
            check=True,
            capture_output=True,
        )
        picks.append(dest)

    video = out_dir / "slideshow_stress_case.mp4"
    hold = 2.0
    inputs: list[str] = []
    filters: list[str] = []
    concat: list[str] = []
    for i, img in enumerate(picks):
        inputs += ["-loop", "1", "-t", f"{hold}", "-i", str(img)]
        filters.append(f"[{i}:v]fps=12,format=yuv420p,setsar=1[v{i}]")
        concat.append(f"[v{i}]")
    filters.append("".join(concat) + f"concat=n={slides}:v=1:a=0,format=yuv420p[vout]")
    # 音频输入的序号是 len(picks) —— 每张幻灯片各占一个输入, 别写死成 1。
    audio_index = len(picks)
    if probe["has_audio"]:
        inputs += ["-i", str(src)]
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    audio_map = ["-map", f"{audio_index}:a"]
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vout]",
        *audio_map,
        "-shortest",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(video),
    ]
    subprocess.run(cmd, check=True, capture_output=True)

    # 真 SRT: 每张幻灯片一条, 覆盖整条片长
    srt = out_dir / "slideshow_stress_case.srt"
    lines: list[str] = []
    for i in range(slides):
        start = i * hold
        end = start + hold
        lines += [
            str(i + 1),
            f"{_srt_ts(start)} --> {_srt_ts(end - 0.05)}",
            f"第 {i + 1} 页 · 静态要点 {i + 1}",
        ]
        lines.append("")
    srt.write_text("\n".join(lines), encoding="utf-8")

    build_contact_sheet(
        frames=picks,
        output_path=work / "slides_source.png",
        labels=tuple(f"slide{i}" for i in range(slides)),
    )
    return video, srt


def _srt_ts(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def make_noise_fixture(out_dir: Path) -> Path:
    """Generate a random-noise video with white-noise audio (the bug repro)."""
    dest = out_dir / "bad_noise.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-y", "-f", "lavfi",
            "-i", "nullsrc=s=640x360:r=24:d=5",
            "-f", "lavfi",
            "-i", "anoisesrc=d=5:c=white:r=44100:a=0.5",
            "-vf", "geq=random(1)*255:128:128",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(dest),
        ],
        check=True, capture_output=True,
    )
    return dest


def make_macroblock_fixture(out_dir: Path) -> Path:
    """Generate a macroblock-pattern video with white-noise audio."""
    dest = out_dir / "bad_macroblock.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-y", "-f", "lavfi",
            "-i", "nullsrc=s=640x360:r=24:d=5",
            "-f", "lavfi",
            "-i", "anoisesrc=d=5:c=white:r=44100:a=0.5",
            "-vf",
            "geq=lum='48+mod(floor(X/16)+floor(Y/16),2)*208':cb=128:cr=128",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(dest),
        ],
        check=True, capture_output=True,
    )
    return dest


def make_half_gray_fixture(out_dir: Path) -> Path:
    """Generate a half-white/half-gray split-screen video."""
    dest = out_dir / "bad_half_gray.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-y",
            "-f", "lavfi", "-i", "color=c=white:s=320x360:r=24:d=5",
            "-f", "lavfi", "-i", "color=c=gray:s=320x360:r=24:d=5",
            "-filter_complex", "[0:v][1:v]hstack",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-an",
            str(dest),
        ],
        check=True, capture_output=True,
    )
    return dest


# ---------------------------------------------------------------------------
# A 后期增强
# ---------------------------------------------------------------------------


def section_enhance(out: Path, fast: bool) -> dict[str, Any]:
    log("A 后期增强")
    from hevi.enhance import build_comparison_sheet, enhance_media

    src = REAL_VIDEO_DIR / "final" / "FINAL.mp4"
    if not src.is_file():
        raise SystemExit(f"missing source film: {src}")
    step_dir = out / "A_enhance"
    step_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {"source": ffprobe(src), "ops": {}, "unmeasured": []}

    # 抠像 + 超分 + 人脸修复 都走图像路径: 先从成片里取一张真实代表帧
    frame = step_dir / "source_frame.png"
    crop_center(src, frame, 640, 360)
    results["source_frame"] = measure_image(frame)

    # --- A1 抠像 (rembg u2net, CPU) ---
    matte_dir = step_dir / "matte"
    r = enhance_media(op="matte", input_path=frame, output_dir=matte_dir, config={"model": "u2net"})
    matte = (r.get("results") or [{}])[0]
    matte_path = Path(matte.get("output_path", ""))
    results["ops"]["matte"] = {
        "status": r.get("status"),
        "backend": matte.get("backend"),
        "license": matte.get("license"),
        "commercial_ok": matte.get("commercial_ok"),
        "metrics": matte.get("metrics"),
        "output": measure_image(matte_path) if matte_path.is_file() else None,
    }
    if not matte_path.is_file():
        results["unmeasured"].append("matte")
    else:
        alpha = _alpha_coverage(matte_path)
        results["ops"]["matte"]["alpha_coverage"] = alpha
        mask = matte_dir / f"{matte_path.stem}_mask.png"
        if mask.is_file():
            results["ops"]["matte"]["mask"] = measure_image(mask)

    # --- A2 2x 超分 (Real-ESRGAN, CPU; 输入刻意裁小, CPU 上 1280x720 要十几分钟) ---
    sr_in = crop_center(src, step_dir / "sr_input.png", 320 if fast else 480, 180 if fast else 270)
    up_dir = step_dir / "upscale"
    t0 = time.time()
    r = enhance_media(op="upscale", input_path=sr_in, output_dir=up_dir, config={"scale": 2})
    up = (r.get("results") or [{}])[0]
    up_path = Path(up.get("output_path", ""))
    results["ops"]["upscale"] = {
        "status": r.get("status"),
        "backend": up.get("backend"),
        "metrics": up.get("metrics"),
        "elapsed_s": round(time.time() - t0, 1),
        "input": measure_image(sr_in),
        "output": measure_image(up_path) if up_path.is_file() else None,
        "sharpness": _sharpness(up_path) if up_path.is_file() else None,
        "input_sharpness": _sharpness(sr_in),
    }
    if not up_path.is_file():
        results["unmeasured"].append("upscale")

    # --- A3 人脸修复 (GFPGAN; 非商用权重, 必须显式 opt-in) ---
    face_dir = step_dir / "face_restore"
    face_src = crop_center(src, step_dir / "face_input.png", 256, 256)
    t0 = time.time()
    r = enhance_media(
        op="face_restore",
        input_path=face_src,
        output_dir=face_dir,
        config={"allow_noncommercial": True, "weight": 0.7, "upscale": 1},
    )
    face = (r.get("results") or [{}])[0]
    face_path = Path(face.get("output_path", ""))
    results["ops"]["face_restore"] = {
        "status": r.get("status"),
        "backend": face.get("backend"),
        "license": face.get("license"),
        "commercial_ok": face.get("commercial_ok"),
        "metrics": face.get("metrics"),
        "elapsed_s": round(time.time() - t0, 1),
        "input": measure_image(face_src),
        "output": measure_image(face_path) if face_path.is_file() else None,
    }
    if not face_path.is_file():
        results["ops"]["face_restore"]["note"] = (
            "未检出人脸或权重不可用 —— 如实记失败, 不换素材凑一张"
        )
        results["unmeasured"].append("face_restore")

    # 默认关闭的证明: 不带 opt-in 必须被拒
    r_off = enhance_media(
        op="face_restore", input_path=face_src, output_dir=step_dir / "face_restore_denied"
    )
    results["ops"]["face_restore_default_off"] = {
        "status": r_off.get("status"),
        "error": r_off.get("error"),
    }

    # --- A4 调色 LUT (ffmpeg lut3d) ---
    lut_dir = step_dir / "lut"
    lut_src = REAL_VIDEO_DIR / "artifacts" / "scene_broll_720p.mp4"
    t0 = time.time()
    r = enhance_media(
        op="lut",
        input_path=lut_src,
        output_dir=lut_dir,
        # 不设 max_frames: 截断会悄悄把成片剪短, 这里整条走完, 再由验收门
        # 比对输出时长与源时长。
        config={"look": "teal", "intensity": 0.85, "process_video": True},
    )
    lut = (r.get("results") or [{}])[0]
    lut_path = Path(lut.get("output_path", ""))
    results["ops"]["lut"] = {
        "status": r.get("status"),
        "backend": lut.get("backend"),
        "metrics": lut.get("metrics"),
        "elapsed_s": round(time.time() - t0, 1),
        "source": ffprobe(lut_src),
        "output": ffprobe(lut_path) if lut_path.is_file() else None,
    }
    if not lut_path.is_file():
        results["unmeasured"].append("lut")

    # --- 前后对比图 ---
    sheets: dict[str, Any] = {}
    if matte_path.is_file():
        p = build_comparison_sheet(
            frame,
            matte_path,
            step_dir / "compare_matte.png",
            title="FINAL.mp4 representative frame — matte (rembg u2net)",
            labels=("SOURCE", "MATTED"),
        )
        sheets["matte"] = p.get("path")
    if up_path.is_file():
        p = build_comparison_sheet(
            sr_in,
            up_path,
            step_dir / "compare_upscale.png",
            title="centre crop — Real-ESRGAN 2x",
            labels=(
                f"SOURCE {results['ops']['upscale']['input']['width']}px",
                f"2x {results['ops']['upscale']['output']['width']}px",
            ),
        )
        sheets["upscale"] = p.get("path")
    if face_path.is_file():
        p = build_comparison_sheet(
            face_src,
            face_path,
            step_dir / "compare_face_restore.png",
            title="centre crop — GFPGAN face restore (non-commercial weights)",
            labels=("SOURCE", "RESTORED"),
        )
        sheets["face_restore"] = p.get("path")
    if lut_path.is_file():
        # 对比图只能吃图片: 从源片与调色片各取同一时刻的真实帧
        lut_before = crop_center(lut_src, step_dir / "lut_before.png", 640, 360)
        lut_after = crop_center(lut_path, step_dir / "lut_after.png", 640, 360)
        p = build_comparison_sheet(
            lut_before,
            lut_after,
            step_dir / "compare_lut.png",
            title="scene_broll_720p.mp4 — lut3d teal @0.85",
            labels=("SOURCE", "GRADED"),
        )
        sheets["lut"] = p.get("path")
    results["comparison_sheets"] = sheets

    if lut_path.is_file():
        results["ops"]["lut"]["mean_rgb"] = {
            "source": _mean_rgb(lut_src),
            "graded": _mean_rgb(lut_path),
        }
        results["ops"]["lut"]["mean_luma"] = {
            "source": _video_mean_luma(lut_src),
            "graded": _video_mean_luma(lut_path),
        }
    results["sharpness_method"] = (
        f"FIND_EDGES 方差, 先等比缩到宽 {SHARPNESS_NORM_WIDTH}px 再量(跨分辨率可比)"
    )
    return results


def _alpha_coverage(path: Path) -> float | None:
    """Fraction of opaque pixels in an RGBA cutout (0..1), measured."""
    from PIL import Image

    with Image.open(path) as im:
        if im.mode != "RGBA":
            return None
        alpha = im.getchannel("A")
        hist = alpha.histogram()
        total = sum(hist) or 1
        opaque = sum(hist[200:])  # >=200 视为前景
        return round(opaque / total, 4)


#: 锐度量测的归一化宽度。像素差类指标天生随分辨率变化 —— 2x 图的边缘被摊到
#: 两倍的像素上, 原始方差反而会"变小"。所以先等比缩到同一宽度再量, 两次量测
#: 才可比。
SHARPNESS_NORM_WIDTH = 256


def _sharpness(path: Path) -> float | None:
    """Scale-normalised edge energy — a real sharpness number, not a label.

    Resizes to a fixed width first so a 2x image is not penalised for having
    its gradients spread over twice as many pixels.  The method is reported in
    the manifest so the number can be recomputed by hand.
    """
    from PIL import Image, ImageFilter

    with Image.open(path) as im:
        grey = im.convert("L")
        w = min(SHARPNESS_NORM_WIDTH, grey.width)
        grey = grey.resize(
            (w, max(1, round(grey.height * w / grey.width))), Image.Resampling.LANCZOS
        )
        edges = grey.filter(ImageFilter.FIND_EDGES)
        return round(float(_variance(edges)), 4)


def _mean_rgb(path: Path, frames: int = 6) -> dict[str, float] | None:
    """Mean R/G/B over real frames of a video (measured colour shift)."""
    from PIL import Image, ImageStat

    tmp = path.parent / f".{path.stem}_rgbprobe"
    tmp.mkdir(exist_ok=True)
    try:
        picks = extract_frames(path, tmp, count=frames)
        if not picks:
            return None
        acc = [0.0, 0.0, 0.0]
        for f in picks:
            with Image.open(f) as im:
                mean = ImageStat.Stat(im.convert("RGB")).mean
            for i in range(3):
                acc[i] += float(mean[i])
        n = len(picks)
        return {k: round(v / n, 3) for k, v in zip("rgb", acc, strict=True)}
    finally:
        for f in tmp.glob("*.png"):
            f.unlink(missing_ok=True)
        tmp.rmdir()


def _variance(img: Any) -> float:
    from PIL import ImageStat

    return float(ImageStat.Stat(img).var[0])


def _video_mean_luma(path: Path) -> float | None:
    """Mean luma over 6 real frames of the video (measured, not a label)."""
    tmp = path.parent / f".{path.stem}_lumaprobe"
    tmp.mkdir(exist_ok=True)
    try:
        frames = extract_frames(path, tmp, count=6)
        vals = [measure_image(f)["mean_luma"] for f in frames]
        return round(sum(vals) / len(vals), 3) if vals else None
    finally:
        for f in tmp.glob("*.png"):
            f.unlink(missing_ok=True)
        tmp.rmdir()


# ---------------------------------------------------------------------------
# B 审片
# ---------------------------------------------------------------------------


def section_review(out: Path) -> dict[str, Any]:
    log("B 审片(3 条已有成片 + 交付承诺对账 + 幻灯片压力样本)")
    from hevi.production.delivery_promise import classify_from_brief
    from hevi.review import review_finished_video

    step_dir = out / "B_review"
    step_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {"films": {}, "unmeasured": []}

    # 承诺按交付类型取: 成片走 cinematic → motion_led
    promise = classify_from_brief("cinematic", {}).to_dict()
    results["promise"] = promise

    for label, path in REVIEW_TARGETS:
        if not path.is_file():
            results["unmeasured"].append(f"review:{label}")
            continue
        report = review_finished_video(
            input_path=str(path),
            output_dir=step_dir / label,
            config={"promise": promise, "require_audio": True, "frame_count": 4},
        )
        m = report.get("metrics", {})
        results["films"][label] = {
            "input": str(path),
            "ffprobe": ffprobe(path),
            "sha256": sha256(path),
            "verdict": report.get("verdict"),
            "allows_compose": report.get("allows_compose"),
            "violations": report.get("violations"),
            "warnings": report.get("warnings"),
            "unmeasured": report.get("unmeasured"),
            "slideshow": {
                k: m.get("slideshow", {}).get(k)
                for k in ("risk", "verdict", "components", "missing")
            },
            "promise": m.get("promise"),
            "audio": m.get("audio"),
            "frames": {k: m.get("frames", {}).get(k) for k in ("count", "black", "broken", "flat")},
            "contact_sheet": (m.get("contact_sheet") or {}).get("path"),
            "report_json": str(step_dir / label / "review_report.json"),
        }
        log(
            f"  {label}: verdict={report.get('verdict')} "
            f"slideshow={m.get('slideshow', {}).get('verdict')} "
            f"risk={m.get('slideshow', {}).get('risk')}"
        )

    # --- 幻灯片压力样本: 证明判红这条路真的会红 ---
    log("  构造幻灯片压力样本(真实成片抽帧拼静帧片 + 真 SRT)")
    slide_video, slide_srt = make_slideshow_stress_case(
        REAL_VIDEO_DIR / "final" / "FINAL.mp4", step_dir
    )
    report = review_finished_video(
        input_path=str(slide_video),
        output_dir=step_dir / "slideshow_stress",
        config={"promise": promise, "subtitle_path": str(slide_srt), "require_audio": True},
    )
    m = report.get("metrics", {})
    results["slideshow_stress"] = {
        "constructed_by": "scripts/om_quality_e2e.py",
        "note": "真实成片抽帧拼的静帧片; 不是仓库里已有的成片, 用途是压测判红路径",
        "ffprobe": ffprobe(slide_video),
        "sha256": sha256(slide_video),
        "subtitle": m.get("subtitle"),
        "verdict": report.get("verdict"),
        "violations": report.get("violations"),
        "warnings": report.get("warnings"),
        "slideshow": {
            k: m.get("slideshow", {}).get(k) for k in ("risk", "verdict", "components", "missing")
        },
        "promise": m.get("promise"),
        "report_json": str(step_dir / "slideshow_stress" / "review_report.json"),
    }
    log(
        f"  slideshow_stress: verdict={report.get('verdict')} "
        f"risk={m.get('slideshow', {}).get('risk')}"
    )

    red = [
        k for k, v in results["films"].items() if (v.get("slideshow") or {}).get("verdict") == "red"
    ]
    results["existing_films_flagged_red"] = red
    results["red_demo_via_stress_case"] = (results["slideshow_stress"]["slideshow"] or {}).get(
        "verdict"
    ) == "red"

    # --- 破图/花屏负面样本：证明空间质量检测会判红 ---
    log("  构造破图负面样本(随机噪点 / 宏块花屏 / 半屏灰块)")
    bad_cases: dict[str, Any] = {}
    for name, maker in (
        ("noise", make_noise_fixture),
        ("macroblock", make_macroblock_fixture),
        ("half_gray", make_half_gray_fixture),
    ):
        clip = maker(step_dir)
        rep = review_finished_video(
            input_path=str(clip),
            output_dir=step_dir / f"bad_{name}",
            config={"promise": promise, "require_audio": True, "frame_count": 4},
        )
        bad_cases[name] = {
            "constructed_by": "scripts/om_quality_e2e.py",
            "ffprobe": ffprobe(clip),
            "sha256": sha256(clip),
            "verdict": rep.get("verdict"),
            "allows_compose": rep.get("allows_compose"),
            "violations": rep.get("violations"),
            "frames": {
                k: rep.get("metrics", {}).get("frames", {}).get(k)
                for k in ("count", "noise", "blocky", "flat")
            },
            "report_json": str(step_dir / f"bad_{name}" / "review_report.json"),
        }
        log(
            f"  bad_{name}: verdict={rep.get('verdict')} "
            f"allows_compose={rep.get('allows_compose')} "
            f"violations={len(rep.get('violations') or [])}"
        )
    results["bad_cases"] = bad_cases
    results["red_demo_via_bad_cases"] = all(
        (v.get("verdict") == "red") for v in bad_cases.values()
    )
    return results


# ---------------------------------------------------------------------------
# C Backlot 审批门 + REPLAY
# ---------------------------------------------------------------------------


def section_backlot(out: Path) -> dict[str, Any]:
    log("C Backlot 审批门 + REPLAY(走真 HTTP 栈)")
    from fastapi.testclient import TestClient

    from hevi.api.main import app
    from hevi.auth.dependencies import get_current_user
    from hevi.core.config import settings

    step_dir = out / "C_backlot"
    board_dir = step_dir / "board"
    board_dir.mkdir(parents=True, exist_ok=True)
    previous = settings.backlot_dir
    settings.backlot_dir = str(board_dir)
    app.dependency_overrides[get_current_user] = lambda: {"id": "e2e"}
    client = TestClient(app)
    run_id = "omq-e2e-run"
    trace: list[dict[str, Any]] = []

    def call(method: str, path: str, **kw: Any) -> dict[str, Any]:
        r = client.request(method, path, **kw)
        trace.append({"method": method, "path": path, "status": r.status_code})
        r.raise_for_status()
        return r.json()

    try:
        scenes = [
            (
                "sc01",
                0,
                "B-roll 太空",
                "earth limb from orbit, slow push in, 4k",
                REAL_VIDEO_DIR / "artifacts" / "scene_broll_720p.mp4",
                0.42,
            ),
            (
                "sc02",
                1,
                "访谈口播",
                "talking head, medium shot, warm key light",
                REAL_VIDEO_DIR / "artifacts" / "scene_interview_720p.mp4",
                0.31,
            ),
            (
                "sc03",
                2,
                "空间站外景",
                "iss exterior, orbital sunrise, long lens",
                REAL_VIDEO_DIR / "artifacts" / "nasa-collins-0001_finecut.mp4",
                0.18,
            ),
            (
                "sc04",
                3,
                "ISS 远景",
                "iss wide shot against earth, locked off",
                REAL_VIDEO_DIR / "artifacts" / "nasa-earth-iss-0001_finecut.mp4",
                0.16,
            ),
        ]
        registered: list[dict[str, Any]] = []
        for sid, idx, title, prompt, src, cost in scenes:
            if not src.is_file():
                continue
            body = call(
                "POST",
                f"/api/backlot/runs/{run_id}/shots",
                json={
                    "scene_id": sid,
                    "index": idx,
                    "title": title,
                    "prompt": prompt,
                    "source_path": str(src.resolve()),
                    "cost_usd": cost,
                },
            )
            registered.append(body["shot"])

        sheet = call("GET", f"/api/backlot/runs/{run_id}/contact-sheet")

        # 审批: 通过两条, 否决一条(带理由), 留一条待批
        decisions = [
            ("sc01", "approved", "构图与运动都达标", "director"),
            ("sc03", "rejected", "色温偏冷, 与 B-roll 不接", "director"),
            ("sc02", "approved", "口播可用, 保留", "director"),
        ]
        decision_bodies = []
        for sid, verdict, reason, who in decisions:
            decision_bodies.append(
                call(
                    "POST",
                    f"/api/backlot/runs/{run_id}/shots/{sid}/decision",
                    json={"decision": verdict, "reason": reason, "reviewer": who},
                )
            )
        # 空理由的否决必须被拒
        denied = client.post(
            f"/api/backlot/runs/{run_id}/shots/sc04/decision",
            json={"decision": "rejected", "reason": ""},
        )
        trace.append(
            {
                "method": "POST",
                "path": ".../sc04/decision",
                "status": denied.status_code,
                "expect": "400 空理由被拒",
            }
        )
        assert denied.status_code == 400, f"空理由的否决没有被拒: {denied.status_code}"

        board_path = Path(sheet.get("sheet", {}).get("path", "")) if sheet.get("sheet") else None
        after = call("GET", f"/api/backlot/runs/{run_id}/shots")
        events = call("GET", f"/api/backlot/runs/{run_id}/events?limit=200")

        replay = call("GET", f"/api/backlot/runs/{run_id}/replay?include=approved")
        render = call("POST", f"/api/backlot/runs/{run_id}/replay/render?include=approved")
        reject_replay = call("GET", f"/api/backlot/runs/{run_id}/replay?include=rejected")

        result = {
            "run_id": run_id,
            "board_dir": str(board_dir),
            "http_trace": trace,
            "registered_shots": registered,
            "summary_before_decisions": sheet.get("gate"),
            "contact_sheet": sheet.get("sheet"),
            "contact_sheet_measured": measure_image(board_path) if board_path else None,
            "summary_after_decisions": after["summary"],
            "shots_after_decisions": after["shots"],
            "decision_responses": [
                {
                    "summary": d["summary"],
                    "status": d["shot"]["status"],
                    "decisions": d["shot"]["decisions"],
                }
                for d in decision_bodies
            ],
            "reject_without_reason_status": denied.status_code,
            "event_types": sorted({e["event_type"] for e in events["events"]}),
            "shot_decision_events": [
                e for e in events["events"] if e["event_type"] == "shot_decision"
            ],
            "replay": replay,
            "replay_rejected": reject_replay,
            "replay_render": render["render"],
        }
        if board_path and board_path.is_file():
            result["contact_sheet"]["sha256"] = sha256(board_path)
        rpath = Path(render["render"].get("path") or "")
        if render["render"].get("ok") and rpath.is_file():
            result["replay_render"]["ffprobe"] = ffprobe(rpath)
            result["replay_render"]["sha256"] = sha256(rpath)
        return result
    finally:
        app.dependency_overrides.clear()
        settings.backlot_dir = previous


# ---------------------------------------------------------------------------
# D 收尾: 3O lint 与全量清单
# ---------------------------------------------------------------------------


def section_lint(out: Path) -> dict[str, Any]:
    log("D 3O lint 比对")
    baseline = out.parent.parent / ".qual-scratch" / "lint_baseline.txt"
    proc = subprocess.run(
        [sys.executable, "scripts/ci/run_3o_v3_lint.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    current = proc.stdout + proc.stderr
    (out / "lint_now.txt").write_text(current, encoding="utf-8")
    base_lines = baseline.read_text(encoding="utf-8").splitlines() if baseline.is_file() else []
    cur_lines = current.splitlines()
    base_fail = sorted(x for x in base_lines if x.startswith("[FAIL]"))
    cur_fail = sorted(x for x in cur_lines if x.startswith("[FAIL]"))
    return {
        "baseline_file": str(baseline),
        "baseline_fail": base_fail,
        "current_fail": cur_fail,
        "new_failures": sorted(set(cur_fail) - set(base_fail)),
        "fixed": sorted(set(base_fail) - set(cur_fail)),
        "identical": sorted(base_lines) == sorted(cur_lines),
    }


def collect_artifacts(out: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in sorted(out.rglob("*")):
        if not p.is_file() or p.name == "om_quality_e2e_manifest.json":
            continue
        rows.append(
            {
                "path": str(p.relative_to(out)),
                "bytes": p.stat().st_size,
                "sha256": sha256(p),
            }
        )
    return rows


# ---------------------------------------------------------------------------
# 验收门
# ---------------------------------------------------------------------------


def evaluate(report: dict[str, Any]) -> list[dict[str, Any]]:
    gates: list[dict[str, Any]] = []

    def gate(name: str, ok: bool, detail: str) -> None:
        gates.append({"gate": name, "ok": bool(ok), "detail": detail})

    enh = report.get("A_enhance", {}).get("ops", {})
    matte = enh.get("matte", {})
    gate(
        "enhance.matte",
        bool(matte.get("output")),
        f"backend={matte.get('backend')} alpha_coverage={matte.get('alpha_coverage')} "
        f"output={matte.get('output')}",
    )
    up = enh.get("upscale", {})
    gate(
        "enhance.upscale_2x",
        bool(up.get("output"))
        and up.get("output", {}).get("width", 0) == 2 * up.get("input", {}).get("width", 0)
        and float(up.get("sharpness") or 0) > float(up.get("input_sharpness") or 0),
        f"{up.get('input', {}).get('width')}px -> {up.get('output', {}).get('width')}px "
        f"backend={up.get('backend')}; 归一化锐度 "
        f"{up.get('input_sharpness')} -> {up.get('sharpness')}",
    )
    face = enh.get("face_restore", {})
    gate(
        "enhance.face_restore_optin_gate",
        enh.get("face_restore_default_off", {}).get("status") == "failed"
        and "non-commercial" in str(enh.get("face_restore_default_off", {}).get("error")),
        f"默认关闭已验证: {enh.get('face_restore_default_off', {}).get('error')}",
    )
    gate(
        "enhance.face_restore",
        bool(face.get("output"))
        and int((face.get("metrics") or {}).get("faces_restored") or 0) > 0,
        f"backend={face.get('backend')} license={face.get('license')} "
        f"commercial_ok={face.get('commercial_ok')} metrics={face.get('metrics')}",
    )
    lut = enh.get("lut", {})
    src_d = (lut.get("source") or {}).get("duration_s") or 0.0
    out_d = (lut.get("output") or {}).get("duration_s") or 0.0
    gate(
        "enhance.lut",
        bool(lut.get("output")) and abs(src_d - out_d) < 0.6,
        f"backend={lut.get('backend')} 时长 {src_d}s -> {out_d}s "
        f"{lut.get('output', {}).get('width')}x{lut.get('output', {}).get('height')}; "
        f"均 RGB {lut.get('mean_rgb')}",
    )
    sheets = report.get("A_enhance", {}).get("comparison_sheets", {})
    gate("enhance.comparison_sheets", len(sheets) >= 3, f"对比图: {sorted(sheets)}")

    rev = report.get("B_review") or {
        "films": {},
        "unmeasured": ["B_review 未跑完"],
        "existing_films_flagged_red": [],
        "red_demo_via_stress_case": False,
    }
    gate("review.three_existing_films", len(rev["films"]) == 3, f"{sorted(rev['films'])}")
    measured = [k for k, v in rev["films"].items() if v["frames"]["count"] == 4]
    gate("review.four_point_frames", len(measured) == 3, f"4 点抽帧: {measured}")
    gate(
        "review.slideshow_red",
        bool(rev["existing_films_flagged_red"]) or rev["red_demo_via_stress_case"],
        f"已有成片判红={rev['existing_films_flagged_red']}, "
        f"压力样本判红={rev['red_demo_via_stress_case']}",
    )
    bad = rev.get("bad_cases", {})
    gate(
        "review.bad_cases_red",
        bool(bad)
        and all(v.get("verdict") == "red" for v in bad.values())
        and all(not v.get("allows_compose") for v in bad.values()),
        f"破图样本判红: {[(k, v.get('verdict')) for k, v in bad.items()]}",
    )
    promise_ok = [
        k
        for k, v in rev["films"].items()
        if (v["promise"] or {}).get("verdict") in ("ok", "violation")
    ]
    gate("review.promise_reconciled", len(promise_ok) == 3, f"与排产前承诺对账: {promise_ok}")

    bl = report.get("C_backlot") or {
        "summary_after_decisions": {},
        "contact_sheet": {},
        "reject_without_reason_status": 0,
        "replay_render": {},
    }
    gate(
        "backlot.approval_written_back",
        bl["summary_after_decisions"]["approved"] == 2
        and bl["summary_after_decisions"]["rejected"] == 1,
        f"通过 {bl['summary_after_decisions']['approved']} / "
        f"否决 {bl['summary_after_decisions']['rejected']} / "
        f"待批 {bl['summary_after_decisions']['pending']} gate={bl['summary_after_decisions']['gate']}",
    )
    gate(
        "backlot.quality_measured",
        bl["summary_after_decisions"]["quality_scored"] == 4,
        f"实测质量分 {bl['summary_after_decisions']['quality_scored']} 格, 均分 "
        f"{bl['summary_after_decisions']['mean_quality']}",
    )
    gate(
        "backlot.reject_needs_reason",
        bl["reject_without_reason_status"] == 400,
        f"空理由否决 → HTTP {bl['reject_without_reason_status']}",
    )
    gate(
        "backlot.contact_sheet",
        bool(bl["contact_sheet"].get("sha256")),
        f"{bl['contact_sheet'].get('path')} sha256={bl['contact_sheet'].get('sha256', '')[:16]}…",
    )
    gate(
        "backlot.replay_video",
        bool(bl["replay_render"].get("ok")) and bool(bl["replay_render"].get("sha256")),
        f"{bl['replay_render'].get('path')} "
        f"{bl['replay_render'].get('duration_s')}s "
        f"sha256={str(bl['replay_render'].get('sha256'))[:16]}…",
    )

    lint = report.get("D_lint") or {"baseline_fail": [], "new_failures": ["D_lint 未跑完"]}
    gate(
        "lint.no_new_failures",
        not lint["new_failures"],
        f"基线 {len(lint['baseline_fail'])} 项失败, 新增 {lint['new_failures']}",
    )
    return gates


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="OMQUALITY 真实 E2E")
    ap.add_argument("--out", default="output/om_quality_e2e")
    ap.add_argument("--fast", action="store_true", help="更小的超分输入(CPU 上省时间)")
    args = ap.parse_args()

    os.environ.setdefault("PATH", os.environ.get("PATH", "") + ":/home/soffy/.local/bin")
    out = Path(args.out)
    if not out.is_absolute():
        out = REPO / out
    out.mkdir(parents=True, exist_ok=True)

    started = time.time()
    report: dict[str, Any] = {
        "task": "OMQUALITY",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.version,
        "ffmpeg": subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True
        ).stdout.splitlines()[0],
        "out_dir": str(out),
    }
    try:
        report["A_enhance"] = section_enhance(out, args.fast)
        report["B_review"] = section_review(out)
        report["C_backlot"] = section_backlot(out)
        report["D_lint"] = section_lint(out)
    finally:
        report["elapsed_s"] = round(time.time() - started, 1)
        report["gates"] = evaluate(report)
        report["artifacts"] = collect_artifacts(out)
        report["passed"] = all(g["ok"] for g in report["gates"])

    manifest = out / "om_quality_e2e_manifest.json"
    manifest.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n================ OMQUALITY E2E 验收 ================")
    for g in report["gates"]:
        print(f"  [{'PASS' if g['ok'] else 'FAIL'}] {g['gate']}: {g['detail']}")
    print(f"  用时 {report['elapsed_s']}s, 产物 {len(report['artifacts'])} 件")
    print(f"  manifest: {manifest}")
    print("====================================================")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
