"""Mix recipe and loudness gate (``audio.mix_recipe``).

One fixed recipe, written down so a mix is reproducible instead of
a matter of ear and memory:

* The finished film measures -14 LUFS integrated, true peak no
  higher than -1 dB.
* Voice is normalised to -16 LUFS before it enters the mix, so the
  voice level does not depend on how loud the recording happened
  to be.
* Background music sits at -12 to -16 dB when it plays alone, and
  is ducked to -20 to -26 dB under voice. The ducking compressor
  takes its key from the voice and compresses the music -- wired
  the other way round it would crush the voice, so the wiring is
  part of the recipe, not an implementation detail.
* The two tracks are summed with normalisation off, so neither
  track is quietly halved by the mixer.
* Head and tail each fade over 1 second.
* Music too short loops to the film length; music too long is cut
  to it. Mixing touches audio only: the picture stream is copied,
  never re-encoded.

Loudness is verified with the local ffmpeg loudness filter in
measure mode. If that filter or ffmpeg is missing, the report says
so plainly with verdict ``unmeasured`` -- a missing meter is never
reported as a pass.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

TARGET_LUFS = -14.0
LUFS_TOLERANCE = 2.0
TRUE_PEAK_CEILING_DB = -1.0
VOICE_PRE_NORM_LUFS = -16.0
BGM_SOLO_DB = (-16.0, -12.0)
BGM_UNDER_VOICE_DB = (-26.0, -20.0)
DUCKING = {
    "threshold": 0.03,
    "ratio": 8,
    "attack": 20,
    "release": 300,
}
FADE_SEC = 1.0


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise CapabilityError(f"audio.mix_recipe: required tool missing from PATH: {name}")
    return path


def recipe(bgm_level_db: float = -23.0) -> dict[str, Any]:
    """The fixed recipe as data, so tests can pin every number."""
    if not (BGM_UNDER_VOICE_DB[0] <= bgm_level_db <= BGM_UNDER_VOICE_DB[1]):
        raise CapabilityError(
            f"audio.mix_recipe: bgm_level_db {bgm_level_db} is outside the "
            f"under-voice range {BGM_UNDER_VOICE_DB}"
        )
    return {
        "target_lufs": TARGET_LUFS,
        "lufs_tolerance": LUFS_TOLERANCE,
        "true_peak_ceiling_db": TRUE_PEAK_CEILING_DB,
        "voice_pre_norm_lufs": VOICE_PRE_NORM_LUFS,
        "bgm_solo_db_range": list(BGM_SOLO_DB),
        "bgm_under_voice_db_range": list(BGM_UNDER_VOICE_DB),
        "bgm_level_db": bgm_level_db,
        "ducking": dict(DUCKING),
        "ducking_key": "voice",
        "ducking_target": "bgm",
        "amix_normalize": 0,
        "fade_sec": FADE_SEC,
        "video_codec": "copy",
    }


def build_ffmpeg_command(
    voice_path: Path,
    bgm_path: Path,
    video_path: Path,
    out_path: Path,
    bgm_level_db: float = -23.0,
) -> list[str]:
    """Build the runnable mix command for voice + music + picture.

    Input order is fixed: 0 = picture, 1 = voice, 2 = music (looped).
    The picture stream is copied; only audio filters run.
    """
    spec = recipe(bgm_level_db)
    for p in (voice_path, bgm_path, video_path):
        if not Path(p).is_file():
            raise CapabilityError(f"audio.mix_recipe: input file not found: {p}")
    d = spec["ducking"]
    # The voice feeds two consumers -- the mix itself and the
    # compressor's sidechain key -- so it is split first: a filter
    # output used twice without a split is a binding error.
    filt = (
        f"[1:a]loudnorm=I={VOICE_PRE_NORM_LUFS}:TP=-1.5:LRA=11[voice];"
        f"[voice]asplit=2[vmain][vsc];"
        f"[2:a]volume={bgm_level_db}dB[bgm];"
        f"[bgm][vsc]sidechaincompress=threshold={d['threshold']}:"
        f"ratio={d['ratio']}:attack={d['attack']}:release={d['release']}[ducked];"
        f"[vmain][ducked]amix=inputs=2:normalize=0[mixed];"
        f"[mixed]loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_CEILING_DB}:LRA=11,"
        f"afade=t=in:st=0:d={FADE_SEC},afade=t=out:st=0:d={FADE_SEC}[outa]"
    )
    # The tail fade start time needs the film length; it is patched
    # in by run_mix, which knows the video duration. This builder
    # keeps the out-fade at 0 as a placeholder only when run_mix
    # has not replaced it -- see run_mix for the real command.
    return [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(video_path),
        "-i", str(voice_path),
        "-stream_loop", "-1", "-i", str(bgm_path),
        "-filter_complex", filt,
        "-map", "0:v", "-map", "[outa]",
        "-c:v", "copy",
        "-shortest",
        str(out_path),
    ]


def _video_duration_sec(video_path: Path) -> float:
    ffprobe = _require_tool("ffprobe")
    proc = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise CapabilityError(f"audio.mix_recipe: ffprobe failed: {proc.stderr.strip()}")
    try:
        return float(proc.stdout.strip())
    except ValueError as exc:
        raise CapabilityError("audio.mix_recipe: ffprobe returned no duration") from exc


def run_mix(
    voice_path: Path,
    bgm_path: Path,
    video_path: Path,
    out_path: Path,
    bgm_level_db: float = -23.0,
) -> dict[str, Any]:
    """Run the recipe and return the command plus the mix report."""
    _require_tool("ffmpeg")
    duration = _video_duration_sec(Path(video_path))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_ffmpeg_command(voice_path, bgm_path, video_path, out, bgm_level_db)
    # Patch the tail fade to start one fade-length before the end.
    tail_start = max(0.0, duration - FADE_SEC)
    cmd = [
        arg.replace("afade=t=out:st=0:d=1.0",
                    f"afade=t=out:st={tail_start:.3f}:d={FADE_SEC}")
        if isinstance(arg, str) else arg
        for arg in cmd
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0 or not out.is_file():
        raise CapabilityError(f"audio.mix_recipe: ffmpeg mix failed: {proc.stderr.strip()}")
    loudness = measure_loudness(out)
    return {
        "capability": "audio.mix_recipe",
        "recipe": recipe(bgm_level_db),
        "command": cmd,
        "output": str(out),
        "video_duration_sec": duration,
        "loudness": loudness,
    }


def measure_loudness(media_path: Path) -> dict[str, Any]:
    """Measure integrated loudness and true peak with loudnorm.

    Returns ``measured: False`` with a reason when the tool or the
    measurement is unavailable. Callers must treat that as
    "not verified", never as a pass.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return {"measured": False, "reason": "ffmpeg not found on PATH"}
    proc = subprocess.run(
        [
            ffmpeg, "-i", str(media_path),
            "-af", f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_CEILING_DB}:LRA=11:print_format=json",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, timeout=600,
    )
    match = re.search(r"\{[^}]*\"input_i\"[^}]*\}", proc.stderr, re.DOTALL)
    if not match:
        return {"measured": False, "reason": "loudnorm measurement output not found in ffmpeg stderr"}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {"measured": False, "reason": "loudnorm measurement output was not JSON"}
    try:
        integrated = float(data["input_i"])
        true_peak = float(data["input_tp"])
    except (KeyError, TypeError, ValueError):
        return {"measured": False, "reason": "loudnorm output missing input_i/input_tp"}
    return {
        "measured": True,
        "integrated_lufs": integrated,
        "true_peak_db": true_peak,
        "target_lufs": TARGET_LUFS,
        "true_peak_ceiling_db": TRUE_PEAK_CEILING_DB,
    }


