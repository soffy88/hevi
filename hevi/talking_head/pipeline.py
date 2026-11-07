"""Talking-head pipeline: preflight -> TTS -> lip-sync -> 3 gates -> ledger.

One portrait + one script in, one talking-head MP4 plus a
``job-state.json`` ledger out.  No human confirmation anywhere; the
failure policy is fixed:

* **preflight** failure -> the job stops, ``status="failed"`` (nothing was
  generated, so there is nothing to deliver).
* **TTS / lip-sync** failure -> exactly ONE automatic retry
  (``max_retries=1``); a second failure ends the job as ``"failed"``.
* **gate** failure -> the film is still delivered, as
  ``status="delivered_with_warnings"``, with the failing gate's measured
  numbers in the ledger.  A gate is never reported as passed when it was
  not (see :mod:`hevi.talking_head.gates`).

Reused hevi pieces (no engine is hard-coded here):

* TTS: ``hevi.audio.lux_tts_service.synth_with_luxtts`` /
  ``lux_tts_available``.
* Lip-sync: ``hevi.layer4_legacy.talkcraft.omodul_impl._avatar.build_avatar_clip``
  with ``AvatarSpec`` from ``...oprim_impl.sync`` — the engine
  (``wav2lip`` | ``musetalk``) is a *parameter* of the spec, this module
  only depends on that call surface.  ``build_avatar_clip`` renders a
  silent clip, so the stage finishes by muxing the narration WAV onto it
  (ffmpeg, ``-c:v copy``).
* Gates: :mod:`hevi.talking_head.gates` (whisper / earshot / visual).

Injection seams for tests and the coordinator: ``tts_fn``,
``lipsync_fn`` and ``gate_runner`` replace the real stages.  Their
contracts:

* ``tts_fn(script_text, out_wav: Path, voice: str) -> Path``
* ``lipsync_fn(portrait: Path, voice_wav: Path, duration_s: float,
  work_dir: Path, engine: str) -> Path`` (the final muxed MP4)
* ``gate_runner(video: Path, script_text: str,
  audio_duration_s: float) -> {"pass": bool, "gates": {...}, "failed": [...]}``
  (the :func:`hevi.talking_head.gates.run_all_gates` return shape)

CLI::

    python -m hevi.talking_head --text "大家好" --portrait me.jpg --out out/
    python -m hevi.talking_head --script script.txt --portrait me.jpg \\
        --out out/ --engine musetalk --voice soffy

Exit codes: 0 = delivered, 2 = delivered_with_warnings, 1 = failed.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.talking_head.gates import run_all_gates
from hevi.talking_head.preflight import run_preflight
from hevi.talking_head.state import Ledger, new_ledger

__all__ = [
    "TalkingHeadConfig",
    "main",
    "read_script_input",
    "run_talking_head",
]

ENGINES = ("wav2lip", "musetalk", "livliv")
VOICES = ("soffy", "en_male", "auto")


@dataclass
class TalkingHeadConfig:
    """Thresholds / knobs for one job.  Defaults mirror the gate modules."""

    engine: str = "musetalk"
    voice: str = "soffy"
    language: str = "zh"
    max_retries: int = 1
    whisper_threshold: float = 0.85
    lufs_target: float = -14.0
    lufs_tolerance: float = 2.0
    true_peak_ceiling: float = -1.0
    min_face_rate: float = 0.8
    max_black_share: float = 0.1
    max_av_diff_s: float = 0.5
    clip_size: tuple[int, int] = (512, 512)
    audio_remediation: bool = True
    character_id: str = "d03ft"

    def validate(self) -> None:
        if self.engine not in ENGINES:
            raise ValueError(f"engine must be one of {ENGINES}, got {self.engine!r}")
        if self.voice not in VOICES:
            raise ValueError(f"voice must be one of {VOICES}, got {self.voice!r}")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")


# ---------------------------------------------------------------------------
# real stage implementations (lazy heavy imports)
# ---------------------------------------------------------------------------
def _run_coro(coro):  # type: ignore[no-untyped-def]
    """Run an async stage from synchronous code (oneclick_film pattern)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _media_duration(path: Path) -> float:
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import duration

    return float(duration(path))


