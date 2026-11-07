"""Sandbox material reference gate (``qa.sandbox_material_reference_gate``).

Clean-room restatement of the "material references are real
links" discipline behind Toonflow's sandboxed node references
(see ``TOONFLOW_RECHECK_ATTRIBUTION.md``): inside a sandbox, a
node that claims a material must point at a real, identified
file that stays where the host put it. A reference that cannot
be confirmed is not guessed, and material is never moved around
for tidiness -- the host's returned location is authoritative.
This gate judges reference plans:

1. Every reference names a material id, a sha256, and a path.
   A sha that is not 64 lowercase hex digits, or all zeros,
   fails: it identifies nothing.
2. The path must stay inside the declared scope. A path that
   escapes the declared scope (``..`` or an absolute path
   outside it) fails and names the path; the gate never
   resolves a reference outside the scope it was given.
3. A reference that says the material was moved fails. Moving
   material to tidy a project breaks every earlier link that
   pointed at the old location.
4. The same material id bound to two different shas fails: one
   id, one content.

This gate judges plans only. It reads no file contents, calls
no generator, spends nothing, and never rewrites a reference
to make it pass.
"""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.sandbox_material_reference_gate: {detail}"}
    issue.update(extra)
    return issue


def _normalise_scope(declared_scope: Any) -> list[str]:
    if not isinstance(declared_scope, list) or not declared_scope:
        raise CapabilityError(
            "qa.sandbox_material_reference_gate: declared_scope must be "
            "a non-empty list of allowed root paths; without a declared "
            "scope, escape cannot be judged"
        )
    roots = []
    for root in declared_scope:
        if not isinstance(root, str) or not root:
            raise CapabilityError(
                "qa.sandbox_material_reference_gate: every declared_scope "
                "entry must be a non-empty path string"
            )
        roots.append(str(PurePosixPath(root)))
    return roots


def _path_within_scope(path: str, roots: list[str]) -> bool:
    candidate = PurePosixPath(path)
    if candidate.is_absolute():
        normalised = str(candidate)
        return any(
            normalised == root or normalised.startswith(root.rstrip("/") + "/")
            for root in roots
        )
    # Relative paths are resolved against each root in turn; any
    # ".." that climbs out of the root escapes the scope.
    parts: list[str] = []
    for part in candidate.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return False
            parts.pop()
        else:
            parts.append(part)
    return True


def check_sandbox_material_references(
    references: Any,
    *,
    declared_scope: Any,
) -> dict[str, Any]:
    """Check sandbox material references against the declared scope.

    Returns a report with ``ok``, the count checked, and the
    problems. A failing plan is listed, never silently repaired.
    """
    roots = _normalise_scope(declared_scope)
    if not isinstance(references, list) or not references:
        raise CapabilityError(
            "qa.sandbox_material_reference_gate: references must be a "
            "non-empty list of material reference records"
        )
    problems: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for index, record in enumerate(references):
        if not isinstance(record, dict):
            raise CapabilityError(
                "qa.sandbox_material_reference_gate: every reference must "
                "be an object with material_id, sha256 and path"
            )
        material_id = record.get("material_id")
        sha = record.get("sha256")
        path = record.get("path")
        if not isinstance(material_id, str) or not material_id:
            problems.append(
                _issue(
                    "missing_material_id",
                    f"reference {index} has no material_id",
                    index=index,
                )
            )
            continue
        if not isinstance(sha, str) or not _SHA_RE.match(sha) or set(sha) == {"0"}:
            problems.append(
                _issue(
                    "bad_sha256",
                    f"material {material_id!r} has sha256 {sha!r}, not 64 "
                    "lowercase hex digits identifying real content",
                    material_id=material_id,
                )
            )
        if material_id in seen and seen[material_id] != sha:
            problems.append(
                _issue(
                    "material_id_sha_conflict",
                    f"material id {material_id!r} is bound to two "
                    "different shas; one id, one content",
                    material_id=material_id,
                )
            )
        else:
            seen[material_id] = sha if isinstance(sha, str) else ""
        if not isinstance(path, str) or not path:
            problems.append(
                _issue(
                    "missing_path",
                    f"material {material_id!r} has no path",
                    material_id=material_id,
                )
            )
        elif not _path_within_scope(path, roots):
            problems.append(
                _issue(
                    "scope_escape",
                    f"material {material_id!r} path {path!r} escapes the "
                    f"declared scope {roots}",
                    material_id=material_id,
                    path=path,
                )
            )
        if record.get("moved") is True:
            problems.append(
                _issue(
                    "material_moved",
                    f"material {material_id!r} was moved for tidiness; "
                    "the host's returned location is authoritative and "
                    "earlier links must keep pointing at it",
                    material_id=material_id,
                )
            )
    return {
        "ok": not problems,
        "checked": len(references),
        "problems": problems,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_sandbox_material_references(
        params.get("references"),
        declared_scope=params.get("declared_scope"),
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "sandbox_material_reference_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_sandbox_material_reference_gate_capabilities_once() -> list[str]:
    """Register ``qa.sandbox_material_reference_gate`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.sandbox_material_reference_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "references": {"type": "array"},
                    "declared_scope": {"type": "array"},
                },
                "required": ["references", "declared_scope"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Sandbox material reference gate: every material "
                "reference must name an id, a real sha256, and a path "
                "inside the declared scope; references that escape the "
                "scope, move material, or bind one id to two contents "
                "fail. References are checked, never rewritten to pass."
            ),
            line="qa",
        )
    )
    return ["qa.sandbox_material_reference_gate"]
