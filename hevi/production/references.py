"""HEVI P5.2 — reference adoption audit and licence boundary.

P5.2 is not "HEVI plus eight repositories". Each reference is read for its
*contract*, checked for licence compatibility, and then either mined for ideas
or refused outright. Nothing is vendored, and the default for any licence we
cannot positively verify is ``REFERENCE_ONLY``.

The licence facts below were read from each repository's ``LICENSE`` file at the
pinned revision — not from the GitHub licence API, which mis-detected two of the
nine (``NOASSERTION`` for SeeCut and saas-motion-kit). That discrepancy is
recorded rather than hidden, because "the API said it was fine" is exactly how
incompatible code gets imported.

HEVI itself ships no ``LICENSE`` file, so no reference can be asserted as
*compatible with HEVI's outbound terms*; only compatibility with the reference's
own terms is assessed. That asymmetry is the second reason the default is the
conservative one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class AdoptionMode(StrEnum):
    """How much of a reference HEVI may take."""

    REFERENCE_ONLY = "REFERENCE_ONLY"
    CONTRACT_ADOPT = "CONTRACT_ADOPT"
    CODE_ADOPT_ALLOWED = "CODE_ADOPT_ALLOWED"
    FORBIDDEN_IMPORT = "FORBIDDEN_IMPORT"


@dataclass
class ReferenceAdoptionRecord:
    """The audit record every reference project must produce."""

    repository: str
    revision: str
    license: str
    license_verified: bool
    capabilities_reviewed: list[str] = field(default_factory=list)
    adoption_mode: AdoptionMode = AdoptionMode.REFERENCE_ONLY
    adopted_contracts: list[str] = field(default_factory=list)
    rejected_architecture: list[str] = field(default_factory=list)
    code_import_allowed: bool = False
    notes: str = ""
    license_source: str = "LICENSE file at pinned revision"
    audited_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["adoption_mode"] = self.adoption_mode.value
        return d


# ── The nine references, audited ─────────────────────────────────────────

#: SeeCut is PolyForm Noncommercial 1.0.0. Noncommercial terms cannot be
#: reconciled with HEVI's production use, so it is forbidden outright.
SEECUT = ReferenceAdoptionRecord(
    repository="YeJe-cpu/SeeCut",
    revision="38e37e62c01a",
    license="PolyForm-Noncommercial-1.0.0",
    license_verified=True,
    capabilities_reviewed=[
        "raw-footage fine-cut",
        "take detection",
        "silence/filler classification",
        "jianying project emission",
    ],
    adoption_mode=AdoptionMode.FORBIDDEN_IMPORT,
    adopted_contracts=[
        # Independent implementation of the *idea* only: a CutPlan that records
        # source range, output range, reason and confidence for every cut.
        "CutPlan contract shape (reimplemented, not copied)",
    ],
    rejected_architecture=[
        "its own jianying emitter (HEVI already has P5 + P5.1 editable authority)",
        "its skill directory and prompt corpus",
        "its digital-human module",
        "any source, script, or component implementation",
    ],
    code_import_allowed=False,
    notes=(
        "PolyForm Noncommercial forbids commercial use; the GitHub licence API "
        "reported NOASSERTION, so the LICENSE file was read directly. Zero code, "
        "skills or prompts may enter HEVI. SeeCut's own NOTICE attribution "
        "requirement is moot because nothing is imported."
    ),
)

GUIZANG = ReferenceAdoptionRecord(
    repository="op7418/guizang-product-video-skill",
    revision="d6ddf740c444",
    license="AGPL-3.0-or-later + COMMERCIAL_LICENSING.md",
    license_verified=True,
    capabilities_reviewed=[
        "product video skill structure",
        "claim-to-screen mapping",
        "product surface discovery",
    ],
    adoption_mode=AdoptionMode.REFERENCE_ONLY,
    adopted_contracts=[
        "the *requirement* that a product claim maps to a concrete product state",
    ],
    rejected_architecture=[
        "AGPL copyleft code and its skill/agent scripts",
        "its prompt corpus and references directory",
        "its asset templates",
    ],
    code_import_allowed=False,
    notes=(
        "AGPL-3.0 is network-copyleft and the repository additionally ships "
        "COMMERCIAL_LICENSING.md, so the grant is dual-licensed and restrictive. "
        "Reference only. The claim->state->evidence chain is reimplemented from "
        "the specification, not from their text."
    ),
)

SAAS_MOTION_KIT = ReferenceAdoptionRecord(
    repository="tugrawork-creator/saas-motion-kit",
    revision="c1f8a08ecd67",
    license="MIT",
    license_verified=True,
    capabilities_reviewed=["motion component catalogue", "layout families", "entrance/exit vocabulary"],
    adoption_mode=AdoptionMode.CONTRACT_ADOPT,
    adopted_contracts=[
        "the idea that motion is selected from a registered component family "
        "rather than generated ad hoc",
        "layout-family naming as a fingerprint dimension",
    ],
    rejected_architecture=[
        "React/TSX component implementations",
        "its creative playbook content",
        "its example projects",
    ],
    code_import_allowed=False,
    notes=(
        "MIT is permissive, but HEVI already owns its Remotion component "
        "authority, so components are *selected* through the existing P1 "
        "MotionPlan rather than copied in. The GitHub API reported NOASSERTION; "
        "the LICENSE file is plain MIT."
    ),
)

JELLYFISH = ReferenceAdoptionRecord(
    repository="Forget-C/Jellyfish",
    revision="a9678194ddf2",
    license="Apache-2.0",
    license_verified=True,
    capabilities_reviewed=[
        "production pipeline decomposition",
        "entity/character consistency",
        "multi-stage generation graph",
    ],
    adoption_mode=AdoptionMode.CONTRACT_ADOPT,
    adopted_contracts=[
        "the explicit identity/relationship/continuity split for production entities",
        "the idea that a shot must be *prepared* before expensive generation",
    ],
    rejected_architecture=[
        "its own backend/frontend service runtime",
        "its task orchestration and job centre",
        "its provider layer",
    ],
    code_import_allowed=False,
    notes=(
        "Apache-2.0 permits reuse with notice. Adopted for contract shape only: "
        "HEVI keeps P3 as the single mission runtime and P4 as the single "
        "scheduler, so Jellyfish's service topology is explicitly rejected."
    ),
)

LANSHU = ReferenceAdoptionRecord(
    repository="cclank/lanshu-create-ai-presenter-video",
    revision="04f6bceab888",
    license="MIT",
    license_verified=True,
    capabilities_reviewed=["presenter-first video production", "audio-locked generation", "presenter framing"],
    adoption_mode=AdoptionMode.CONTRACT_ADOPT,
    adopted_contracts=[
        "PresenterPlan: generate the presenter from the finished AudioLock, "
        "never the reverse",
        "presenter framing as a per-shot decision rather than a global default",
    ],
    rejected_architecture=["its SKILL.md and agents directory", "its scripts", "its asset references"],
    code_import_allowed=False,
    notes=(
        "MIT. The audio-first rule is the load-bearing idea and it matches "
        "HEVI's existing P0 AudioLock, so it is adopted as a contract constraint "
        "on top of the canonical timeline rather than as new machinery."
    ),
)

HTML_EXPLAINER = ReferenceAdoptionRecord(
    repository="OneMoh/html-explainer",
    revision="7c6bd6a8f5d9",
    license="MIT",
    license_verified=True,
    capabilities_reviewed=["HTML/CSS explainer rendering", "deterministic frame rendering", "third-party notices"],
    adoption_mode=AdoptionMode.CONTRACT_ADOPT,
    adopted_contracts=[
        "HTML as a first-class renderer backend with frame-deterministic capture",
        "a THIRD_PARTY_NOTICES discipline for anything embedded in a render",
    ],
    rejected_architecture=["its node tooling and skill packaging", "its bundled assets", "its THIRD_PARTY_NOTICES content"],
    code_import_allowed=False,
    notes=(
        "MIT. HEVI implements its own sandboxed HTML backend rather than adopting "
        "this toolchain, because the sandbox and determinism guarantees are "
        "security properties HEVI must own."
    ),
)

POCKET_TTS = ReferenceAdoptionRecord(
    repository="kyutai-labs/pocket-tts",
    revision="d299fb6588f0",
    license="MIT",
    license_verified=True,
    capabilities_reviewed=["local CPU TTS", "streaming synthesis", "voice cloning", "latency/memory profile"],
    adoption_mode=AdoptionMode.CONTRACT_ADOPT,
    adopted_contracts=[
        "PocketTTSProvider capability declaration: LOCAL_TTS / STREAMING_TTS / VOICE_CLONING",
        "explicit supported_languages with a hard failure rather than a silent "
        "fallback when a language is unsupported",
    ],
    rejected_architecture=["its model weights", "its inference server", "its deployment scripts"],
    code_import_allowed=False,
    notes=(
        "MIT for the code; the model weights carry their own terms and are not "
        "vendored. Adoption is gated on an explicit language check so Chinese "
        "production can never silently fall through to this provider."
    ),
)

CAPCUT_CLI = ReferenceAdoptionRecord(
    repository="renezander030/capcut-cli",
    revision="c87d61dec9e2",
    license="MIT",
    license_verified=True,
    capabilities_reviewed=["draft emission via CLI", "draft lint", "capcut project structure"],
    adoption_mode=AdoptionMode.CONTRACT_ADOPT,
    adopted_contracts=[
        "EditableProjectBackend as an interface with a CLI-backed projection",
        "a draft lint pass covering missing materials, invalid segments and "
        "out-of-range sources",
    ],
    rejected_architecture=[
        "capcut-cli becoming an authority: it is a *projection* of the manifest, "
        "never the editable description itself",
        "floating 'latest' resolution of the binary",
    ],
    code_import_allowed=False,
    notes=(
        "MIT. The binary is invoked with a pinned version and revision, and every "
        "invocation goes through argument arrays with no shell. If the pinned "
        "binary is absent the backend reports NOT_AVAILABLE rather than "
        "substituting the internal builder."
    ),
)

VIDEO_USE = ReferenceAdoptionRecord(
    repository="browser-use/video-use",
    revision="b877063835e6",
    license="MIT",
    license_verified=True,
    capabilities_reviewed=["browser-driven video capture", "product surface interaction", "poster frames"],
    adoption_mode=AdoptionMode.CONTRACT_ADOPT,
    adopted_contracts=[
        "browser-driven product surface capture as a way to reach a *real* "
        "product state rather than depicting one",
        "ProductDemoState: an explicit, declared UI state before capture",
    ],
    rejected_architecture=["its skill packaging and helpers", "its agent loop", "its poster template"],
    code_import_allowed=False,
    notes=(
        "MIT. HEVI already owns a Playwright capture path "
        "(hevi/ops/p5_1_evidence.py); P5.2 extends that path with declared "
        "product states instead of adding a second browser authority."
    ),
)

REFERENCES: tuple[ReferenceAdoptionRecord, ...] = (
    JELLYFISH,
    LANSHU,
    HTML_EXPLAINER,
    SAAS_MOTION_KIT,
    POCKET_TTS,
    GUIZANG,
    CAPCUT_CLI,
    VIDEO_USE,
    SEECUT,
)

REFERENCES_BY_REPO: dict[str, ReferenceAdoptionRecord] = {
    record.repository: record for record in REFERENCES
}


def record_for(repository: str) -> ReferenceAdoptionRecord | None:
    return REFERENCES_BY_REPO.get(repository)


def adoption_mode_for(repository: str) -> AdoptionMode:
    record = record_for(repository)
    return record.adoption_mode if record else AdoptionMode.REFERENCE_ONLY


def assert_license_boundary() -> tuple[bool, list[str]]:
    """Fail closed if any reference would leak code into HEVI.

    ``CODE_IMPORTED`` must be 0 for every record until a per-reference
    compatibility audit is signed off; the default posture is that nothing is.
    """
    violations: list[str] = []
    for record in REFERENCES:
        if not record.license_verified:
            violations.append(f"UNVERIFIED_LICENSE:{record.repository}")
        if record.code_import_allowed and record.adoption_mode is AdoptionMode.FORBIDDEN_IMPORT:
            violations.append(f"CODE_ALLOWED_ON_FORBIDDEN:{record.repository}")
        if (
            record.adoption_mode is AdoptionMode.REFERENCE_ONLY
            and record.adopted_contracts
            and record.license.startswith("PolyForm")
        ):
            violations.append(f"NONCOMMERCIAL_CONTRACT_LEAK:{record.repository}")
    return (not violations), violations


def audit_summary() -> dict[str, Any]:
    """Machine-readable adoption audit."""
    ok, violations = assert_license_boundary()
    return {
        "audit_ok": ok,
        "violations": violations,
        "reference_count": len(REFERENCES),
        "code_imported_total": sum(1 for r in REFERENCES if r.code_import_allowed),
        "forbidden_import_total": sum(
            1 for r in REFERENCES if r.adoption_mode is AdoptionMode.FORBIDDEN_IMPORT
        ),
        "reference_only_total": sum(
            1 for r in REFERENCES if r.adoption_mode is AdoptionMode.REFERENCE_ONLY
        ),
        "contract_adopt_total": sum(
            1 for r in REFERENCES if r.adoption_mode is AdoptionMode.CONTRACT_ADOPT
        ),
        "records": [record.to_dict() for record in REFERENCES],
    }


#: The Hevi-side outward-licence posture. HEVI ships no LICENSE file, so no
#: reference can be claimed compatible with HEVI's own terms.
HEVI_OUTBOUND_LICENSE = "UNSPECIFIED (no LICENSE file in this repository)"


__all__ = [
    "HEVI_OUTBOUND_LICENSE",
    "REFERENCES",
    "REFERENCES_BY_REPO",
    "AdoptionMode",
    "ReferenceAdoptionRecord",
    "adoption_mode_for",
    "assert_license_boundary",
    "audit_summary",
    "record_for",
]