def compute_remediation_gain_db(
    *,
    true_peak_dbtp: float,
    lufs: float | None,
    ceiling: float = -1.0,
    lufs_target: float = -14.0,
    lufs_tolerance: float = 2.0,
    margin_db: float = 0.5,
) -> float | None:
    """Gain (dB) that fixes a level-only earshot failure, or None.

    The peak constraint caps any upward gain; a downward gain fixes both a
    hot peak and hot loudness.  Returns None when no single gain can satisfy
    both constraints, or when the needed change is negligible.
    """
    peak_cap_gain = ceiling - margin_db - true_peak_dbtp
    gain = peak_cap_gain if true_peak_dbtp > ceiling else 0.0
    if lufs is not None:
        projected = lufs + gain
        if projected > lufs_target + lufs_tolerance:
            gain = lufs_target - lufs
        elif projected < lufs_target - lufs_tolerance:
            gain = min(lufs_target - lufs, peak_cap_gain)
    gain = max(-12.0, min(gain, peak_cap_gain))
    if abs(gain) < 0.05:
        return None
    return round(gain, 2)


def _remux_with_gain(source: Path, target: Path, gain_db: float) -> Path:
    """Re-master the audio track at ``gain_db``; video stream is copied."""
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import FFMPEG, run

    run(
        [
            FFMPEG, "-y", "-v", "error", "-i", str(source),
            "-c:v", "copy", "-af", f"volume={gain_db:.2f}dB",
            "-c:a", "aac", "-b:a", "192k", str(target),
        ]
    )
    return target


def _local_luxtts_fallback() -> str | None:
    """Probe the on-box LuxTTS deployment (same model + voiceprint, CPU tier).

    The default HEVI_LUXTTS_URL points at the owner's laptop, which sleeps;
    ubuntu26 itself carries a byte-identical LuxTTS server on 127.0.0.1:8796
    (aii-asr/lux lux_server_cpu.py, voices soffy/en_male). Preferring it when
    the configured host is down keeps this line fully local and zero-cost.
    """
    import httpx

    url = "http://127.0.0.1:8796"
    try:
        response = httpx.get(
            f"{url}/health", timeout=httpx.Timeout(5.0, connect=2.0), trust_env=False
        )
        payload = response.json()
        if response.status_code == 200 and isinstance(payload, dict) and payload.get("ok") is True:
            return url
    except Exception:
        pass
    return None


def _default_tts(script_text: str, out_wav: Path, voice: str) -> Path:
    from hevi.audio.lux_tts_service import lux_tts_available, synth_with_luxtts

    if not lux_tts_available() and not os.environ.get("HEVI_LUXTTS_URL"):
        local = _local_luxtts_fallback()
        if local:
            os.environ["HEVI_LUXTTS_URL"] = local
    if not lux_tts_available():
        raise RuntimeError(
            "LuxTTS service is not healthy (lux_tts_available() is False); "
            "check HEVI_LUXTTS_URL / the LuxTTS host / local :8796 deployment"
        )
    metadata_path = out_wav.with_suffix(".tts.json")
    result = _run_coro(
        synth_with_luxtts(script_text, out_wav, voice=voice, metadata_path=metadata_path)
    )
    return Path(result)


def _default_lipsync(
    portrait: Path, voice_wav: Path, duration_s: float, work_dir: Path, engine: str,
    *, clip_size: tuple[int, int] = (512, 512),
) -> Path:
    from hevi.layer4_legacy.talkcraft.omodul_impl._avatar import build_avatar_clip
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import FFMPEG, run
    from hevi.layer4_legacy.talkcraft.oprim_impl.sync import AvatarSpec

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    spec = AvatarSpec(image=str(portrait), mode="lipsync", engine=engine)  # type: ignore[arg-type]
    result = build_avatar_clip(
        spec=spec, voice_wav=Path(voice_wav), duration_s=duration_s,
        work=work_dir, size=clip_size,
    )
    # build_avatar_clip renders silent video; mux the narration onto it.
    final = work_dir.parent / "talking_head.mp4"
    run(
        [FFMPEG, "-y", "-v", "error", "-i", str(result.clip), "-i", str(voice_wav),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
         "-shortest", str(final)]
    )
    return final


