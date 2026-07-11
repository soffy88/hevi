"""L8 字幕与剪辑合成 —— 全部上游产物 → final.mp4。见 HEVI-SPEC-01 §9。
纯确定性代码层,零 LLM(VLM 终审除外,那是审核不是生成)。

流程:
  1. 每个 shot 的静态帧(L6 frame_manifest)→ zoompan(camera.movement 决定运镜)→ shot.mp4
  2. L3 逐行音频文件 + timeline.gaps 静音 → 拼成一条连续旁白轨
  3. L7 music_plan 的逐幕 BGM cue → 按各幕时长裁剪/循环 + acrossfade 拼成一条 BGM 主轨;
     SFX cue → adelay 到各自 t_start_ms + amix 成一条 SFX 主轨
  4. timeline + script → SRT(直接用已知的精确时间戳,不走 ASR 对齐)
  5. 调用 hevi.assembly.assembler.assemble_longvideo 完成拼接 + 混音(旁白 loudnorm +
     BGM 侧链闪避,duck 到 spec 要求的 -22dB,非 assembler 默认的 -18dB)+ 烧字幕 + 导出

G8 终审门(纯代码为主,VLM 终审除外):时长偏差、黑帧检测、音频削波检测、
ASR 全片反打(旁白轨,不含 BGM/SFX,避免背景音乐干扰识别)、VLM 抽帧终审。
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any

from obase.ffmpeg import run as ffmpeg_run

from hevi.assembly.assembler import ShotSegment, assemble_longvideo, probe_duration
from hevi.tongjian.chapter_ir import _extract_json_obj
from hevi.tongjian.schemas import (
    Constitution,
    FinalVideo,
    FrameManifest,
    GateResult,
    MusicPlan,
    Script,
    Shot,
    ShotFrame,
    ShotList,
    Timeline,
)
from hevi.tongjian.voiceover import _char_error_rate

logger = logging.getLogger(__name__)

_BGM_DUCK_GAIN_DB = -22.0  # spec §7:BGM 在人声段自动 duck 至 -22dB(assembler 默认 -18)
_BGM_CROSSFADE_S = 1.5  # spec §8:音乐切换点交叉淡入淡出 1.5s

_ZOOM_MAX = 1.15
_ZOOM_RATE = 0.0008

_DURATION_DEVIATION_THRESHOLD = 0.20
_BLACK_FRAME_MIN_DURATION_S = 1.0  # 超过此时长的黑场才算异常(转场本身很短)
_CLIP_MAX_VOLUME_THRESHOLD_DB = -0.5
_VLM_SAMPLE_FRAMES = 6

# spec §9.1:字幕/画面样式由宪法 visual_style 决定 —— 目前只把 aspect_ratio 接到画幅
# 尺寸选择;subtitle_burner 的样式预设(default/bold_yellow/large_white/compact)是
# 固定枚举,不支持 visual_style.art_direction 任意映射,暂用 "default"(P1 简化)。
_ASPECT_RATIO_DIMENSIONS: dict[str, tuple[int, int]] = {
    "16:9": (832, 480),
    "9:16": (480, 832),
    "1:1": (720, 720),
}
_DEFAULT_DIMENSIONS = (832, 480)


def _dimensions_for_aspect_ratio(aspect_ratio: str) -> tuple[int, int]:
    return _ASPECT_RATIO_DIMENSIONS.get(aspect_ratio, _DEFAULT_DIMENSIONS)


_FINAL_AUDIT_PROMPT_TEMPLATE = """你是短片终审。下面是从成片里按时间顺序抽取的 {n} 帧画面。
请判断整体美术风格/色调是否一致,是否有明显穿帮或崩坏画面。

