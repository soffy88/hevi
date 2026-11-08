"""Open-skills method notes (``qa.open_skills_method_notes``).

Reference table and citation check for the 20 open-source items
in the "combine these open skills" list, restated in our own
words from the read-only comparison report
(``hevi-vs-20-open-skills.md``). Each entry records the
repository, the license as stated in the repository's own
LICENSE text (an API "NOASSERTION" is never treated as a
conclusion), the version/status observed, hevi's standing
against it, and what this graft does about it. Nothing here
installs, runs, or copies any of the 20 items. Two standing
notes are recorded as constants: the LosslessCut cutting method
is already internalized in ``edit_video_use`` (no separate
build), and OBS recording is not a finished-film pipeline step
(no build). Effect claims for GPU-bound or slow-maintenance
items fail unless real verification exists elsewhere. See
OPEN_SKILLS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# LosslessCut's method (per-segment extract + concat without
# re-encoding) is already the method inside edit_video_use; the
# tool itself is not wired in.
LOSSLESSCUT_NOTE = (
    "LosslessCut method already internalized in edit_video_use "
    "(per-segment extract plus concat without re-encoding); "
    "the LosslessCut tool itself is not installed or wired in."
)

# OBS is a live/record suite; screen recording is not a step of
# the finished-film pipeline, so no OBS capability is built.
OBS_NOTE = (
    "OBS Studio is a live/record suite; recording is not a "
    "finished-film pipeline step, so no OBS capability is built."
)

# Items whose real effects are unverified here (GPU-bound render,
# slow maintenance, or execution living elsewhere). A citation
# claiming a verified effect for one of these fails.
_UNVERIFIED_EFFECT: frozenset[int] = frozenset({1, 9, 12, 13, 15, 17})

# Items that must never be claimed as installed through this
# table: unlicensed method-only material, and GPL items kept to
# local-backend/method reference only.
_NEVER_INSTALLED_CLAIM: frozenset[int] = frozenset({2, 14, 18, 19})

_NOTES: tuple[dict[str, str], ...] = (
    {
        "index": "01",
        "item": "Remotion",
        "repo": "remotion-dev/remotion",
        "license": "per in-repo LICENSE text (API reports NOASSERTION)",
        "version_status": "v4.0.540 (2026-11-02); active",
        "hevi_status": "partial: smoke only, container render unproven",
        "graft_action": "method gate only (A1); true render is a separate case",
    },
    {
        "index": "02",
        "item": "Remotion Skills",
        "repo": "remotion-dev/skills",
        "license": "undeclared",
        "version_status": "no release; pinned commit c7cb2fdcacd134fb2ccb9b7a44f9ffa44e467271 (2026-11-02)",
        "hevi_status": "gap: official method notes not taken in",
        "graft_action": "method gate only (A1); method restated, no text copied",
    },
    {
        "index": "03",
        "item": "Anime.js",
        "repo": "juliangarnier/anime",
        "license": "MIT",
        "version_status": "v4 series, 4.5.0; v3 and v4 APIs incompatible",
        "hevi_status": "gap: v4 timeline vocabulary not taken in",
        "graft_action": "vocabulary gate only (A2), v4 only",
    },
    {
        "index": "04",
        "item": "Motion",
        "repo": "motiondivision/motion",
        "license": "MIT",
        "version_status": "active; open successor of Framer Motion",
        "hevi_status": "gap: entry-point split not taken in",
        "graft_action": "variant gate only (A3)",
    },
    {
        "index": "05",
        "item": "Manim",
        "repo": "ManimCommunity/manim",
        "license": "MIT",
        "version_status": "v0.22.1 (2026-10-27); active",
        "hevi_status": "present: video.manim_render",
        "graft_action": "none; no duplicate build",
    },
    {
        "index": "06",
        "item": "Lottie",
        "repo": "airbnb/lottie-web",
        "license": "MIT",
        "version_status": "maintenance slowed (last push 2025-09-01); web player",
        "hevi_status": "partial: sample mention only, no registered capability",
        "graft_action": "contract fake only (B1); player not bundled",
    },
    {
        "index": "07",
        "item": "MCP for Blender",
        "repo": "ahujasid/mcp-for-blender",
        "license": "MIT",
        "version_status": "active; community plugin, not a Blender Foundation product",
        "hevi_status": "present: video.blender_mcp (upstream 1.8)",
        "graft_action": "none; repository name correction recorded only",
    },
    {
        "index": "08",
        "item": "Three.js",
        "repo": "mrdoob/three.js",
        "license": "MIT",
        "version_status": "r187 (2026-10-30); hevi template on r169",
        "hevi_status": "present: three.js imaging upgrade and scene3d templates",
        "graft_action": "none; version gap noted, no new build",
    },
    {
        "index": "09",
        "item": "Three GPU Pathtracer",
        "repo": "gkjohnson/three-gpu-pathtracer",
        "license": "MIT",
        "version_status": "active; GPU path tracing, not realtime preview",
        "hevi_status": "gap: no pathtracer reference in hevi",
        "graft_action": "deferred; effect unverified, GPU case only",
    },
    {
        "index": "10",
        "item": "Jolt Physics",
        "repo": "jrouwe/JoltPhysics",
        "license": "MIT",
        "version_status": "active; C++ library, rigid-body and collision focus; soft-body support limited",
        "hevi_status": "partial: collision structure checks only, no rigid-body engine",
        "graft_action": "deferred (B3); compile binding is a real-machine case",
    },
    {
        "index": "11",
        "item": "postprocessing",
        "repo": "pmndrs/postprocessing",
        "license": "Zlib",
        "version_status": "active; distinct from the three.js bundled passes",
        "hevi_status": "partial: three.js bundled passes only, pmndrs build not wired",
        "graft_action": "variant gate only (A4); render chain unchanged",
    },
    {
        "index": "12",
        "item": "three.quarks",
        "repo": "Alchemist0823/three.quarks",
        "license": "MIT",
        "version_status": "maintenance slowed (last push 2026-05-21); pin a version",
        "hevi_status": "gap: no particle/VFX engine reference",
        "graft_action": "contract fake only (B2); true render is a GPU case",
    },
    {
        "index": "13",
        "item": "Tweakpane",
        "repo": "cocopon/tweakpane",
        "license": "MIT",
        "version_status": "maintenance slowed (last push 2026-03-15); dev/debug panel",
        "hevi_status": "gap: no parameter-panel reference",
        "graft_action": "deferred (B5); debug tool, not a finished-film step",
    },
    {
        "index": "14",
        "item": "ComfyUI",
        "repo": "Comfy-Org/ComfyUI",
        "license": "GPL-3.0",
        "version_status": "v0.44.0 (2026-11-04); hevi pins its deployed version, no upgrade",
        "hevi_status": "present: FastH3 local run, canvas executor, gateway contract",
        "graft_action": "none; local execution backend / method reference only",
    },
    {
        "index": "15",
        "item": "CosyVoice",
        "repo": "QwenAudio/CosyVoice",
        "license": "Apache-2.0",
        "version_status": "moved under QwenAudio; maintenance slowed (last push 2026-05-25)",
        "hevi_status": "gap: narration runs on Doubao/ElevenLabs; keys pending",
        "graft_action": "deferred (B4); voice-authorization gate first, GPU case",
    },
    {
        "index": "16",
        "item": "librosa",
        "repo": "librosa/librosa",
        "license": "ISC",
        "version_status": "1.0.0 (2026-08-11); active",
        "hevi_status": "present: audio.music_analyze and related analysis",
        "graft_action": "none; already internalized",
    },
    {
        "index": "17",
        "item": "WhisperX",
        "repo": "m-bain/whisperX",
        "license": "BSD-2-Clause",
        "version_status": "v3.8.6; commits active into 2026-10; word timestamps plus speaker separation",
        "hevi_status": "partial: stub comment only; live ASR runs on faster-whisper",
        "graft_action": "subtitle contract gate only (A5); execution is a GPU case",
    },
    {
        "index": "18",
        "item": "OBS Studio",
        "repo": "obsproject/obs-studio",
        "license": "GPL-2.0",
        "version_status": "active; live/record suite",
        "hevi_status": "not applicable: recording is not a finished-film step",
        "graft_action": "none; method note only",
    },
    {
        "index": "19",
        "item": "LosslessCut",
        "repo": "mifi/lossless-cut",
        "license": "GPL-2.0",
        "version_status": "active; lossless-cut front end over FFmpeg",
        "hevi_status": "present as method: edit_video_use already cuts without re-encoding",
        "graft_action": "none; method note only",
    },
    {
        "index": "20",
        "item": "FFmpeg",
        "repo": "FFmpeg/FFmpeg",
        "license": "per in-repo LICENSE text (API reports NOASSERTION); LGPL/GPL dual track",
        "version_status": "active; official git mirror",
        "hevi_status": "present: core dependency across cutting, joining, overlay, transcode",
        "graft_action": "none; core dependency, not a new item",
    },
)


def method_notes() -> list[dict[str, str]]:
    """Return the 20-item method-notes table (copies; never the live rows)."""
    return [dict(row) for row in _NOTES]


def _find_note(citation: dict[str, Any]) -> dict[str, str] | None:
    ref = citation.get("item")
    if isinstance(ref, int) and 1 <= ref <= 20:
        return _NOTES[ref - 1]
    if isinstance(ref, str):
        key = ref.strip().lower()
        for row in _NOTES:
            if key in (row["index"], row["item"].lower(), row["repo"].lower()):
                return row
    return None


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_method_note(citation: Any) -> dict[str, Any]:
    """Validate a citation against the 20-item table; never raises.

    Verdicts are ``pass`` / ``fail`` only. The cited item must be
    one of the 20; a license claim must match the table; a
    verified-effect claim fails for items whose effects are
    unverified here; an installed claim fails for items kept to
    method-only or local-backend reference.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(citation, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("citation_not_object", "citation must be a JSON object")
            ],
            "note": None,
        }
    note = _find_note(citation)
    if note is None:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue(
                    "unknown_item",
                    "cited item is not one of the 20 listed open skills",
                )
            ],
            "note": None,
        }
    license_claim = citation.get("license_claim")
    if license_claim is not None and license_claim != note["license"]:
        issues.append(
            _issue(
                "license_mismatch",
                f"license claim {license_claim!r} does not match the "
                f"recorded license for item {note['index']}",
            )
        )
    if citation.get("effect_verified") is True and int(note["index"]) in _UNVERIFIED_EFFECT:
        issues.append(
            _issue(
                "effect_unverified",
                f"item {note['index']} ({note['item']}) has no verified "
                "effect here; a verified-effect claim needs real "
                "verification recorded elsewhere",
            )
        )
    if citation.get("installed") is True and int(note["index"]) in _NEVER_INSTALLED_CLAIM:
        issues.append(
            _issue(
                "installed_claim_invalid",
                f"item {note['index']} ({note['item']}) is method-only "
                "or local-backend reference here and must not be "
                "claimed as installed through this table",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "note": dict(note),
        "losslesscut_note": LOSSLESSCUT_NOTE,
        "obs_note": OBS_NOTE,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_method_note(params.get("citation"))
    report["table_size"] = len(_NOTES)
    report_path = out_dir / "open_skills_method_notes.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_open_skills_method_notes_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.open_skills_method_notes",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "citation": {"type": "object"},
                },
                "required": ["citation"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Open-skills method notes: the 20-item license and "
                "version table with a citation check; license claims "
                "must match, unverified-effect and installed claims "
                "fail where the table says so."
            ),
        )
    )
    return ["qa.open_skills_method_notes"]


__all__ = [
    "LOSSLESSCUT_NOTE",
    "OBS_NOTE",
    "method_notes",
    "check_method_note",
    "register_open_skills_method_notes_capabilities_once",
]