def _default_lipsync_livliv(
    portrait: Path, voice_wav: Path, duration_s: float, work_dir: Path, engine: str,
    *, clip_size: tuple[int, int] = (512, 512), character_id: str = "d03ft",
) -> Path:
    from hevi.avatar_livliv.render import render_clip

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir.parent / "livliv_render"
    # Never upscale a small render: keep the character at >=720 wide (2:3).
    lw = max(720, int(clip_size[0]))
    lh = max(1080, int(round(lw * 1.5)))
    result = render_clip(
        character_id, Path(voice_wav), out, fps=30,
        width=lw, height=lh, duration_s=duration_s,
    )
    outputs = result.get("outputs") or {}
    mp4 = outputs.get("mp4")
    if not mp4 or not Path(mp4).is_file():
        raise RuntimeError(f"livliv render produced no mp4: {result}")
    return Path(mp4)


# ---------------------------------------------------------------------------
# retry helper
# ---------------------------------------------------------------------------
def _run_stage_with_retry(
    ledger: Ledger, stage: str, fn: Callable[[], Any], *, max_retries: int
) -> Any:
    """Run ``fn``; on failure retry up to ``max_retries`` times.

    Attempt / retry counts land on the ledger stage either way.  The
    final exception re-raises so the caller can fail the job.
    """
    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        ledger.start_stage(stage)
        try:
            result = fn()
        except Exception as exc:  # stage boundary: record, maybe retry
            last_error = exc
            if attempt < max_retries:
                ledger.record_retry(stage)
                ledger.add_warning(
                    f"{stage} attempt {attempt + 1} failed, retrying: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            ledger.fail_stage(stage, f"{type(exc).__name__}: {exc}")
            raise
        ledger.finish_stage(stage)
        return result
    assert last_error is not None  # pragma: no cover - loop always returns/raises
    raise last_error


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def run_talking_head(
    *,
    script_text: str,
    portrait_path: str | Path,
    out_dir: str | Path,
    engine: str = "musetalk",
    voice: str = "soffy",
    voice_sample: str | Path | None = None,
    config: TalkingHeadConfig | None = None,
    tts_fn: Callable[..., Path] | None = None,
    lipsync_fn: Callable[..., Path] | None = None,
    gate_runner: Callable[..., dict[str, Any]] | None = None,
    face_detector: Callable[[Path], Any] | None = None,
) -> dict[str, Any]:
    """Run the full pipeline and return the ledger dict.

    The ledger is also written to ``<out_dir>/job-state.json`` at every
    stage boundary, so a crashed job still leaves its evidence behind.
    """
    cfg = config or TalkingHeadConfig(engine=engine, voice=voice)
    cfg.validate()
    # Absolute paths everywhere below: the MuseTalk worker chdirs into its
    # model home before reading the portrait/wav, so relative paths break.
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    portrait = Path(portrait_path).resolve()

    ledger = Ledger(
        new_ledger(
            script_text=script_text, portrait=str(portrait),
            engine=cfg.engine, voice=cfg.voice,
            voice_sample=str(voice_sample) if voice_sample else None,
        ),
        out / "job-state.json",
    )
    ledger.save()
    (out / "script.txt").write_text(script_text, encoding="utf-8")

    # -- 1. preflight (no retry: bad inputs do not heal themselves) -------
    ledger.start_stage("preflight")
    preflight = run_preflight(
        script_text=script_text, portrait_path=portrait,
        voice_sample=voice_sample, face_detector=face_detector,
    )
    if not preflight["ok"]:
        ledger.fail_stage("preflight", "; ".join(preflight["errors"]), detail={"report": preflight})
        ledger.finalize()
        ledger.save()
        return ledger.data
    ledger.finish_stage(
        "preflight",
        detail={
            "estimated_seconds": preflight["estimated_seconds"],
            "portrait_size": [
                preflight["portrait"].get("width"), preflight["portrait"].get("height"),
            ],
        },
    )
    for warning in preflight.get("warnings") or []:
        ledger.add_warning(f"preflight: {warning}")
    ledger.save()

    # -- 2. TTS (one retry) -------------------------------------------------
    narration_wav = out / "narration.wav"
    tts = tts_fn or _default_tts
    try:
        _run_stage_with_retry(
            ledger, "tts",
            lambda: tts(script_text, narration_wav, cfg.voice),
            max_retries=cfg.max_retries,
        )
    except Exception:
        ledger.finalize()
        ledger.save()
        return ledger.data
    if not narration_wav.is_file():
        ledger.fail_stage("tts", f"TTS returned without producing {narration_wav}")
        ledger.finalize()
        ledger.save()
        return ledger.data
    try:
        audio_duration = _media_duration(narration_wav)
    except Exception:
        audio_duration = float(preflight["estimated_seconds"])
        ledger.mark_degraded("tts", "narration duration unprobeable; using preflight estimate")
    ledger.set_artifact("narration_wav", str(narration_wav))
    ledger.data["stages"]["tts"]["detail"]["audio_duration_s"] = round(audio_duration, 3)
    ledger.save()

    # -- 3. lip-sync + mux (one retry) --------------------------------------
    work_dir = out / "work"
    if cfg.engine == "livliv":
        lipsync = lipsync_fn or (
            lambda p, w, d, wd, e: _default_lipsync_livliv(
                p, w, d, wd, e, clip_size=cfg.clip_size, character_id=cfg.character_id)
        )
    else:
        lipsync = lipsync_fn or (
            lambda p, w, d, wd, e: _default_lipsync(p, w, d, wd, e, clip_size=cfg.clip_size)
        )
    try:
        final_video = _run_stage_with_retry(
            ledger, "lipsync",
            lambda: Path(lipsync(portrait, narration_wav, audio_duration, work_dir, cfg.engine)),
            max_retries=cfg.max_retries,
        )
    except Exception:
        ledger.finalize()
        ledger.save()
        return ledger.data
    final_video = Path(final_video)
    if not final_video.is_file():
        ledger.fail_stage("lipsync", f"lip-sync returned without producing {final_video}")
        ledger.finalize()
        ledger.save()
        return ledger.data
    # Normalise the delivered artifact location without hiding the source.
    delivered = out / "talking_head.mp4"
    if final_video.resolve() != delivered.resolve():
        import shutil

        shutil.copy2(final_video, delivered)
    else:
        delivered = final_video
    ledger.set_artifact("talking_head_mp4", str(delivered))
    ledger.save()

    # -- 4. three gates (failures degrade the delivery, never fake a pass) --
    ledger.start_stage("gates")
    runner = gate_runner or (
        lambda video, text, adur: run_all_gates(
            video, script_text=text, audio_duration_s=adur,
            whisper_threshold=cfg.whisper_threshold, language=cfg.language,
            lufs_target=cfg.lufs_target, lufs_tolerance=cfg.lufs_tolerance,
            true_peak_ceiling=cfg.true_peak_ceiling,
            min_face_rate=cfg.min_face_rate, max_black_share=cfg.max_black_share,
            max_av_diff_s=cfg.max_av_diff_s,
        )
    )
    try:
        gate_result = runner(delivered, script_text, audio_duration)
    except Exception as exc:  # a broken gate runner is a failed gate, not a crash
        gate_result = {
            "pass": False,
            "gates": {},
            "failed": ["gate_runner"],
            "error": f"{type(exc).__name__}: {exc}",
        }
    # One-shot audio remediation (the story.oneclick_film precedent): when
    # the ONLY failure is the earshot gate and it is a level problem (true
    # peak and/or loudness), re-master once with a computed gain and re-run
    # the gates.  Anything else is not level-fixable and stays a warning.
    remediation: dict[str, Any] | None = None
    if cfg.audio_remediation and gate_result.get("failed") == ["earshot_audio"]:
        ear = (gate_result.get("gates") or {}).get("earshot_audio") or {}
        failed_checks = set(ear.get("failed_checks") or [])
        measurements = ear.get("measurements") or {}
        gain_db = None
        if (
            failed_checks
            and failed_checks <= {"true_peak", "loudness"}
            and measurements.get("true_peak_dbtp") is not None
        ):
            gain_db = compute_remediation_gain_db(
                true_peak_dbtp=float(measurements["true_peak_dbtp"]),
                lufs=float(measurements["lufs"]) if measurements.get("lufs") is not None else None,
                ceiling=cfg.true_peak_ceiling,
                lufs_target=cfg.lufs_target,
                lufs_tolerance=cfg.lufs_tolerance,
            )
        if gain_db is not None:
            remediation = {"gain_db": gain_db, "applied": False}
            try:
                mastered = out / "talking_head_mastered.mp4"
                _remux_with_gain(delivered, mastered, gain_db)
                retry_result = runner(mastered, script_text, audio_duration)
                remediation["recheck_pass"] = bool(retry_result.get("pass"))
                if retry_result.get("pass"):
                    import shutil

                    shutil.copy2(mastered, delivered)
                    gate_result = retry_result
                    remediation["applied"] = True
            except Exception as exc:  # remediation must never crash the job
                remediation["error"] = f"{type(exc).__name__}: {exc}"
    gates = gate_result.get("gates") or {}
    ledger.set_gates(gates)
    if gate_result.get("failed"):
        ledger.mark_degraded(
            "gates", f"gates failed: {', '.join(str(f) for f in gate_result['failed'])}"
        )
    ledger.finish_stage(
        "gates",
        detail={
            "pass": bool(gate_result.get("pass")),
            "failed": gate_result.get("failed") or [],
            "remediation": remediation,
        },
    )
    ledger.save()

    # -- 5. deliver -----------------------------------------------------------
    ledger.start_stage("deliver")
    ledger.finish_stage("deliver", detail={"output": str(delivered)})
    status = ledger.finalize()
    ledger.data["deliver"] = {"status": status, "output_video": str(delivered)}
    ledger.save()
    return ledger.data


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def read_script_input(*, script_path: str | None, text: str | None) -> str:
    """Resolve the mutually exclusive --script / --text inputs (pure-ish)."""
    if script_path and text:
        raise ValueError("pass either --script or --text, not both")
    if script_path:
        return Path(script_path).read_text(encoding="utf-8")
    if text:
        return text
    raise ValueError("one of --script or --text is required")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m hevi.talking_head",
        description="Talking-head pipeline: portrait + script -> lip-synced MP4 + job-state.json",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--script", help="path to a UTF-8 script text file")
    group.add_argument("--text", help="script text inline")
    parser.add_argument("--portrait", required=True, help="frontal portrait image path")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--engine", choices=ENGINES, default="musetalk",
                        help="lip-sync engine passed to build_avatar_clip (default: musetalk, MIT; wav2lip weights are non-commercial)")
    parser.add_argument("--voice", choices=VOICES, default="soffy",
                        help="LuxTTS voice (default: soffy)")
    parser.add_argument("--voice-sample", default=None,
                        help="optional voice-clone sample (MP3/M4A/WAV, 10s-5min, <=20MB)")
    parser.add_argument("--language", default="zh", help="ASR language for the whisper gate")
    parser.add_argument("--whisper-threshold", type=float, default=0.85,
                        help="min normalised script/transcript similarity (default: 0.85)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        script_text = read_script_input(script_path=args.script, text=args.text)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    cfg = TalkingHeadConfig(
        engine=args.engine, voice=args.voice, language=args.language,
        whisper_threshold=args.whisper_threshold,
    )
    ledger = run_talking_head(
        script_text=script_text, portrait_path=args.portrait, out_dir=args.out,
        config=cfg, voice_sample=args.voice_sample,
    )
    status = ledger.get("status")
    print(f"status={status} ledger={Path(args.out) / 'job-state.json'}")
    if status == "delivered":
        return 0
    if status == "delivered_with_warnings":
        failed = [
            name for name, gate in (ledger.get("gates") or {}).items()
            if isinstance(gate, dict) and gate.get("pass") is not True
        ]
        print(f"delivered with warnings; failed gates: {failed or ledger.get('warnings')}",
              file=sys.stderr)
        return 2
    print(f"job failed at stage: {ledger.get('failed_stage')}", file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