只输出 JSON: {{"consistent": true/false, "issues": ["..."]}}"""


# ── 字幕(SRT,直接用已知时间戳)──────────────────────────────────────────


def _srt_timestamp(ms: int) -> str:
    ms = max(ms, 0)
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def generate_srt(timeline: Timeline, script: Script) -> str:
    """timeline.audio_segments 的时间戳是配音阶段真实产出的,直接用,不需要 ASR 对齐。"""
    lines_by_id = {ln.line_id: ln for ln in script.lines}
    entries: list[str] = []
    idx = 0
    for seg in timeline.audio_segments:
        line = lines_by_id.get(seg.line_id)
        if line is None or not line.text:
            continue
        idx += 1
        text = line.text
        if line.type == "dialogue" and line.speaker != "NARRATOR":
            text = f"{line.speaker}: {text}"
        entries.append(
            f"{idx}\n{_srt_timestamp(seg.t_start_ms)} --> {_srt_timestamp(seg.t_end_ms)}\n{text}\n"
        )
    return "\n".join(entries)


# ── 逐 shot Ken Burns 静态帧 → 视频片段(§9.2)────────────────────────────


def _zoompan_filter(movement: str, width: int, height: int, fps: int, duration_s: float) -> str:
    """把 camera.movement(L4 分镜定的运镜)转成 ffmpeg zoompan 表达式。"""
    frames = max(round(duration_s * fps), 1)
    up_w, up_h = width * 2, height * 2

    if movement == "slow_push_in":
        z, x, y = f"min(zoom+{_ZOOM_RATE},{_ZOOM_MAX})", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif movement == "slow_pull_out":
        z = f"if(eq(on,0),{_ZOOM_MAX},max(zoom-{_ZOOM_RATE},1.0))"
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    elif movement == "pan_left":
        z, x, y = str(_ZOOM_MAX), f"(iw-iw/zoom)*(1-on/{frames})", "ih/2-(ih/zoom/2)"
    elif movement == "pan_right":
        z, x, y = str(_ZOOM_MAX), f"(iw-iw/zoom)*(on/{frames})", "ih/2-(ih/zoom/2)"
    elif movement == "tilt_up":
        z, x, y = str(_ZOOM_MAX), "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-on/{frames})"
    elif movement == "tilt_down":
        z, x, y = str(_ZOOM_MAX), "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(on/{frames})"
    else:  # static
        z, x, y = "1.0", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"

    return (
        f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase,"
        f"crop={up_w}:{up_h},"
        f"zoompan=z='{z}':d={frames}:x='{x}':y='{y}':s={width}x{height}:fps={fps},"
        "format=yuv420p"
    )


async def render_shot_clip(
    shot: Shot,
    frame: ShotFrame,
    *,
    output_dir: Path,
    width: int = 832,
    height: int = 480,
    fps: int = 24,
) -> Path:
    """静态帧 → 带运镜的短视频片段。时长只需大致准确 —— assemble_longvideo 的
    ShotSegment.target_duration 会再按对白音频精确裁剪/补足一次。
    """
    duration_s = max((shot.t_end_ms - shot.t_start_ms) / 1000.0, 0.1)
    vf = _zoompan_filter(shot.camera.movement, width, height, fps, duration_s)
    out = output_dir / f"{shot.shot_id.lower()}.mp4"
    args = [
        "-loop",
        "1",
        "-i",
        frame.frame_path,
        "-t",
        f"{duration_s:.3f}",
        "-vf",
        vf,
        "-r",
        str(fps),
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        str(out),
    ]
    await ffmpeg_run(args=args, expected_output=out)
    return out


# ── 旁白轨(逐行音频 + gaps 静音 → 一条连续 wav)──────────────────────────


async def concat_narration_track(
    timeline: Timeline,
    audio_dir: Path,
    *,
    output_dir: Path,
) -> Path | None:
    if not timeline.audio_segments:
        return None

    gaps_by_after = {g.after_line: g for g in timeline.gaps}
    inputs: list[str] = []
    filter_parts: list[str] = []
    concat_labels: list[str] = []
    idx = 0
    for seg in timeline.audio_segments:
        inputs += ["-i", str(audio_dir / seg.file)]
        concat_labels.append(f"[{idx}:a]")
        idx += 1
        gap = gaps_by_after.get(seg.line_id)
        if gap:
            sil_label = f"sil{idx}"
            filter_parts.append(
                f"anullsrc=r=44100:cl=mono:d={gap.duration_ms / 1000:.3f}[{sil_label}]"
            )
            concat_labels.append(f"[{sil_label}]")

    n = len(concat_labels)
    filter_complex = ";".join(
        [*filter_parts, "".join(concat_labels) + f"concat=n={n}:v=0:a=1[aout]"]
    )
    out = output_dir / "narration.wav"
    args = [*inputs, "-filter_complex", filter_complex, "-map", "[aout]", str(out)]
    await ffmpeg_run(args=args, expected_output=out)
    return out


# ── BGM/SFX 主轨(L7 music_plan 的多条 cue → 各一条单轨)──────────────────


async def mix_bgm_master(
    music_plan: MusicPlan,
    *,
    output_dir: Path,
    crossfade_s: float = _BGM_CROSSFADE_S,
) -> Path | None:
    """按每幕时长裁剪/循环各自的 BGM,幕间用 acrossfade 交叉淡入淡出拼成一条主轨。"""
    cues = [c for c in music_plan.cues if c.bgm_path and Path(c.bgm_path).exists()]
    if not cues:
        return None

    segment_paths: list[Path] = []
    for cue in cues:
        dur_s = max((cue.t_end_ms - cue.t_start_ms) / 1000.0, 0.1)
        seg_out = output_dir / f"bgm_act{cue.act}.wav"
        args = ["-stream_loop", "-1", "-i", cue.bgm_path, "-t", f"{dur_s:.3f}", str(seg_out)]
        await ffmpeg_run(args=args, expected_output=seg_out)
        segment_paths.append(seg_out)

    out = output_dir / "bgm_master.wav"
    if len(segment_paths) == 1:
        shutil.copy(segment_paths[0], out)
        return out

    inputs: list[str] = []
    for p in segment_paths:
        inputs += ["-i", str(p)]
    parts: list[str] = []
    prev = "[0:a]"
    for i in range(1, len(segment_paths)):
        out_label = f"[ax{i}]" if i < len(segment_paths) - 1 else "[aout]"
        parts.append(f"{prev}[{i}:a]acrossfade=d={crossfade_s}:c1=tri:c2=tri{out_label}")
        prev = out_label
    args = [*inputs, "-filter_complex", ";".join(parts), "-map", "[aout]", str(out)]
    await ffmpeg_run(args=args, expected_output=out)
    return out


async def mix_sfx_master(
    music_plan: MusicPlan,
    total_duration_ms: int,
    *,
    output_dir: Path,
) -> Path | None:
    """每个 SFX cue 延时到其 t_start_ms,amix 成一条覆盖全片时长的音效轨。"""
    cues = [c for c in music_plan.sfx if c.sfx_path and Path(c.sfx_path).exists()]
    if not cues:
        return None

    inputs: list[str] = []
    parts: list[str] = []
    labels: list[str] = []
    for i, cue in enumerate(cues):
        inputs += ["-i", cue.sfx_path]
        parts.append(f"[{i}:a]adelay={max(cue.t_start_ms, 0)}:all=1[sfx{i}]")
        labels.append(f"[sfx{i}]")

    n = len(labels)
    total_s = max(total_duration_ms, 1) / 1000.0
    # -t only truncates — it can't extend a shorter mix, so pad explicitly with apad.
    parts.append("".join(labels) + f"amix=inputs={n}:duration=longest:dropout_transition=0[mixed]")
    parts.append(f"[mixed]apad=whole_dur={total_s:.3f}[aout]")
    out = output_dir / "sfx_master.wav"
    args = [
        *inputs,
        "-filter_complex",
        ";".join(parts),
        "-map",
        "[aout]",
        "-t",
        f"{total_s:.3f}",
        str(out),
    ]
    await ffmpeg_run(args=args, expected_output=out)
    return out


# ── 主装配 ───────────────────────────────────────────────────────────────


def _ffprobe_dur_sync(p: Path) -> float:
    import subprocess

    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(p),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


def _xfade_concat_clips(
    clips: list[Path], out: Path, width: int, height: int, fps: int, crossfade: float = 0.5
) -> None:
    """把各镜头 talking clip(自带音轨)用 xfade/acrossfade 溶解拼接。"""
    import subprocess

    durs = [_ffprobe_dur_sync(c) for c in clips]
    inputs: list[str] = []
    for c in clips:
        inputs += ["-i", str(c)]
    n = len(clips)
    scale = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}"
    if n == 1:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                *inputs,
                "-vf",
                scale,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(out),
            ],
            check=True,
            capture_output=True,
        )
        return
    vf, af = [], []
    for i in range(n):
        vf.append(f"[{i}:v]{scale},setsar=1[cv{i}]")
    prev_v, prev_a = "[cv0]", "[0:a]"
    cum = durs[0]
    for i in range(1, n):
        off = max(cum - crossfade, 0.0)
        vout = f"[v{i}]" if i < n - 1 else "[vout]"
        aout = f"[a{i}]" if i < n - 1 else "[aout]"
        vf.append(
            f"{prev_v}[cv{i}]xfade=transition=fade:duration={crossfade}:offset={off:.3f}{vout}"
        )
        af.append(f"{prev_a}[{i}:a]acrossfade=d={crossfade}{aout}")
        prev_v, prev_a = vout, aout
        cum = cum + durs[i] - crossfade
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            ";".join(vf + af),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(out),
        ],
        check=True,
        capture_output=True,
    )


async def _assemble_avatar_clips(
    shotlist: ShotList,
    frame_manifest: FrameManifest,
    timeline: Timeline,
    script: Script,
    constitution: Constitution,
    *,
    output_dir: Path,
    width: int,
    height: int,
    fps: int,
    vlm: Any = None,
) -> tuple[FinalVideo, GateResult]:
    """L8 avatar 装配:各镜 talking clip(自带配音+口型)→ xfade 溶解拼接 + 字幕。旁白/对白音
    已在 clip 内,不再另配旁白轨;BGM 留待后续(可在此叠加低音量 bgm)。"""
    frames_by_shot = {f.shot_id: f for f in frame_manifest.frames}
    clips = [
        Path(f.clip_path)
        for shot in shotlist.shots
        if (f := frames_by_shot.get(shot.shot_id)) and f.clip_path and Path(f.clip_path).exists()
    ]
    if not clips:
        raise RuntimeError("avatar 装配:无可用 talking clip(L6 应已产出 clip_path)")

    final_path = output_dir / "final.mp4"
    # 用 clip 的原生分辨率(L6 resolution 参数决定,如 720P/1080P),不降到宪法画幅默认档。
    import subprocess as _sp

    _wh = _sp.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(clips[0]),
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        cw, ch = (int(x) for x in _wh.split("x")[:2])
    except Exception:
        cw, ch = width, height
    _xfade_concat_clips(clips, final_path, cw, ch, fps, crossfade=0.5)

    srt_path = output_dir / "subtitles.srt"
    srt_path.write_text(generate_srt(timeline, script), encoding="utf-8")
    duration_ms = round(await probe_duration(final_path) * 1000)
    final_video = FinalVideo(
        video_path=str(final_path),
        cover_path="",
        srt_path=str(srt_path),
        duration_ms=duration_ms,
    )
    errors: list[str] = []
    if duration_ms <= 0:
        errors.append("成片时长为 0")
    missing = len(shotlist.shots) - len(clips)
    warnings = [f"{missing} 个镜头缺 talking clip,已跳过"] if missing else []
    return final_video, GateResult(passed=not errors, errors=errors, warnings=warnings)


async def build_final_video(
    shotlist: ShotList,
    frame_manifest: FrameManifest,
    timeline: Timeline,
    script: Script,
    music_plan: MusicPlan,
    constitution: Constitution,
    *,
    audio_dir: Path,
    output_dir: Path,
    width: int | None = None,
    height: int | None = None,
    fps: int = 24,
    vlm: Any = None,
) -> tuple[FinalVideo, GateResult]:
    """L8 主入口:逐 shot 视频化 → 旁白/BGM/SFX 主轨 → 字幕 → assemble_longvideo → G8 门。

    width/height 缺省时按 constitution.visual_style.aspect_ratio 选取画幅尺寸。
    """
    if width is None or height is None:
        width, height = _dimensions_for_aspect_ratio(constitution.visual_style.aspect_ratio)
    output_dir.mkdir(parents=True, exist_ok=True)
    frames_by_shot = {f.shot_id: f for f in frame_manifest.frames}

    # avatar 渲染模式(L6 cloud_avatar):每镜是自带配音+口型的 talking clip → 直接 xfade 拼接,
    # 跳过"静帧化 + 另配旁白/字幕混音"这条(音已在 clip 里)。
    if any(f.clip_path for f in frame_manifest.frames):
        return await _assemble_avatar_clips(
            shotlist,
            frame_manifest,
            timeline,
            script,
            constitution,
            output_dir=output_dir,
            width=width,
            height=height,
            fps=fps,
            vlm=vlm,
        )

    shot_segments: list[ShotSegment] = []
    for shot in shotlist.shots:
        frame = frames_by_shot.get(shot.shot_id)
        if frame is None or not frame.frame_path:
            raise RuntimeError(f"镜头 {shot.shot_id} 没有可用画面,无法装配(L6 G6 门应已拦截此情况)")
        clip_path = await render_shot_clip(
            shot,
            frame,
            output_dir=output_dir,
            width=width,
            height=height,
            fps=fps,
        )
        target_s = max((shot.t_end_ms - shot.t_start_ms) / 1000.0, 0.1)
        shot_segments.append(ShotSegment(video_path=clip_path, target_duration=target_s))

    narration_path = await concat_narration_track(timeline, audio_dir, output_dir=output_dir)
    bgm_path = await mix_bgm_master(music_plan, output_dir=output_dir)
    sfx_path = await mix_sfx_master(music_plan, timeline.total_duration_ms, output_dir=output_dir)

    srt_path = output_dir / "subtitles.srt"
    srt_path.write_text(generate_srt(timeline, script), encoding="utf-8")

    final_path = output_dir / "final.mp4"
    await assemble_longvideo(
        shots=shot_segments,
        output_path=final_path,
        narration_audio=narration_path,
        bgm_path=bgm_path,
        sfx_path=sfx_path,
        subtitle_path=srt_path,
        width=width,
        height=height,
        fps=fps,
        bgm_gain_db=_BGM_DUCK_GAIN_DB,
    )

    cover_path = final_path.with_suffix(".cover.jpg")
    duration_ms = round(await probe_duration(final_path) * 1000)
    final_video = FinalVideo(
        video_path=str(final_path),
        cover_path=str(cover_path) if cover_path.exists() else "",
        srt_path=str(srt_path),
        duration_ms=duration_ms,
    )

    result = await gate_final_video(final_video, timeline, script, narration_path, vlm=vlm)
    return final_video, result


# ── G8 终审门 ────────────────────────────────────────────────────────────


async def _detect_black_frames(video_path: Path) -> list[tuple[float, float]]:
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i",
        str(video_path),
        "-vf",
        "blackdetect=d=0.5:pic_th=0.98",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    text = stderr.decode(errors="replace")
    return [
        (float(m.group(1)), float(m.group(2)))
        for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)", text)
    ]


async def _detect_clipping(video_path: Path) -> float | None:
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i",
        str(video_path),
        "-af",
        "volumedetect",
        "-f",
        "null",
        "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    m = re.search(r"max_volume:\s*(-?[\d.]+) dB", stderr.decode(errors="replace"))
    return float(m.group(1)) if m else None


async def _extract_sample_frames(video_path: Path, n: int, *, output_dir: Path) -> list[Path]:
    duration = await probe_duration(video_path)
    if duration <= 0:
        return []
    paths: list[Path] = []
    for i in range(n):
        t = duration * (i + 0.5) / n
        out = output_dir / f"g8_frame_{i}.jpg"
        try:
            await ffmpeg_run(
                args=["-ss", f"{t:.3f}", "-i", str(video_path), "-frames:v", "1", str(out)],
                expected_output=out,
            )
            paths.append(out)
        except Exception as e:
            logger.warning("G8: 抽帧第%d帧失败: %s", i, e)
    return paths


async def _asr_reverify(narration_path: Path | None, script: Script) -> tuple[float | None, str]:
    if narration_path is None or not narration_path.exists():
        return None, "narration 轨不存在,ASR 全片反打跳过"
    import asyncio

    reference = "".join(ln.text for ln in script.lines if ln.text)
    try:
        proc = await asyncio.create_subprocess_exec(
            "whisper",
            str(narration_path),
            "--language",
            "zh",
            "--output_format",
            "txt",
            "--output_dir",
            str(narration_path.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=300)
        txt_path = narration_path.with_suffix(".txt")
        if txt_path.exists():
            hypothesis = txt_path.read_text(encoding="utf-8").strip()
            txt_path.unlink(missing_ok=True)
            return _char_error_rate(reference, hypothesis), ""
    except Exception as e:
        return None, f"ASR 全片反打不可用(whisper): {e}"
    return None, "ASR 全片反打未产出转写文本"


async def gate_final_video(
    final_video: FinalVideo,
    timeline: Timeline,
    script: Script,
    narration_path: Path | None,
    *,
    vlm: Any = None,
) -> GateResult:
    """G8 终审门:时长偏差/黑帧/削波/ASR 反打只报 warning(装配层面的软问题,
    人工可接受);成片文件缺失或长时间黑场才算 error。
    """
    errors: list[str] = []
    warnings: list[str] = []

    video_path = Path(final_video.video_path)
    if not video_path.exists():
        errors.append("成片文件不存在")
        return GateResult(passed=False, errors=errors)

    if timeline.total_duration_ms > 0:
        deviation = (
            abs(final_video.duration_ms - timeline.total_duration_ms) / timeline.total_duration_ms
        )
        if deviation > _DURATION_DEVIATION_THRESHOLD:
            warnings.append(
                f"成片时长 {final_video.duration_ms}ms 与配音时长 "
                f"{timeline.total_duration_ms}ms 偏差 {deviation:.1%}"
            )

    try:
        black_spans = await _detect_black_frames(video_path)
        long_black = [s for s in black_spans if s[1] - s[0] >= _BLACK_FRAME_MIN_DURATION_S]
        if long_black:
            errors.append(f"检测到 {len(long_black)} 处超过 {_BLACK_FRAME_MIN_DURATION_S}s 的黑场")
    except Exception as e:
        warnings.append(f"黑帧检测失败,跳过: {e}")

    try:
        max_vol = await _detect_clipping(video_path)
        if max_vol is not None and max_vol > _CLIP_MAX_VOLUME_THRESHOLD_DB:
            warnings.append(f"音频峰值 {max_vol:.1f}dB 接近/超过削波门槛")
    except Exception as e:
        warnings.append(f"音频削波检测失败,跳过: {e}")

    cer, note = await _asr_reverify(narration_path, script)
    if cer is not None and cer > 0.05:
        warnings.append(f"ASR 全片反打 CER={cer:.1%},超过 5% 门槛(可能装配环节引入了音画错位)")
    elif note:
        warnings.append(note)

    if vlm is None:
        try:
            from obase.provider_registry import ProviderRegistry

            vlm = ProviderRegistry.get().vlm("default")
        except Exception:
            vlm = None
    if vlm is not None:
        frames = await _extract_sample_frames(
            video_path, _VLM_SAMPLE_FRAMES, output_dir=video_path.parent
        )
        if frames:
            try:
                resp = await vlm(
                    messages=[
                        {
                            "role": "user",
                            "content": _FINAL_AUDIT_PROMPT_TEMPLATE.format(n=len(frames)),
                        }
                    ],
                    image_paths=[str(p) for p in frames],
                    max_tokens=300,
                )
                content = resp.get("content") if hasattr(resp, "get") else str(resp)
                audit = _extract_json_obj(content)
                if audit.get("consistent") is False:
                    warnings.append(f"VLM 终审发现风格不一致: {audit.get('issues')}")
            except Exception as e:
                warnings.append(f"VLM 终审调用失败,跳过: {e}")

    return GateResult(
        passed=not errors, coverage=1.0 if not errors else 0.0, errors=errors, warnings=warnings
    )
