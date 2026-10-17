"""中文旁白合成 —— CosyVoice(17600, 首选) 与 piper(回退)。

两条路径都:
* 全片同一音色(每行同一 speaker/voice_ref);
* 每行产出真实 wav 并测出真实时长, 供字幕对齐;
* 行间插固定静默, 拼成整条旁白。

引擎选择: ``STICKDIR_TTS`` 环境变量或 ``engine`` 参数。默认 ``piper`` ——
CosyVoice 在 CPU 单线程上每行约 50–60s 且不稳定(见 DONE), piper 是 Hevi
``svg_character.synth_line`` 使用的本地中文音色, 快且确定。CosyVoice 客户端
仍完整实现, 可用 ``STICKDIR_TTS=cosyvoice`` 启用。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

PIPER = "/data/soffy/projects/hevi-zero/.venv/bin/piper"
PIPER_VOICE = "/data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx"
COSY_URL = os.environ.get("STICKDIR_COSY_URL", "http://127.0.0.1:17600")
COSY_VOICE_REF = os.environ.get("STICKDIR_COSY_REF", "builtin:zh_default")
COSY_TIMEOUT = float(os.environ.get("STICKDIR_COSY_TIMEOUT", "25"))

#: 全片统一音色标识(voice-continuity: 一条视频一个冻结音色)
VOICE_ID = "zh_CN-huayan-medium"

FFMPEG = shutil.which("ffmpeg") or "/home/soffy/.local/bin/ffmpeg"
FFPROBE = shutil.which("ffprobe") or "/home/soffy/.local/bin/ffprobe"


@dataclass
class NarrationAudio:
    wav: Path
    cues: list[tuple[float, float]]  # 每行 (start, end) 秒
    engine: str
    total: float


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def _duration(path: Path) -> float:
    out = _run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]
    ).stdout.strip()
    return float(out) if out else 0.0


def _norm(src: Path, dst: Path) -> None:
    """单行响度归一(-16 LUFS, TP -1.5)。"""
    proc = _run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-af",
            "highpass=f=70,loudnorm=I=-16:TP=-1.5",
            "-ar",
            "44100",
            "-ac",
            "1",
            str(dst),
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError(f"loudnorm failed: {proc.stderr[-300:]}")


def cosyvoice_available(timeout: float = 4.0) -> bool:
    try:
        import httpx

        r = httpx.get(f"{COSY_URL}/health", timeout=timeout)
        return r.status_code == 200 and bool(r.json().get("status"))
    except Exception:  # noqa: BLE001
        return False


def _synth_piper(text: str, out_wav: Path) -> None:
    raw = out_wav.with_suffix(".raw.wav")
    proc = subprocess.run(
        [
            PIPER,
            "-m",
            PIPER_VOICE,
            "-f",
            str(raw),
            "--length_scale",
            "1.0",
            "--sentence_silence",
            "0.25",
        ],
        input=text,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"piper failed: {proc.stderr[-300:]}")
    _norm(raw, out_wav)
    raw.unlink(missing_ok=True)


def _synth_cosy(text: str, out_wav: Path) -> None:
    import httpx

    payload = {"script": [{"text": text, "voice_ref": COSY_VOICE_REF}], "config": {}}
    r = httpx.post(
        f"{COSY_URL}/api/ai/cosyvoice",
        content=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=COSY_TIMEOUT,
    )
    r.raise_for_status()
    tmp = out_wav.with_suffix(".cosy.wav")
    tmp.write_bytes(r.content)
    if tmp.stat().st_size < 1024:
        raise RuntimeError("cosyvoice returned an empty wav")
    _norm(tmp, out_wav)
    tmp.unlink(missing_ok=True)


def synthesize(
    lines: list[str],
    out_dir: Path,
    *,
    engine: str | None = None,
    gap: float = 0.30,
) -> NarrationAudio:
    """合成全部旁白行, 拼成整条, 返回 wav + 每行真实 (start, end)。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = (engine or os.environ.get("STICKDIR_TTS") or "piper").lower()
    if engine == "cosyvoice" and not cosyvoice_available():
        logger.warning("cosyvoice unavailable at %s; falling back to piper", COSY_URL)
        engine = "piper"

    parts: list[Path] = []
    cues: list[tuple[float, float]] = []
    t = 0.0
    for i, line in enumerate(lines):
        text = line.strip()
        wav = out_dir / f"vo_{i:02d}.wav"
        if not text:
            # 空行: 仍占一小段静默(保证与段对齐)
            silent = out_dir / f"vo_{i:02d}.wav"
            _run(
                [
                    FFMPEG,
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=44100:cl=mono",
                    "-t",
                    "0.4",
                    str(silent),
                ]
            )
            dur = 0.4
        else:
            used = engine
            try:
                if used == "cosyvoice":
                    _synth_cosy(text, wav)
                else:
                    _synth_piper(text, wav)
            except Exception as exc:  # noqa: BLE001 - 首选失败回退 piper
                if used != "piper":
                    logger.warning("cosyvoice line %d failed (%s); falling back to piper", i, exc)
                    used = "piper"
                    _synth_piper(text, wav)
                else:
                    raise
            dur = _duration(wav)
        cues.append((t, t + dur))
        parts.append(wav)
        t += dur + gap

    listfile = out_dir / "vo.txt"
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in parts), encoding="utf-8")
    out = out_dir / "narration.wav"
    proc = _run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listfile),
            "-c",
            "copy",
            str(out),
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError(f"narration concat failed: {proc.stderr[-300:]}")
    return NarrationAudio(wav=out, cues=cues, engine=engine, total=_duration(out))


