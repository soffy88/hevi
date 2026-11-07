"""Director dials and the sound-clock contract (``qa.director_dials``).

Clean-room rewrite of the *method* of the director dials in
``win4r/video-director`` (METHODOLOGY.md lists the convergent
principles; SKILL.md carries the dials): every film declares four
dials -- clock, continuity, register and text-policy -- and the
dials are coupled, so a declaration that contradicts itself is
caught before it can drift a film. No text, code or script from
the source repository is copied here, and no dial value is
copied from the source: the value sets below are hevi's own
working vocabulary, chosen so each coupling rule can be checked
against a timeline record the pipeline already produces.

Dials
-----
* ``clock``: what time is measured against -- ``music`` (the
  beat grid), ``voice`` (the spoken line) or ``reads`` (the
  time a viewer needs to read what is on screen).
* ``continuity``: how strictly shots must agree with each
  other -- ``strict`` (locked anchors/characters), ``loose``
  (mood carries across cuts) or ``montage`` (deliberate
  discontinuity is the point).
* ``register``: the film's manner of address -- ``formal``,
  ``plain`` or ``playful``.
* ``text_policy``: what on-screen text is for -- ``minimal``
  (hook/CTA only), ``terms`` (key terms are shown as well as
  said) or ``captioned`` (full captions carry the wording).

Coupling rules (each is checked; a broken rule fails the
declaration, it is not silently repaired):

* R1 music clock needs a bpm.
* R2 reads clock needs a non-empty per-shot reads list.
* R3 strict continuity needs locked anchors.
* R4 ``terms`` text-policy needs a terms list (said+shown).
* R5 a voice clock with SFX needs every SFX entry to point at
  a beat (an SFX that lands nowhere lands on the voice).

The sound-clock contract is a declaration only, and it says so.
``sound_clock_contract()`` reports which parts of the full
sound clock are measured by an existing hevi capability and
which are still ``planned_not_measured``: SFX peak placement
against measured audio peaks, the sparse-mix no-hard-limit
rule, and the loudnorm/ebur128 divergence note have no
measurement in hevi today. Loudness targets themselves *are*
measured, by ``audio.mix_recipe`` (-14 +/- 2 LUFS, true peak
at most -1 dB, VO -16, ducking); this module never re-measures
them and never claims the unmeasured parts are done.
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

CLOCKS = ("music", "voice", "reads")
CONTINUITIES = ("strict", "loose", "montage")
REGISTERS = ("formal", "plain", "playful")
TEXT_POLICIES = ("minimal", "terms", "captioned")

# Sound-clock status: what is measured, and what is only declared.
# SFX peak placement, the sparse-mix rule and the loudnorm/ebur128
# note are planned_not_measured: no hevi capability measures them
# today, and declaring them here must not be read as implementing
# them. Loudness targets are the one measured part, owned by
# audio.mix_recipe, referenced here, never duplicated.
SOUND_CLOCK_CONTRACT: dict[str, Any] = {
    "loudness_targets": {
        "status": "measured_by",
        "measured_by": "audio.mix_recipe",
        "detail": "integrated -14 +/- 2 LUFS, true peak at most -1 dB, "
                  "VO -16, voice-keyed ducking",
    },
    "sfx_peak_placement": {
        "status": "planned_not_measured",
        "detail": "SFX are not placed against measured audio peaks in hevi today",
    },
    "sparse_mix_no_hard_limit": {
        "status": "planned_not_measured",
        "detail": "no sparse-mix rule (no hard limiting on sparse mixes) is measured in hevi today",
    },
    "loudnorm_ebur128_note": {
        "status": "planned_not_measured",
        "detail": "the loudnorm/ebur128 measurement divergence is not recorded anywhere in hevi today",
    },
}


def sound_clock_contract() -> dict[str, Any]:
    """The sound-clock contract: measured parts named, the rest planned."""
    return {
        "capability": "qa.director_dials",
        "contract": "sound_clock",
        "items": dict(SOUND_CLOCK_CONTRACT),
        "note": (
            "Declaration only. planned_not_measured items have no "
            "measurement behind them; do not present them as done."
        ),
    }


def declare_dials(dials: dict[str, Any]) -> dict[str, Any]:
    """Validate one dial declaration and check the coupling rules.

    Returns ``verdict`` ``"pass"`` when all four dials are known
    values and no coupling rule is broken, ``"fail"`` otherwise.
    Unknown dial values and broken rules are listed, never
    repaired silently. Missing optional evidence (bpm, reads,
    anchors, terms) is a coupling failure only when the dial
    that needs it is selected.
    """
    if not isinstance(dials, dict):
        raise CapabilityError("qa.director_dials: dials must be an object (dict)")
    violations: list[str] = []
    warnings: list[str] = []

    clock = dials.get("clock")
    continuity = dials.get("continuity")
    register_value = dials.get("register")
    text_policy = dials.get("text_policy")
    if clock not in CLOCKS:
        violations.append(f"R0: clock must be one of {list(CLOCKS)}, got {clock!r}")
    if continuity not in CONTINUITIES:
        violations.append(
            f"R0: continuity must be one of {list(CONTINUITIES)}, got {continuity!r}")
    if register_value not in REGISTERS:
        violations.append(
            f"R0: register must be one of {list(REGISTERS)}, got {register_value!r}")
    if text_policy not in TEXT_POLICIES:
        violations.append(
            f"R0: text_policy must be one of {list(TEXT_POLICIES)}, got {text_policy!r}")

    # R1: music clock needs a bpm.
    if clock == "music":
        bpm = dials.get("bpm")
        if not isinstance(bpm, (int, float)) or isinstance(bpm, bool) or float(bpm) <= 0:
            violations.append("R1: clock=music requires a positive bpm")
    # R2: reads clock needs per-shot reads.
    if clock == "reads":
        reads = dials.get("reads")
        if not isinstance(reads, list) or not reads:
            violations.append("R2: clock=reads requires a non-empty reads list")
    # R3: strict continuity needs locked anchors.
    if continuity == "strict":
        anchors = dials.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            violations.append("R3: continuity=strict requires a non-empty anchors list")
    # R4: terms text-policy needs a terms list.
    if text_policy == "terms":
        terms = dials.get("terms")
        if not isinstance(terms, list) or not terms:
            violations.append("R4: text_policy=terms requires a non-empty terms list")
    # R5 is timeline-relative; here it only warns when SFX are
    # declared without beats in the same declaration.
    sfx = dials.get("sfx")
    beats = dials.get("beats")
    if isinstance(sfx, list) and sfx and clock == "voice":
        if not isinstance(beats, list) or not beats:
            violations.append(
                "R5: clock=voice with SFX requires beats for the SFX to point at")
    if dials.get("sound_clock") is not None and not isinstance(dials.get("sound_clock"), dict):
        violations.append("sound_clock must be an object when declared")
    if "bpm" in dials and clock != "music":
        warnings.append("bpm is declared but the clock is not music; bpm is ignored")
    if "reads" in dials and clock != "reads":
        warnings.append("reads are declared but the clock is not reads")

    verdict = "fail" if violations else "pass"
    return {
        "capability": "qa.director_dials",
        "verdict": verdict,
        "dials": {
            "clock": clock,
            "continuity": continuity,
            "register": register_value,
            "text_policy": text_policy,
        },
        "violations": violations,
        "warnings": warnings,
        "sound_clock": sound_clock_contract()["items"],
    }


def check_dials_against_timeline(
    dials: dict[str, Any], timeline: dict[str, Any]
) -> dict[str, Any]:
    """Cross-check a dial declaration against a timeline record.

    The timeline is the ``qa.timeline_gate`` input shape. Clock
    agreement (timeline meta clock vs declared clock), bpm
    agreement, terms presence for the terms policy, reads
    presence for the reads clock, and SFX-to-beat pointing are
    checked. A missing timeline field is a mismatch that names
    the field, not a pass.
    """
    declaration = declare_dials(dials)
    mismatches: list[str] = list(declaration["violations"])
    if not isinstance(timeline, dict):
        raise CapabilityError("qa.director_dials: timeline must be an object (dict)")
    meta = timeline.get("meta")
    if not isinstance(meta, dict):
        mismatches.append("timeline meta is missing: clock/bpm cannot be checked")
        meta = {}
    if meta.get("clock") != dials.get("clock"):
        mismatches.append(
            f"timeline clock {meta.get('clock')!r} != declared clock {dials.get('clock')!r}")
    if dials.get("clock") == "music":
        if meta.get("bpm") != dials.get("bpm"):
            mismatches.append(
                f"timeline bpm {meta.get('bpm')!r} != declared bpm {dials.get('bpm')!r}")
    if dials.get("text_policy") == "terms":
        terms = timeline.get("terms")
        if not isinstance(terms, list) or not terms:
            mismatches.append("text_policy=terms but the timeline declares no terms")
    if dials.get("clock") == "reads":
        shots = timeline.get("shots", timeline.get("scenes"))
        reads_found = False
        if isinstance(shots, list):
            reads_found = any(
                isinstance(s, dict) and isinstance(s.get("reads"), list) and s["reads"]
                for s in shots)
        if not reads_found and not dials.get("reads"):
            mismatches.append("clock=reads but no shot in the timeline carries a reads list")
    sfx = timeline.get("sfx")
    if isinstance(sfx, list) and sfx:
        beats = timeline.get("beats") or []
        for idx, entry in enumerate(sfx):
            if isinstance(entry, dict) and entry.get("at") is not None:
                at = entry.get("at")
                if isinstance(at, (int, float)) and not any(
                        isinstance(b, (int, float)) and abs(float(at) - float(b)) <= 0.05
                        for b in beats):
                    mismatches.append(f"sfx[{idx}] at {at}s points at no beat")
    verdict = "fail" if mismatches else declaration["verdict"]
    return {
        "capability": "qa.director_dials",
        "verdict": verdict,
        "declaration": declaration,
        "mismatches": mismatches,
        "warnings": declaration["warnings"],
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dials = params.get("dials", {})
    if params.get("timeline") is not None:
        report = check_dials_against_timeline(dials, params["timeline"])
    else:
        report = declare_dials(dials)
    report_path = out_dir / "director_dials_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "pass": report["verdict"] == "pass",
            "violations": report.get("violations", report.get("mismatches", [])),
        },
    )


def register_director_dials_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.director_dials",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "dials": {"type": "object"},
                    "timeline": {"type": "object"},
                },
                "required": ["dials"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Director dials: one declaration per film (clock / "
                "continuity / register / text-policy) with coupling "
                "rules checked (music needs bpm, reads needs a reads "
                "list, strict continuity needs anchors, terms policy "
                "needs terms, voice-clock SFX need beats), plus an "
                "optional cross-check against a timeline record. "
                "The sound-clock contract is carried as a declaration: "
                "SFX peak placement, the sparse-mix rule and the "
                "loudnorm/ebur128 note are planned_not_measured."
            ),
            line="qa",
        )
    )
    return ["qa.director_dials"]


register_director_dials_capabilities_once()
