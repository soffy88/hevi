"""hevi 原生长视频装配器 — 取代"硬切 + 整轨盲贴"的回退路径。

RFC-002 P0-2/P1-4/P1-5 收敛于此:
  - 音频驱动镜头时长(item 2): 每镜头按其对白音频时长裁/补(末帧保持)。
  - 统一归一化 + xfade 转场(item 4): 所有镜头统一 scale/pad/setsar/fps,
    用 xfade 重编码拼接,杜绝跨编码 `-c:v copy` 花屏;transition="cut" 时退化为硬切。
  - 响度归一 + BGM ducking(item 5): 旁白 EBU R128 -14 LUFS;BGM 侧链闪避 + fade。

设计为纯 ffmpeg 确定性操作,可不依赖 GPU 单测(用 lavfi 合成片验证)。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from obase.ffmpeg import run as ffmpeg_run

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ShotSegment:
    """一个镜头片段 + 其目标显示时长(由对白音频驱动,None 则用视频原时长)。"""

    video_path: Path
    target_duration: float | None = None  # 秒;None=保持视频原时长


# ── 探测 ────────────────────────────────────────────────────────────────


async def probe_duration(path: Path) -> float:
    """ffprobe 取媒体时长(秒)。失败返回 0.0。"""
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except ValueError, AttributeError:
        return 0.0


def load_timing_manifest(audio_path: Path) -> list[float] | None:
    """读音频旁的逐句时长清单(injected_audio_fn 落盘的 side-channel)。

    清单文件: <audio_path>.timing.json,内容 {"durations": [s, s, ...]}。
    """
    manifest = audio_path.with_suffix(audio_path.suffix + ".timing.json")
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text())
        durs = data.get("durations")
        if isinstance(durs, list) and all(isinstance(d, (int, float)) for d in durs):
            return [float(d) for d in durs]
    except json.JSONDecodeError, OSError:
        return None
    return None


# ── 单镜头归一化(统一尺寸/帧率/SAR + 音频驱动时长 + 跨 provider 亮度归一) ─────


def _normalize_vf(width: int, height: int, fps: int, *, brightness: float = 0.0) -> str:
    """统一画面: 等比缩放进 W×H 黑边填充 + 方形像素 + 目标帧率 + 可选亮度修正。"""
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1,fps={fps}"
    )
    if brightness:
        vf += f",eq=brightness={brightness:.4f}"
    return vf


def _measure_avg_luma(path: Path) -> float | None:
    """取视频中点一帧,算平均灰度亮度(0-255)。

    跨 provider 调色统一(HEVI 路线图 Phase2 #37)的度量基准——不同 provider 对
    同一 prompt 输出的整体明暗有系统性差异,直接硬切/xfade 拼接会看出接缝。采样
    单帧而非逐帧统计,足够代表整个镜头的曝光基调,换来速度。失败(无法探测/
    解码)→ None,不阻断装配。
    """
    import subprocess
    import tempfile

    from PIL import Image

    dur_out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        dur = float(dur_out)
    except ValueError:
        return None
    with tempfile.TemporaryDirectory(prefix="luma_") as td:
        frame = Path(td) / "f.png"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{dur / 2:.3f}",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(frame),
            ],
            capture_output=True,
        )
        if not frame.exists():
            return None
        with Image.open(frame) as im:
            hist = im.convert("L").histogram()
            total = sum(hist)
            if total == 0:
                return None
            return sum(i * c for i, c in enumerate(hist)) / total


def _brightness_correction(luma: float, target_luma: float, *, max_delta: float = 0.15) -> float:
    """luma/target_luma 是 0-255 平均灰度。ffmpeg `eq` 的 brightness 参数是 -1..1
    的加性偏移。把两者的相对差值转成修正量,夹在 ±max_delta 内——只做"缩小组间
    差异",不做激进的重新打光,避免过度修正把正常的明暗节奏(比如刻意的夜戏)
    拉平成一个亮度。
    """
    diff = (target_luma - luma) / 255.0
    return max(-max_delta, min(max_delta, diff))


async def _normalize_shot(
    shot: ShotSegment,
    idx: int,
    tmp_dir: Path,
    width: int,
    height: int,
    fps: int,
    *,
    brightness: float = 0.0,
) -> tuple[Path, float]:
    """把单镜头归一化到统一规格 + 目标时长 + 亮度修正,返回(归一化文件, 实际时长)。

    时长策略: target 比视频短→裁(-t);比视频长→末帧保持(tpad clone)补足。
    """
    src_dur = await probe_duration(shot.video_path)
    out = tmp_dir / f"norm_{idx:04d}.mp4"
    vf = _normalize_vf(width, height, fps, brightness=brightness)

    target = shot.target_duration
    args = ["-y", "-i", str(shot.video_path)]
    if target and target > 0:
        if target > src_dur + 0.05:
            # 视频比对白短: 末帧保持补足(clone)到 target
            vf += f",tpad=stop_mode=clone:stop_duration={target - src_dur:.3f}"
        # 裁/定长到 target(末帧保持后再定长保证精确)
        args += ["-vf", vf, "-t", f"{target:.3f}"]
        actual = target
    else:
        args += ["-vf", vf]
        actual = src_dur

    args += [
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        str(out),
    ]
    await ffmpeg_run(args=args, expected_output=out)
    return out, actual


# ── 拼接(xfade 转场 / 硬切) ──────────────────────────────────────────


def build_xfade_chain(
    durations: list[float],
    transition: str,
    xfade_d: float | list[float],
) -> tuple[str, str, float]:
    """构造 N 段 xfade 链 filter_complex。

    返回 (filter_complex, 末级标签, 成片总时长)。
    offset_i = (已合并总时长) - xfade_d_i。每次 xfade 重叠 xfade_d_i,故总时长
    = sum(durations) - sum(xfade_d_i)。

    `xfade_d` 可以是单一值(所有转场同一重叠时长,原有行为)或逐转场的列表——
    BGM 节拍对齐(HEVI 路线图 Phase2 #37)按节拍点微调每处转场的重叠时长,不是
    整条链统一一个数,故需要这个泛化。
    """
    n = len(durations)
    if n == 1:
        return "", "0:v", durations[0]
    xfade_ds = xfade_d if isinstance(xfade_d, list) else [xfade_d] * (n - 1)
    if len(xfade_ds) != n - 1:
        raise ValueError(
            f"xfade_d list must have {n - 1} entries for {n} shots, got {len(xfade_ds)}"
        )
    parts: list[str] = []
    prev = "[0:v]"
    merged = durations[0]
    for i in range(1, n):
        d = xfade_ds[i - 1]
        offset = merged - d
        out_label = f"[vx{i}]" if i < n - 1 else "[vout]"
        parts.append(
            f"{prev}[{i}:v]xfade=transition={transition}:duration={d}:offset={offset:.3f}{out_label}"
        )
        merged = merged + durations[i] - d
        prev = out_label
    return ";".join(parts), "[vout]", merged


# ── 音频(响度归一 + BGM ducking) ────────────────────────────────────


def build_audio_filter(
    has_narration: bool,
    has_bgm: bool,
    narr_idx: int,
    bgm_idx: int,
    lufs: float,
    bgm_gain_db: float,
    total_dur: float,
    *,
    has_sfx: bool = False,
    sfx_idx: int = -1,
    sfx_gain_db: float = -6.0,
) -> tuple[str, str | None]:
    """构造音频 filter_complex: 旁白 loudnorm + BGM 侧链闪避(+可选音效)+ amix。

    音效(sfx)是一次性提示音,不参与旁白侧链闪避(非持续底噪,闪避无意义),只按固定
    电平叠加进混音;有旁白时随旁白轨一起 amix,无旁白时随 BGM(若有)一起 amix。
    返回 (filter_complex_片段, 末级音频标签或 None)。
    """
    if not has_narration and not has_bgm and not has_sfx:
        return "", None

    # 单轨情形(其余两轨都无):narration 走 loudnorm+apad;bgm/sfx 走 volume+fade。
    if has_narration and not has_bgm and not has_sfx:
        return (
            f"[{narr_idx}:a]loudnorm=I={lufs}:TP=-1.5:LRA=11,"
            f"apad=whole_dur={max(total_dur, 0.1):.3f}[aout]",
            "[aout]",
        )
    if has_bgm and not has_narration and not has_sfx:
        return (
            f"[{bgm_idx}:a]volume={bgm_gain_db}dB,"
            f"afade=t=out:st={max(0, total_dur - 2):.2f}:d=2[aout]",
            "[aout]",
        )
    if has_sfx and not has_narration and not has_bgm:
        return (f"[{sfx_idx}:a]volume={sfx_gain_db}dB[aout]", "[aout]")

    # 多轨:旁白(若有)归一 + 侧链压 BGM;音效独立轨,最后统一 amix。asplit 仅在确实
    # 要喂侧链时才用(否则会留一个没人接的 output pad)。
    parts: list[str] = []
    mix_inputs: list[str] = []
    if has_narration:
        if has_bgm:
            parts.append(f"[{narr_idx}:a]loudnorm=I={lufs}:TP=-1.5:LRA=11,asplit=2[narr][narrsc]")
            parts.append(f"[{bgm_idx}:a]volume={bgm_gain_db}dB[bgmv]")
            parts.append(
                "[bgmv][narrsc]sidechaincompress=threshold=0.03:ratio=8:"
                "attack=20:release=300[bgmduck]"
            )
            parts.append(f"[narr]apad=whole_dur={max(total_dur, 0.1):.3f}[narrp]")
            mix_inputs.append("[narrp]")
            mix_inputs.append("[bgmduck]")
        else:
            parts.append(
                f"[{narr_idx}:a]loudnorm=I={lufs}:TP=-1.5:LRA=11,"
                f"apad=whole_dur={max(total_dur, 0.1):.3f}[narrp]"
            )
            mix_inputs.append("[narrp]")
    elif has_bgm:
        parts.append(f"[{bgm_idx}:a]volume={bgm_gain_db}dB[bgmv]")
        mix_inputs.append("[bgmv]")
    if has_sfx:
        parts.append(f"[{sfx_idx}:a]volume={sfx_gain_db}dB[sfxv]")
        mix_inputs.append("[sfxv]")

    n = len(mix_inputs)
    parts.append(
        "".join(mix_inputs) + f"amix=inputs={n}:duration=longest:dropout_transition=2[aout]"
    )
    return ";".join(parts), "[aout]"


# ── 主装配 ──────────────────────────────────────────────────────────


async def compose_avatar_broll(
    *,
    broll_video: Path,
    avatar_video: Path,
    output_path: Path,
    position: str = "br",  # tl|tr|bl|br 角落
    scale: float = 0.28,  # 数字人占画面宽度比例
) -> Path:
    """RFC-002 item 11: 数字人讲解 + B-roll 画中画合成。

    B-roll 全屏铺底, 数字人(Duix 讲解)缩放到角落叠加; 音频取数字人轨(含口型对白)。
    纯 ffmpeg overlay, 确定性可测。
    """
    pos = {
        "tl": "10:10",
        "tr": "W-w-10:10",
        "bl": "10:H-h-10",
        "br": "W-w-10:H-h-10",
    }.get(position, "W-w-10:H-h-10")
    fc = f"[1:v]scale=iw*{scale}:-1[av];[0:v][av]overlay={pos}:format=auto[vout]"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-y",
        "-i",
        str(broll_video),
        "-i",
        str(avatar_video),
        "-filter_complex",
        fc,
        "-map",
        "[vout]",
        "-map",
        "1:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(output_path),
    ]
    await ffmpeg_run(args=args, expected_output=output_path)
    return output_path


async def assemble_longvideo(
    *,
    shots: list[ShotSegment],
    output_path: Path,
    narration_audio: Path | None = None,
    bgm_path: Path | None = None,
    sfx_path: Path | None = None,
    subtitle_path: Path | None = None,
    subtitle_style: str = "default",
    width: int = 832,
    height: int = 480,
    fps: int = 24,
    transition: str = "fade",
    transition_duration: float = 0.5,
    loudness_lufs: float = -14.0,
    bgm_gain_db: float = -18.0,
    sfx_gain_db: float = -6.0,
    color_normalize: bool = True,
    bgm_beat_align: bool = True,
) -> Path:
    """装配长视频成片。返回 output_path。

    步骤: ①逐镜头归一化(统一规格 + 音频驱动时长 + 跨 provider 亮度归一)
    ②xfade/硬切拼接(重编码,转场可选贴 BGM 节拍点) ③旁白 loudnorm + BGM
    ducking(+可选音效)混音 ④可选烧字幕(可选样式)。

    `color_normalize`(HEVI 路线图 Phase2 #37):度量每个原始镜头的平均亮度,往
    全片平均值方向做一个有界修正(±0.15,ffmpeg eq brightness 单位),缓解不同
    provider 输出的系统性明暗差异造成的混剪接缝。只做亮度,不做色相/饱和度——
    没有跨 provider 校准数据支撑更激进的调色,不该编造。
    `bgm_beat_align`:有 BGM 时用 librosa 检测节拍,转场点贴最近节拍(±0.3s 内),
    检测失败/无 BGM 时静默回退成原有的统一转场时长,不阻断装配。
    """
    import tempfile

    if not shots:
        raise ValueError("assemble_longvideo: no shots")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hevi_assemble_") as td:
        tmp_dir = Path(td)

        # 跨 provider 调色统一:先测原始镜头的亮度,算出每镜头的修正量,直接并入
        # 下面的归一化编码(①同一趟 ffmpeg 调用完成,不需要额外一趟重编码)。
        brightness_by_shot = [0.0] * len(shots)
        if color_normalize:
            import asyncio

            lumas = await asyncio.gather(
                *(asyncio.to_thread(_measure_avg_luma, s.video_path) for s in shots)
            )
            valid = [x for x in lumas if x is not None]
            if valid:
                target_luma = sum(valid) / len(valid)
                brightness_by_shot = [
                    _brightness_correction(lm, target_luma) if lm is not None else 0.0
                    for lm in lumas
                ]

        # ① 归一化每个镜头
        norm: list[tuple[Path, float]] = []
        for i, shot in enumerate(shots):
            norm.append(
                await _normalize_shot(
                    shot, i, tmp_dir, width, height, fps, brightness=brightness_by_shot[i]
                )
            )
        durations = [d for _, d in norm]

        # ② 视频拼接
        silent = tmp_dir / "video_silent.mp4"
        xfade_d: float | list[float] = (
            min(transition_duration, min(durations) / 2) if len(durations) > 1 else 0.0
        )
        use_xfade = transition != "cut" and len(durations) > 1 and xfade_d > 0.05

        if use_xfade and bgm_beat_align and bgm_path is not None and bgm_path.exists():
            import asyncio

            from hevi.assembly.beat_align import beat_snapped_xfade_durations, detect_beat_times

            beats = await asyncio.to_thread(detect_beat_times, bgm_path)
            if beats:
                xfade_d = beat_snapped_xfade_durations(durations, base_xfade_d=xfade_d, beats=beats)

        if use_xfade:
            fc, vlabel, _ = build_xfade_chain(durations, transition, xfade_d)
            args = ["-y"]
            for p, _ in norm:
                args += ["-i", str(p)]
            args += [
                "-filter_complex",
                fc,
                "-map",
                vlabel,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                str(silent),
            ]
            await ffmpeg_run(args=args, expected_output=silent)
        else:
            # 硬切: 归一化后规格一致,concat demuxer + 重编码(稳妥)
            concat_list = tmp_dir / "concat.txt"
            concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p, _ in norm))
            args = [
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
                str(silent),
            ]
            await ffmpeg_run(args=args, expected_output=silent)

        video_dur = await probe_duration(silent)

        # ③ 音频混音
        has_narr = narration_audio is not None and narration_audio.exists()
        has_bgm = bgm_path is not None and bgm_path.exists()
        has_sfx = sfx_path is not None and sfx_path.exists()
        if not has_narr and not has_bgm and not has_sfx:
            muxed = silent
        else:
            muxed = tmp_dir / "muxed.mp4"
            args = ["-y", "-i", str(silent)]
            narr_idx = bgm_idx = sfx_idx = -1
            nxt = 1
            if has_narr:
                args += ["-i", str(narration_audio)]
                narr_idx = nxt
                nxt += 1
            if has_bgm:
                args += ["-i", str(bgm_path)]
                bgm_idx = nxt
                nxt += 1
            if has_sfx:
                args += ["-i", str(sfx_path)]
                sfx_idx = nxt
                nxt += 1
            af, alabel = build_audio_filter(
                has_narr,
                has_bgm,
                narr_idx,
                bgm_idx,
                loudness_lufs,
                bgm_gain_db,
                video_dur,
                has_sfx=has_sfx,
                sfx_idx=sfx_idx,
                sfx_gain_db=sfx_gain_db,
            )
            assert alabel is not None  # has_narr/has_bgm/has_sfx 任一 → 必非空
            args += [
                "-filter_complex",
                af,
                "-map",
                "0:v",
                "-map",
                alabel,
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(muxed),
            ]
            await ffmpeg_run(args=args, expected_output=muxed)

        # ④ 字幕(可选)
        if subtitle_path is not None and subtitle_path.exists():
            from hevi.assembly.subtitle_burner import get_subtitle_filter

            final = tmp_dir / "final.mp4"
            args = [
                "-y",
                "-i",
                str(muxed),
                "-vf",
                get_subtitle_filter(subtitle_path, style=subtitle_style),
                "-c:a",
                "copy",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                str(final),
            ]
            await ffmpeg_run(args=args, expected_output=final)
            muxed = final

        import shutil

        shutil.move(str(muxed), str(output_path))

    # RFC-002 item 14: 接入 cover_extractor —— 成片旁产出封面帧(供画廊缩略图)。
    try:
        from hevi.assembly.cover_extractor import extract_cover

        await extract_cover(output_path, output_path.with_suffix(".cover.jpg"))
    except Exception as ce:
        logger.warning("cover extraction skipped (non-critical): %s", ce)  # 降级但不静默吞
    return output_path