def synth_line(text: str, out_wav: Path, *, engine: str | None = None) -> tuple[float, str]:
    """合成一行, 返回 (真实时长, 实际引擎)。"""
    engine = (engine or os.environ.get("STICKDIR_TTS") or "piper").lower()
    text = text.strip()
    if not text:
        _run(
            [
                FFMPEG,
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=44100:cl=mono",
                "-t",
                "0.4",
                str(out_wav),
            ]
        )
        return 0.4, engine
    if engine == "cosyvoice":
        try:
            _synth_cosy(text, out_wav)
            return _duration(out_wav), "cosyvoice"
        except Exception as exc:  # noqa: BLE001 - 首选失败回退 piper
            logger.warning("cosyvoice line failed (%s); falling back to piper", exc)
    _synth_piper(text, out_wav)
    return _duration(out_wav), "piper"


def synthesize_timed(
    lines: list[str],
    offsets: list[float],
    total_duration: float,
    out_dir: Path,
    *,
    engine: str | None = None,
) -> NarrationAudio:
    """每行放在 ``offsets[i]`` 时刻, 铺在 ``total_duration`` 的静默床上。

    返回整条 wav 与每行真实 ``(start, end)``。全片同一音色。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    engine = (engine or os.environ.get("STICKDIR_TTS") or "piper").lower()
    if engine == "cosyvoice" and not cosyvoice_available():
        logger.warning("cosyvoice unavailable at %s; falling back to piper", COSY_URL)
        engine = "piper"
    if len(lines) != len(offsets):
        raise ValueError("lines and offsets must be the same length")

    used_engine = engine
    cues: list[tuple[float, float]] = []
    inputs: list[Path] = []
    for i, (line, off) in enumerate(zip(lines, offsets)):
        wav = out_dir / f"vo_{i:02d}.wav"
        dur, used = synth_line(line, wav, engine=engine)
        used_engine = used
        inputs.append(wav)
        cues.append((off, off + dur))

    # 用 amix 把每行按其 offset 铺到静默床上(adelay + amix)
    cmd = [
        FFMPEG,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-t",
        f"{total_duration:.3f}",
        "-i",
        "anullsrc=r=44100:cl=mono",
    ]
    for wav in inputs:
        cmd += ["-i", str(wav)]
    filters = []
    labels = ["[0:a]"]
    for i, (start, _end) in enumerate(cues):
        ms = int(round(start * 1000))
        filters.append(f"[{i + 1}:a]adelay={ms}|{ms}[d{i}]")
        labels.append(f"[d{i}]")
    filters.append(
        "".join(labels) + f"amix=inputs={len(labels)}:normalize=0:dropout_transition=0[mix]"
    )
    filters.append("[mix]volume=1.0[out]")
    cmd += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[out]",
        "-ar",
        "44100",
        "-ac",
        "1",
        str(out_dir / "narration.wav"),
    ]
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"narration assembly failed: {proc.stderr[-400:]}")
    out = out_dir / "narration.wav"
    return NarrationAudio(wav=out, cues=cues, engine=used_engine, total=_duration(out))


__all__ = [
    "COSY_URL",
    "COSY_VOICE_REF",
    "NarrationAudio",
    "PIPER",
    "PIPER_VOICE",
    "VOICE_ID",
    "cosyvoice_available",
    "synth_line",
    "synthesize",
    "synthesize_timed",
]
