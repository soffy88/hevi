"""One-click film entry (``story.oneclick_film``).

Preset-driven wrapper around :func:`hevi.storyfilm.pipeline.run_story_film`
(hyperframes route) plus a gate-retry policy that leaves evidence for
every retry / degradation:

  1. ``film_gate`` verdict ``"red"`` -> ONE retry: every shot's Ken Burns
     parameters are boosted (pure :func:`boost_ken_burns`), the film is
     re-rendered from ``shots.json`` with the delivery's ``film_audio``,
     and the gates are re-run once.
  2. ``earshot_gate`` ``pass == False`` -> ONE retry: the film audio is
     extracted, mastered with ``apply_gain_control(target_dbtp=-2.5)``
     and remuxed with ``-c:v copy``; earshot is re-verified once.
  3. ``qa.review_sheet`` (registry capability) runs as a third gate with
     one minimal legal comment; a missing/failing capability is recorded
     as ``{"skipped": reason}`` — never faked as a pass.

Anything still failing after its single retry is delivered with
warnings (``status == "delivered_with_warnings"``) and the reason in the
ledger — this module never reports a gate as passed when it was not.

The ledger lands in ``<out_dir>/oneclick_delivery.json`` and is also the
return value of :func:`run_oneclick_film`.  CLI::

    python -m hevi.storyfilm.oneclick "一只小猫在雨夜里找回家的路" \
        --preset tuantuan --aspect 9:16
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from hevi.storyfilm.pipeline import (
    DEFAULT_STYLE,
    _ASPECT_RES,
    _run_gates,
    apply_gain_control,
    render_motion_film,
    run_story_film,
)

__all__ = [
    "PRESETS",
    "boost_ken_burns",
    "main",
    "resolve_preset",
    "run_oneclick_film",
]

# Preset table.  ``music_product`` values are direction-mode products of
# hevi.audio.score_render (PRODUCT_MAP, verified 2026-10-23):
# cute -> piano template, creative -> cinematic, calm -> lofi.  All
# three are legal products, so ``watercolor`` keeps ``calm`` (no
# fallback to ``cute`` is needed); ``music_style`` for cinema is the
# legal TEMPLATES key "cinematic".
PRESETS: dict[str, dict[str, Any]] = {
    "storybook": {
        "style": DEFAULT_STYLE,
        "visual": "gpt",
        "music_product": "cute",
    },
    "tuantuan": {
        "style": DEFAULT_STYLE,
        "visual": "rig",
        "rig_character": "tuantuan",
        "music_product": "cute",
    },
    "cinema": {
        "style": "cinematic film still, dramatic lighting, rich color grade",
        "visual": "gpt",
        "music_product": "creative",
        "music_style": "cinematic",
    },
    "watercolor": {
        "style": (
            "soft watercolor storybook illustration, visible brush "
            "strokes, warm paper texture"
        ),
        "visual": "gpt",
        "music_product": "calm",
    },
    "brush": {
        "style": DEFAULT_STYLE,
        "visual": "brush",
        "music_product": "calm",
    },
}


def resolve_preset(name: str) -> dict[str, Any]:
    """Return a copy of the preset config, or raise ValueError."""
    try:
        return dict(PRESETS[name])
    except KeyError:
        raise ValueError(
            f"unknown preset {name!r}; valid presets: {sorted(PRESETS)}"
        ) from None


def boost_ken_burns(params: dict[str, Any]) -> dict[str, Any]:
    """Amplify Ken Burns motion for the film_gate retry (pure).

    Zoom kinds: the crop-width travel is widened around its midpoint
    (clamped to [0.30, 0.98]).  Pan kinds: the centre travel is widened
    to the full pan slack (0.0 -> 1.0).  Direction is preserved and the
    input dict is never mutated.
    """
    boosted = dict(params)
    cs = float(boosted.get("crop_w_start", 0.92))
    ce = float(boosted.get("crop_w_end", 0.50))
    if cs != ce:
        mid = (cs + ce) / 2.0
        half = abs(cs - ce) / 2.0
        new_half = min(0.34, half * 1.6 + 0.04)
        lo = max(0.30, mid - new_half)
        hi = min(0.98, mid + new_half)
        if cs < ce:
            boosted["crop_w_start"], boosted["crop_w_end"] = lo, hi
        else:
            boosted["crop_w_start"], boosted["crop_w_end"] = hi, lo
    xs = float(boosted.get("cx_start", 0.5))
    xe = float(boosted.get("cx_end", 0.5))
    if xs != xe:
        if xs < xe:
            boosted["cx_start"], boosted["cx_end"] = 0.0, 1.0
        else:
            boosted["cx_start"], boosted["cx_end"] = 1.0, 0.0
    return boosted


def _run_coro(coro):  # type: ignore[no-untyped-def]
    """Run an async pipeline from synchronous code (storyfilm.py pattern)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_gates(out_dir: Path, gates: dict[str, Any]) -> None:
    (out_dir / "gates.json").write_text(
        json.dumps(gates, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _rerender_with_boosted_motion(
    out_dir: Path, delivery: dict[str, Any], *, aspect: str
) -> None:
    shots = json.loads((out_dir / "shots.json").read_text(encoding="utf-8"))
    for shot in shots:
        if isinstance(shot.get("ken_burns"), dict):
            shot["ken_burns"] = boost_ken_burns(shot["ken_burns"])
    (out_dir / "shots.json").write_text(
        json.dumps(shots, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    title = str(delivery.get("title") or _read_json(out_dir / "story.json").get("title") or "")
    audio = Path(delivery.get("film_audio") or out_dir / "narration.wav")
    width, height = _ASPECT_RES.get(aspect, (720, 1280))
    render_motion_film(
        shots=shots,
        title=title,
        narration_path=audio,
        output_path=out_dir / "film.mp4",
        width=width,
        height=height,
        fps=24,
    )


def _fix_earshot_audio(out_dir: Path, film_path: Path) -> None:
    audio_path = out_dir / "earshot_fix_audio.wav"
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(film_path),
            "-vn", "-c:a", "pcm_s16le", str(audio_path),
        ],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0 or not audio_path.is_file():
        raise RuntimeError(
            f"ffmpeg audio extract failed: {(proc.stderr or '')[-300:]}"
        )
    apply_gain_control(audio_path, target_dbtp=-2.5)
    tmp = out_dir / "film.earshot_fix.mp4"
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", "-i", str(film_path),
            "-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(tmp),
        ],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0 or not tmp.is_file():
        raise RuntimeError(
            f"ffmpeg remux failed: {(proc.stderr or '')[-300:]}"
        )
    tmp.replace(film_path)


def _run_review_sheet(
    film_path: Path, out_dir: Path, *, aspect: str
) -> dict[str, Any]:
    """Third gate via the registry capability; skipped is recorded, not faked."""
    try:
        import hevi.capabilities as caps

        if "qa.review_sheet" not in caps.names():
            return {"skipped": "qa.review_sheet not registered"}
        cap = caps.get("qa.review_sheet")
        # comments=[] is rejected by build_review_sheet ("nothing to
        # review"), so pass one minimal legal comment at t=0.
        result = cap.render_safe(
            {
                "media_path": str(film_path),
                "comments": [
                    {
                        "timestamp_s": 0.0,
                        "comment": "oneclick 自动审片占位记录（无人工意见）",
                        "status": "pending",
                    }
                ],
            },
            out_dir / "review_sheet",
            duration=0.0,
            aspect=aspect,
            seed=0,
        )
        return {
            "pass": result.qa.get("pass"),
            "report": result.qa.get("report"),
            "comments": result.qa.get("comments"),
        }
    except Exception as exc:
        return {"skipped": f"{type(exc).__name__}: {exc}"}


def run_oneclick_film(
    premise: str,
    *,
    preset: str = "storybook",
    aspect: str = "9:16",
    max_shots: int = 5,
    voice: str = "soffy",
    music: bool = True,
    out_dir: Path,
    series: str | None = None,
    asset_library: str | None = None,
) -> dict[str, Any]:
    """One-click film: preset run + gate retries + oneclick ledger."""
    cfg = resolve_preset(preset)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    kwargs: dict[str, Any] = dict(
        premise=premise,
        style=cfg["style"],
        max_shots=max_shots,
        render_route="hyperframes",
        aspect=aspect,
        voice=voice,
        out_dir=out_dir,
        music=music,
        music_product=cfg.get("music_product", "cute"),
    )
    if cfg.get("music_style"):
        kwargs["music_style"] = cfg["music_style"]
    if cfg.get("visual") == "rig":
        kwargs["rig_character"] = cfg.get("rig_character", "tuantuan")
    if cfg.get("visual") == "brush":
        kwargs["image_provider"] = "brush"
    if series:
        kwargs["series"] = series
    if asset_library:
        kwargs["asset_library"] = asset_library
    delivery = _run_coro(run_story_film(**kwargs))

    retries: list[dict[str, Any]] = []
    degradations: list[dict[str, Any]] = []
    warnings: list[str] = []
    for stage_name, stage in (delivery.get("stages") or {}).items():
        if isinstance(stage, dict) and stage.get("status") == "degraded":
            degradations.append(
                {"stage": stage_name, "error": stage.get("error")}
            )

    film_path = out_dir / "film.mp4"
    gates: dict[str, Any] = _read_json(out_dir / "gates.json")
    if not gates and isinstance(delivery.get("gates"), dict):
        gates = dict(delivery["gates"])

    # Gate 1: film_gate red -> one boosted-Ken-Burns re-render.
    film_gate = gates.get("film_gate") or {}
    if isinstance(film_gate, dict) and film_gate.get("verdict") == "red":
        try:
            _rerender_with_boosted_motion(out_dir, delivery, aspect=aspect)
            gates = _run_gates(film_path, out_dir, aspect=aspect)
            _write_gates(out_dir, gates)
            verdict = (gates.get("film_gate") or {}).get("verdict")
            retries.append(
                {
                    "gate": "film_gate",
                    "action": "boost_ken_burns_rerender",
                    "result": "done",
                    "verdict_after": verdict,
                }
            )
            if verdict == "red":
                warnings.append("film_gate still red after one retry")
        except Exception as exc:
            retries.append(
                {
                    "gate": "film_gate",
                    "action": "boost_ken_burns_rerender",
                    "result": f"failed: {type(exc).__name__}: {exc}",
                }
            )
            warnings.append(f"film_gate retry failed: {exc}")

    # Gate 2: earshot fail -> one gain-control + remux retry.
    earshot = gates.get("earshot_gate") or {}
    if isinstance(earshot, dict) and earshot.get("pass") is False:
        try:
            _fix_earshot_audio(out_dir, film_path)
            new_gates = _run_gates(film_path, out_dir, aspect=aspect)
            if isinstance(new_gates.get("earshot_gate"), dict):
                gates["earshot_gate"] = new_gates["earshot_gate"]
            _write_gates(out_dir, gates)
            passed = (gates.get("earshot_gate") or {}).get("pass")
            retries.append(
                {
                    "gate": "earshot_gate",
                    "action": "gain_control_remux",
                    "result": "done",
                    "pass_after": passed,
                }
            )
            if passed is False:
                warnings.append("earshot_gate still failing after one retry")
        except Exception as exc:
            retries.append(
                {
                    "gate": "earshot_gate",
                    "action": "gain_control_remux",
                    "result": f"failed: {type(exc).__name__}: {exc}",
                }
            )
            warnings.append(f"earshot_gate retry failed: {exc}")

    # Gate 3: qa.review_sheet via the capability registry.
    gates["review_sheet"] = _run_review_sheet(film_path, out_dir, aspect=aspect)
    if "skipped" in gates["review_sheet"]:
        degradations.append(
            {"stage": "review_sheet", "error": gates["review_sheet"]["skipped"]}
        )
    _write_gates(out_dir, gates)

    film_info = delivery.get("film") or {}
    duration_s = float(film_info.get("duration_s") or 0.0)
    if not duration_s and (out_dir / "shots.json").is_file():
        try:
            shots = json.loads(
                (out_dir / "shots.json").read_text(encoding="utf-8")
            )
            duration_s = round(
                sum(float(s.get("duration_s") or 0.0) for s in shots), 2
            )
        except Exception:
            duration_s = 0.0

    status = (
        "delivered_with_warnings"
        if (warnings or degradations)
        else "delivered"
    )
    ledger: dict[str, Any] = {
        "entry": "story.oneclick_film",
        "premise": premise,
        "preset": preset,
        "series": series,
        "aspect": aspect,
        "film": {"path": str(film_path), "duration_s": duration_s},
        "cost_usd": delivery.get("total_cost_usd"),
        "stages": {
            k: (v.get("status") if isinstance(v, dict) else v)
            for k, v in (delivery.get("stages") or {}).items()
        },
        "gates": gates,
        "retries": retries,
        "degradations": degradations,
        "warnings": warnings,
        "status": status,
    }
    (out_dir / "oneclick_delivery.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return ledger


def _load_repo_env() -> None:
    """Inject missing keys from the repo-root .env (values never printed)."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="oneclick",
        description="一键出片: premise -> story.oneclick_film",
    )
    parser.add_argument("premise", help="一句话故事前提")
    parser.add_argument("--preset", default="storybook", choices=sorted(PRESETS))
    parser.add_argument(
        "--aspect", default="9:16", choices=["9:16", "16:9", "1:1"]
    )
    parser.add_argument("--max-shots", type=int, default=5)
    parser.add_argument("--voice", default="soffy")
    parser.add_argument("--no-music", action="store_true")
    parser.add_argument(
        "--series", default=None,
        help="series name: enables the cross-episode asset registry",
    )
    parser.add_argument(
        "--library", default=None,
        help="asset library root (default: $HEVI_ASSET_LIBRARY or ~/.hevi/storyfilm_assets)",
    )
    parser.add_argument("--out", default=None, help="output dir")
    args = parser.parse_args(argv)

    if not os.getenv("MONID_API_KEY"):
        _load_repo_env()

    if args.out:
        out_dir = Path(args.out)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = Path.cwd() / "oneclick_output" / stamp

    try:
        ledger = run_oneclick_film(
            args.premise,
            preset=args.preset,
            aspect=args.aspect,
            max_shots=args.max_shots,
            voice=args.voice,
            music=not args.no_music,
            out_dir=out_dir,
            series=args.series,
            asset_library=args.library,
        )
    except Exception as exc:
        print(f"oneclick failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    print(f"film: {ledger['film']['path']}")
    print(f"duration_s: {ledger['film']['duration_s']}")
    print(f"cost_usd: {ledger['cost_usd']}")
    print(f"gates: {json.dumps(ledger['gates'], ensure_ascii=False)}")
    print(f"status: {ledger['status']}")
    print(f"ledger: {out_dir / 'oneclick_delivery.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
