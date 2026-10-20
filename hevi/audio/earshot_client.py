"""Client for the local earshot CLI (model-free paths only).

Upstream: earshot by Leon Lin, MIT License —
https://github.com/Leonxlnx/earshot ("Ears for coding agents").

On this host earshot lives in its own venv (``~/.venvs/earshot``) installed
with the model-free dependency set (numpy / scipy / soundfile / soxr /
librosa / pyloudnorm).  The CLAP/AST model weights are deliberately NOT
downloaded, so this client only wraps the commands that need no models and
no network:

* ``measure``   — objective measurements (LUFS, true peak, LRA, ...)
* ``sfx list``  — the shipped bank of 201 code-defined sound effects
* ``sfx render``— render one bank sound by id to a wav file

``EARSHOT_BIN`` overrides the CLI path (used by tests).  Every failure raises
:class:`EarshotError` — callers surface it as ``CapabilityError``; nothing in
here pretends a measurement happened when it did not.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


class EarshotError(RuntimeError):
    """earshot is missing, failed, or returned something unusable."""


def earshot_bin() -> Path:
    override = os.environ.get("EARSHOT_BIN")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".venvs" / "earshot" / "bin" / "earshot"


def ensure_earshot() -> Path:
    binary = earshot_bin()
    if not binary.is_file():
        raise EarshotError(
            f"earshot CLI not found at {binary}. Install it once with: "
            "python3 -m venv ~/.venvs/earshot && "
            "~/.venvs/earshot/bin/pip install -e <earshot checkout> "
            "(model-free deps only; see docs/rules/audio_gate.md)."
        )
    return binary


def _run_env() -> dict[str, str]:
    env = dict(os.environ)
    extra = [str(Path.home() / ".local" / "bin"), str(earshot_bin().parent)]
    env["PATH"] = os.pathsep.join([*extra, env.get("PATH", "")])
    return env


def _run(args: list[str], *, timeout: float = 300.0) -> str:
    binary = ensure_earshot()
    try:
        proc = subprocess.run(
            [str(binary), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_run_env(),
        )
    except subprocess.TimeoutExpired as exc:
        raise EarshotError(f"earshot {' '.join(args[:2])} timed out") from exc
    if proc.returncode != 0:
        lines = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = lines[-1] if lines else f"exit code {proc.returncode}"
        raise EarshotError(f"earshot {' '.join(args[:2])} failed: {tail}")
    return proc.stdout


def _run_json(args: list[str], *, timeout: float = 300.0) -> Any:
    out = _run(args, timeout=timeout)
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise EarshotError(
            f"earshot {' '.join(args[:2])} did not return JSON: {out[:200]!r}"
        ) from exc


def measure(media_path: Path) -> dict[str, Any]:
    """Objective, model-free measurements for one media file.

    Returns the earshot ``measure --json`` payload: duration, peak_dbfs,
    true_peak_dbtp, lufs, lra_lu, short_term_max_lufs, ...  Video files are
    decoded through the ffmpeg on PATH (installed at ~/.local/bin/ffmpeg).
    """
    path = Path(media_path)
    if not path.is_file():
        raise EarshotError(f"media file not found: {path}")
    # --light skips the librosa-dependent slow parts (onsets/HPSS/pitch);
    # everything the gate needs (LUFS, true peak, clipping) is returned.
    payload = _run_json(["measure", str(path), "--json", "--light"])
    if not isinstance(payload, dict) or "true_peak_dbtp" not in payload:
        raise EarshotError(f"earshot measure returned no measurements for {path}")
    return payload


def sfx_list() -> list[dict[str, Any]]:
    """All bank sounds (id / category / timing / knobs), fully offline."""
    payload = _run_json(["sfx", "list", "--json"])
    sounds = payload.get("sounds") if isinstance(payload, dict) else None
    if not isinstance(sounds, list):
        raise EarshotError("earshot sfx list returned no sounds")
    return sounds


def sfx_render(
    sfx_id: str,
    out_path: Path,
    *,
    dur: float | None = None,
    apex: float | None = None,
    pitch: str | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Render one bank sound by id to ``out_path`` (wav, 48 kHz).

    The bank is data shipped inside the earshot package (201 sounds defined
    as synthesis recipes in JSON) — rendering needs no model and no network.
    An unknown id makes the CLI exit non-zero, surfaced as EarshotError.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = ["sfx", "render", str(sfx_id), "-o", str(out_path), "--json"]
    if dur is not None:
        args += ["--dur", str(dur)]
    if apex is not None:
        args += ["--apex", str(apex)]
    if pitch is not None:
        args += ["--pitch", str(pitch)]
    if seed is not None:
        args += ["--seed", str(seed)]
    payload = _run_json(args)
    if not out_path.is_file() or out_path.stat().st_size == 0:
        raise EarshotError(f"earshot sfx render produced no file at {out_path}")
    return payload if isinstance(payload, dict) else {}
