"""Score-rendered accompaniment as a capability (``audio.score_render``).

Write the music as an ABC score and get a locally rendered track whose
sync points land on picture time — or, with no score, give a product
category + scene list and let the direction templates draft the score
(the generated ABC is shipped as ``generated_score.abc`` so a human can
edit it and re-render in score mode).

Pipeline (all local / offline / numpy, see ``hevi.audio.score_render``):

* ABC 2.1 subset parser: headers, voices with ``inst=/role=/gain=/
  transpose=/kit=``, chords, ties, triplets, repeats, inline fields,
  dynamics / hairpins / fermata / rit / breath.
* Sync: ``!mark:name!`` in the score + ``align={name: seconds}``; every
  span between marks is independently time-fitted (< 5 ms residual),
  bend percentages and per-span measured RMS land in the sidecar.
* Render: numpy synth recipes (piano / pluck / strings / bass / sine /
  GM-subset drums, ``!hit!`` impacts), deterministic per seed, mastered
  to about -18 dBFS RMS with a -1.5 dBFS peak ceiling, 48 kHz stereo.
  Optional sampled timbres (``timbre="sampled"`` param, or per-voice
  ``timbre=`` / ``sampled_inst=`` / sampled ``inst=`` in the ABC):
  real-instrument VCSL samples (CC0, via mg-styles-15) pitch-shifted to
  the written notes through the same fit/mastering pipeline; unmapped
  voices fall back to the synth recipes and say so in the sidecar.

Exactly one input mode per call: ``abc`` XOR (``product`` + ``scenes``).
Both or neither raises ``CapabilityError`` — never a fake success.
"""

from __future__ import annotations

import json
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


