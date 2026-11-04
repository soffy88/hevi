"""CosyVoice attribution note (``qa.cosyvoice_attribution_note``).

Reference table and citation check for CosyVoice, restated
in our own words from the read-only comparison report
(``hevi-vs-15-open-tools.md``). The attribution split is the
whole point of this note: the code repository moved under a
new organization name, while model releases still publish
under the original organization name. Citing the code
repository by its old address, or a model release by the new
organization name, both fail. Nothing here installs, runs,
or copies CosyVoice; the voice-cloning route is never
connected, and no claim of active maintenance survives the
observed slowdown. See FIFTEEN_TOOLS_ATTRIBUTION.md.
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

# Canonical code repository today (the old address redirects
# to it on the hosting side). Model releases still publish
# under the original organization name. The two names must
# never be mixed.
CODE_REPO = "QwenAudio/CosyVoice"
OLD_CODE_ADDRESS = "FunAudioLLM/CosyVoice"
MODEL_NAMESPACE = "FunAudioLLM"
COSYVOICE_LICENSE = "Apache-2.0"

# Maintenance slowed: last observed push 2026-05-25. A claim
# of active maintenance fails against this note.
LAST_PUSH = "2026-05-25"
MAINTENANCE = "slowed"

_NOTES: tuple[dict[str, str], ...] = (
    {
        "ref_kind": "code_repo",
        "name": CODE_REPO,
        "license": COSYVOICE_LICENSE,
        "maintenance": MAINTENANCE,
        "last_push": LAST_PUSH,
        "hevi_status": "gap: no CosyVoice reference in hevi; "
        "narration runs on other providers",
        "rule": "cite the code repository as QwenAudio/CosyVoice; "
        "the old FunAudioLLM address is a redirect, not the "
        "canonical name",
    },
    {
        "ref_kind": "model_release",
        "name": "FunAudioLLM/CosyVoice3-0.5B (model family example)",
        "license": "model weights are a separate release from the code",
        "maintenance": MAINTENANCE,
        "last_push": LAST_PUSH,
        "hevi_status": "gap: no CosyVoice model wired in",
        "rule": "cite model releases under the FunAudioLLM "
        "namespace; do not rename a model release under the "
        "code repository's organization",
    },
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def cosyvoice_notes() -> list[dict[str, str]]:
    """Return the CosyVoice attribution notes (copies)."""
    return [dict(note) for note in _NOTES]


def check_cosyvoice_citation(citation: Any) -> dict[str, Any]:
    """Validate a CosyVoice citation; never raises.

    Verdicts are ``pass`` / ``fail`` only. The cited name must
    match its kind: code repository under the new organization
    name, model release under the original one. Clone claims,
    installed claims, and active-maintenance claims all fail.
    """
    issues: list[dict[str, Any]] = []
    if not isinstance(citation, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue(
                    "citation_not_object",
                    "CosyVoice citation must be a JSON object",
                )
            ],
            "note": None,
        }
    ref_kind = citation.get("ref_kind")
    if ref_kind not in ("code_repo", "model_release"):
        issues.append(
            _issue(
                "ref_kind_unknown",
                "ref_kind must be one of code_repo, model_release",
            )
        )
        ref_kind = None
    name = citation.get("name")
    if not isinstance(name, str) or not name:
        issues.append(
            _issue("name_missing", "citation must name what it cites")
        )
        name = None
    note = None
    if ref_kind is not None and name is not None:
        if ref_kind == "code_repo":
            note = _NOTES[0]
            if name != CODE_REPO:
                issues.append(
                    _issue(
                        "code_repo_must_be_qwenaudio",
                        "the code repository is cited as "
                        f"{CODE_REPO}; {OLD_CODE_ADDRESS} is the "
                        "old address, not the canonical name",
                    )
                )
        else:
            note = _NOTES[1]
            if not name.startswith(MODEL_NAMESPACE + "/"):
                issues.append(
                    _issue(
                        "model_release_must_be_funaudiollm",
                        "model releases publish under the "
                        f"{MODEL_NAMESPACE} namespace; the code "
                        "repository's organization name must not be "
                        "used for a model release",
                    )
                )
    license_claim = citation.get("license_claim")
    if license_claim is not None and license_claim != COSYVOICE_LICENSE:
        issues.append(
            _issue(
                "license_mismatch",
                f"license claim {license_claim!r} does not match the "
                f"recorded code license {COSYVOICE_LICENSE}",
            )
        )
    if citation.get("clone_claim") is True:
        issues.append(
            _issue(
                "clone_route_never_connected",
                "the voice-cloning route is never connected; a "
                "clone claim fails",
            )
        )
    if citation.get("installed") is True:
        issues.append(
            _issue(
                "not_installed_here",
                "CosyVoice is not installed here; an installed "
                "claim fails",
            )
        )
    if citation.get("actively_maintained") is True:
        issues.append(
            _issue(
                "maintenance_slowed",
                "maintenance is recorded as slowed (last observed "
                f"push {LAST_PUSH}); an active-maintenance claim fails",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "note": dict(note) if note is not None else None,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_cosyvoice_citation(params.get("citation"))
    report_path = out_dir / "cosyvoice_citation.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_cosyvoice_attribution_note_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.cosyvoice_attribution_note",
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
                "CosyVoice attribution note: code repository cited "
                "as QwenAudio/CosyVoice, model releases under the "
                "FunAudioLLM namespace; clone, installed, and "
                "active-maintenance claims fail."
            ),
        )
    )
    return ["qa.cosyvoice_attribution_note"]


__all__ = [
    "CODE_REPO",
    "COSYVOICE_LICENSE",
    "LAST_PUSH",
    "MAINTENANCE",
    "MODEL_NAMESPACE",
    "OLD_CODE_ADDRESS",
    "check_cosyvoice_citation",
    "cosyvoice_notes",
    "register_cosyvoice_attribution_note_capabilities_once",
]