def verify_loudness(media_path: Path) -> dict[str, Any]:
    """Verdict a finished mix against the recipe's loudness gate."""
    measured = measure_loudness(Path(media_path))
    if not measured.get("measured"):
        return {
            "capability": "audio.mix_recipe",
            "verdict": "unmeasured",
            "pass": False,
            "detail": f"loudness not verified: {measured.get('reason')}",
            "loudness": measured,
        }
    lufs_ok = abs(measured["integrated_lufs"] - TARGET_LUFS) <= LUFS_TOLERANCE
    tp_ok = measured["true_peak_db"] <= TRUE_PEAK_CEILING_DB
    ok = lufs_ok and tp_ok
    return {
        "capability": "audio.mix_recipe",
        "verdict": "pass" if ok else "fail",
        "pass": ok,
        "detail": (
            f"integrated {measured['integrated_lufs']:.2f} LUFS "
            f"(target {TARGET_LUFS} +/- {LUFS_TOLERANCE}), "
            f"true peak {measured['true_peak_db']:.2f} dB "
            f"(ceiling {TRUE_PEAK_CEILING_DB})"
        ),
        "loudness": measured,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bgm_level = float(params.get("bgm_level_db", -23.0))
    out_path = out_dir / "mixed.mp4"
    if params.get("out_path"):
        out_path = Path(params["out_path"])
    report = run_mix(
        Path(params["voice_path"]), Path(params["bgm_path"]),
        Path(params["video_path"]), out_path, bgm_level,
    )
    report["loudness_gate"] = verify_loudness(out_path)
    report_path = out_dir / "mix_recipe_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        mp4=str(out_path),
        duration_s=float(report["video_duration_sec"]),
        sha256=compute_sha256(out_path),
        qa={"report_json": str(report_path), "loudness_gate": report["loudness_gate"]},
    )


def register_mix_recipe_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="audio.mix_recipe",
            kind="audio",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "voice_path": {"type": "string"},
                    "bgm_path": {"type": "string"},
                    "video_path": {"type": "string"},
                    "out_path": {"type": "string"},
                    "bgm_level_db": {"type": "number", "minimum": -26.0, "maximum": -20.0},
                },
                "required": ["voice_path", "bgm_path", "video_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=1.0,
            render=_render,
            description=(
                "Fixed mix recipe: voice pre-normalised to -16 LUFS, "
                "music ducked under voice (sidechain keyed on voice, "
                "threshold 0.03, ratio 8, attack 20, release 300), "
                "summed with normalisation off, 1 s head/tail fades, "
                "picture copied not re-encoded, finished film gated "
                "at -14 LUFS with a -1 dB true-peak ceiling and "
                "verified with loudnorm; a missing meter reports "
                "unmeasured, never a pass."
            ),
            line="audio",
        )
    )
    return ["audio.mix_recipe"]


register_mix_recipe_capabilities_once()