def _render_score_render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.audio.score_render import (
        ScoreRenderError,
        _write_wav,
        generate_score,
        parse_abc,
        render_score,
    )

    abc_text = params.get("abc")
    product = params.get("product")
    scenes = params.get("scenes")
    has_score = bool(abc_text and str(abc_text).strip())
    has_direction = bool(product)
    if has_score and has_direction:
        raise CapabilityError(
            "audio.score_render: give either 'abc' or 'product'+'scenes', not both"
        )
    if not has_score and not has_direction:
        raise CapabilityError(
            "audio.score_render: one input mode is required: 'abc' or "
            "'product'+'scenes'"
        )

    effective_seed = int(params.get("seed", seed))
    sample_rate = int(params.get("sample_rate", 48000))
    timbre = params.get("timbre") or None
    if timbre is not None and timbre not in ("synth", "sampled"):
        raise CapabilityError(
            f"audio.score_render: bad 'timbre': {timbre!r} (synth|sampled)"
        )
    align_in = params.get("align") or None
    if align_in is not None:
        align_in = {str(k): float(v) for k, v in dict(align_in).items()}

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_path: Path | None = None

    try:
        if has_direction:
            if not scenes:
                raise CapabilityError(
                    "audio.score_render: direction mode requires 'scenes'"
                )
            gen_abc, gen_align = generate_score(
                str(product),
                [dict(s) for s in scenes],
                params.get("style"),
                seed=effective_seed,
            )
            abc_text = gen_abc
            # Scene starts are the sync targets; an explicit align may
            # refine individual marks on top of the generated defaults.
            merged = dict(gen_align)
            if align_in:
                merged.update(align_in)
            align_in = merged
            generated_path = out_dir / "generated_score.abc"
            generated_path.write_text(gen_abc, encoding="utf-8")
        score = parse_abc(str(abc_text))
        mix, sidecar = render_score(
            score,
            align_in,
            seed=effective_seed,
            sample_rate=sample_rate,
            timbre=timbre,
        )
    except CapabilityError:
        raise
    except ScoreRenderError as exc:
        raise CapabilityError(f"audio.score_render: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"audio.score_render failed: {exc}") from exc

    if has_direction:
        sidecar["product"] = str(product)
        sidecar["style"] = params.get("style") or sidecar.get("style")
        sidecar["generated_score"] = "generated_score.abc"

    wav_path = out_dir / "score.wav"
    _write_wav(wav_path, mix, sample_rate)
    sidecar_path = out_dir / "score_sidecar.json"
    sidecar_path.write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    return CapabilityResult(
        wav=str(wav_path),
        duration_s=float(sidecar["duration_s"]),
        sha256=compute_sha256(wav_path),
        qa={
            "sidecar": str(sidecar_path),
            "title": sidecar.get("title"),
            "engine": sidecar.get("engine"),
            "timbre": sidecar.get("timbre"),
            "sampled": sidecar.get("sampled"),
            "note_count": sidecar.get("note_count"),
            "marks": sidecar.get("marks"),
            "stretches": sidecar.get("stretches"),
            "warnings": sidecar.get("warnings"),
            "generated_score": str(generated_path) if generated_path else None,
        },
    )


def register_score_render_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True

    register(
        Capability(
            name="audio.score_render",
            kind="audio",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "abc": {
                        "type": "string",
                        "minLength": 1,
                        "description": "ABC 2.1 score text (subset; see "
                        "hevi.audio.score_render docstring). Sync points are "
                        "!mark:name! decorations in the score.",
                    },
                    "product": {
                        "type": "string",
                        "description": "Direction mode: product category "
                        "(devtool/ai/hardware/consumer/cute/creative/game/"
                        "data/explainer/calm/guofeng/hype).",
                    },
                    "scenes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "start_s": {"type": "number", "minimum": 0},
                                "end_s": {"type": "number", "exclusiveMinimum": 0},
                                "energy": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                            },
                            "required": ["id", "start_s", "end_s"],
                            "additionalProperties": True,
                        },
                        "minItems": 1,
                        "description": "Direction mode: scene list; each "
                        "scene start becomes a sync mark.",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["pulse", "piano", "cinematic", "lofi"],
                        "description": "Direction mode template override.",
                    },
                    "align": {
                        "type": "object",
                        "additionalProperties": {"type": "number"},
                        "description": "Mark name -> target time in seconds "
                        "in the finished film; times must increase with "
                        "the marks' score order.",
                    },
                    "timbre": {
                        "type": "string",
                        "enum": ["synth", "sampled"],
                        "description": "Timbre source for the whole "
                        "render: 'synth' (numpy recipes, default unless a "
                        "voice opts in) or 'sampled' (vendored VCSL real-"
                        "instrument samples, pitch-shifted to the score; "
                        "per-voice ABC attrs timbre=/sampled_inst= "
                        "override, unmapped voices fall back to synth).",
                    },
                    "seed": {
                        "type": "integer",
                        "description": "Render seed (timing jitter, drum "
                        "noise, direction-mode key/motif). Defaults to the "
                        "render seed argument.",
                    },
                    "sample_rate": {
                        "type": "integer",
                        "default": 48000,
                        "description": "Output sample rate (48 kHz default).",
                    },
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.6,
            render=_render_score_render,
            description=(
                "Score-rendered accompaniment (ABC -> local render, "
                "offline, seed-deterministic): parse an ABC score, fit "
                "!mark:name! sync points to picture times from 'align' "
                "(per-span tempo bending, <5 ms residual), and render "
                "piano/pluck/strings/bass/sine + GM-subset drums with "
                "dynamics, rit/fermata/breath tempo shaping and !hit! "
                "impacts. Timbre: numpy synth by default, or real-"
                "instrument VCSL samples (timbre='sampled' / per-voice "
                "timbre=/sampled_inst=/sampled inst=) pitch-shifted to "
                "the written notes through the same pipeline. Direction "
                "mode: product + scenes (+ optional "
                "style pulse/piano/cinematic/lofi) generates the ABC "
                "(generated_score.abc) and runs the same pipeline. "
                "Writes score.wav + score_sidecar.json (marks, stretches "
                "with bend % and measured RMS, warnings)."
            ),
            line="audio",
        )
    )
    return ["audio.score_render"]
