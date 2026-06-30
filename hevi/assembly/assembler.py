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
from dataclasses import dataclass
from pathlib import Path

from obase.ffmpeg import run as ffmpeg_run


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
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    try:
        return float(out.decode().strip())
    except (ValueError, AttributeError):
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
    except (json.JSONDecodeError, OSError):
        return None
    return None


# ── 单镜头归一化(统一尺寸/帧率/SAR + 音频驱动时长) ─────────────────────


def _normalize_vf(width: int, height: int, fps: int) -> str:
    """统一画面: 等比缩放进 W×H 黑边填充 + 方形像素 + 目标帧率。"""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
        f"setsar=1,fps={fps}"
    )


async def _normalize_shot(
    shot: ShotSegment, idx: int, tmp_dir: Path,
    width: int, height: int, fps: int,
) -> tuple[Path, float]:
    """把单镜头归一化到统一规格 + 目标时长,返回(归一化文件, 实际时长)。

    时长策略: target 比视频短→裁(-t);比视频长→末帧保持(tpad clone)补足。
    """
    src_dur = await probe_duration(shot.video_path)
    out = tmp_dir / f"norm_{idx:04d}.mp4"
    vf = _normalize_vf(width, height, fps)

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

    args += ["-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", str(out)]
    await ffmpeg_run(args=args, expected_output=out)
    return out, actual


# ── 拼接(xfade 转场 / 硬切) ──────────────────────────────────────────


def build_xfade_chain(
    durations: list[float], transition: str, xfade_d: float,
) -> tuple[str, str, float]:
    """构造 N 段 xfade 链 filter_complex。

    返回 (filter_complex, 末级标签, 成片总时长)。
    offset_i = (已合并总时长) - xfade_d。每次 xfade 重叠 xfade_d,故总时长
    = sum(durations) - (N-1)*xfade_d。
    """
    n = len(durations)
    if n == 1:
        return "", "0:v", durations[0]
    parts: list[str] = []
    prev = "[0:v]"
    merged = durations[0]
    for i in range(1, n):
        offset = merged - xfade_d
        out_label = f"[vx{i}]" if i < n - 1 else "[vout]"
        parts.append(
            f"{prev}[{i}:v]xfade=transition={transition}:"
            f"duration={xfade_d}:offset={offset:.3f}{out_label}"
        )
        merged = merged + durations[i] - xfade_d
        prev = out_label
    return ";".join(parts), "[vout]", merged


# ── 音频(响度归一 + BGM ducking) ────────────────────────────────────


def build_audio_filter(
    has_narration: bool, has_bgm: bool, narr_idx: int, bgm_idx: int,
    lufs: float, bgm_gain_db: float, total_dur: float,
) -> tuple[str, str | None]:
    """构造音频 filter_complex: 旁白 loudnorm + BGM 侧链闪避 + amix。

    返回 (filter_complex_片段, 末级音频标签或 None)。
    """
    if not has_narration and not has_bgm:
        return "", None
    if has_narration and not has_bgm:
        return f"[{narr_idx}:a]loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]", "[aout]"
    if has_bgm and not has_narration:
        return (
            f"[{bgm_idx}:a]volume={bgm_gain_db}dB,"
            f"afade=t=out:st={max(0, total_dur - 2):.2f}:d=2[aout]", "[aout]"
        )
    # 二者都有: 旁白归一 → 作为侧链压 BGM(旁白响时压低 BGM) → amix
    f = (
        f"[{narr_idx}:a]loudnorm=I={lufs}:TP=-1.5:LRA=11,asplit=2[narr][narrsc];"
        f"[{bgm_idx}:a]volume={bgm_gain_db}dB[bgmv];"
        f"[bgmv][narrsc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[bgmduck];"
        f"[narr][bgmduck]amix=inputs=2:duration=first:dropout_transition=2[aout]"
    )
    return f, "[aout]"


# ── 主装配 ──────────────────────────────────────────────────────────


async def assemble_longvideo(
    *,
    shots: list[ShotSegment],
    output_path: Path,
    narration_audio: Path | None = None,
    bgm_path: Path | None = None,
    subtitle_path: Path | None = None,
    width: int = 832,
    height: int = 480,
    fps: int = 24,
    transition: str = "fade",
    transition_duration: float = 0.5,
    loudness_lufs: float = -14.0,
    bgm_gain_db: float = -18.0,
) -> Path:
    """装配长视频成片。返回 output_path。

    步骤: ①逐镜头归一化(统一规格 + 音频驱动时长) ②xfade/硬切拼接(重编码)
    ③旁白 loudnorm + BGM ducking 混音 ④可选烧字幕。
    """
    import tempfile

    if not shots:
        raise ValueError("assemble_longvideo: no shots")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hevi_assemble_") as td:
        tmp_dir = Path(td)

        # ① 归一化每个镜头
        norm: list[tuple[Path, float]] = []
        for i, shot in enumerate(shots):
            norm.append(await _normalize_shot(shot, i, tmp_dir, width, height, fps))
        durations = [d for _, d in norm]

        # ② 视频拼接
        silent = tmp_dir / "video_silent.mp4"
        xfade_d = min(transition_duration, min(durations) / 2) if len(durations) > 1 else 0.0
        use_xfade = transition != "cut" and len(durations) > 1 and xfade_d > 0.05

        if use_xfade:
            fc, vlabel, _ = build_xfade_chain(durations, transition, xfade_d)
            args = ["-y"]
            for p, _ in norm:
                args += ["-i", str(p)]
            args += ["-filter_complex", fc, "-map", vlabel,
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                     "-pix_fmt", "yuv420p", str(silent)]
            await ffmpeg_run(args=args, expected_output=silent)
        else:
            # 硬切: 归一化后规格一致,concat demuxer + 重编码(稳妥)
            concat_list = tmp_dir / "concat.txt"
            concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p, _ in norm))
            args = ["-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", str(silent)]
            await ffmpeg_run(args=args, expected_output=silent)

        video_dur = await probe_duration(silent)

        # ③ 音频混音
        has_narr = narration_audio is not None and narration_audio.exists()
        has_bgm = bgm_path is not None and bgm_path.exists()
        if not has_narr and not has_bgm:
            muxed = silent
        else:
            muxed = tmp_dir / "muxed.mp4"
            args = ["-y", "-i", str(silent)]
            narr_idx = bgm_idx = -1
            nxt = 1
            if has_narr:
                args += ["-i", str(narration_audio)]
                narr_idx = nxt
                nxt += 1
            if has_bgm:
                args += ["-i", str(bgm_path)]
                bgm_idx = nxt
                nxt += 1
            af, alabel = build_audio_filter(
                has_narr, has_bgm, narr_idx, bgm_idx,
                loudness_lufs, bgm_gain_db, video_dur,
            )
            assert alabel is not None  # has_narr or has_bgm → 必非空
            args += ["-filter_complex", af, "-map", "0:v", "-map", alabel,
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                     "-shortest", str(muxed)]
            await ffmpeg_run(args=args, expected_output=muxed)

        # ④ 字幕(可选)
        if subtitle_path is not None and subtitle_path.exists():
            from hevi.assembly.subtitle_burner import get_subtitle_filter

            final = tmp_dir / "final.mp4"
            args = ["-y", "-i", str(muxed), "-vf", get_subtitle_filter(subtitle_path),
                    "-c:a", "copy", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "20", "-pix_fmt", "yuv420p", str(final)]
            await ffmpeg_run(args=args, expected_output=final)
            muxed = final

        import shutil
        shutil.move(str(muxed), str(output_path))
    return output_path
