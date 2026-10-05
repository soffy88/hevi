"""Production artifact verification — V0..V3, fail-closed, with evidence.

    Artifact -> V0 -> V1 -> V2 -> V3 -> Evidence -> Receipt

This module is the *orchestration* of the four levels, not a second authority.
Each level reuses the module that already owns it:

    V0 existence   -> hevi.artifact.qualify.ArtifactDescriptor
    V1 media       -> hevi.artifact.qualify.qualify (ffprobe-backed probe)
    V2 contract    -> hevi.creative.director_contract.ShotSpec
    V3 creative    -> hevi.creative.autonomous.verdict.ProductionVerdictAuthority

The rule that makes the whole thing safe is the same one `qualify` already
enforces and that spec §7/§8 demands: **an unobserved check is not a pass.** A
level that could not observe its input reports ``UNKNOWN``, and ``UNKNOWN`` never
propagates to a receipt status of ``ACCEPTED``.

Concretely, this differs from a fail-open probe in three ways:

1. A missing ffprobe is ``UNKNOWN`` at V1, not a pass.
2. A technically valid video that misses its ShotSpec duration bound is a V2
   ``FAIL`` — the spec's "a technically valid video can still fail V2".
3. V3 is aggregated from named sources. An empty input set is ``UNKNOWN``, and
   human review is recorded as a decision rather than being inferred.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from hevi.artifact.checks import CheckOperator, CheckRequirement
from hevi.artifact.qualify import describe, qualify
from hevi.creative.autonomous.verdict import (
    ProductionVerdictAuthority,
    VerdictInput,
    VerdictOutcome,
)

#: Version of this orchestration. Recorded in every receipt.
VERIFIER_VERSION = "production.verification-v1"


class Level(StrEnum):
    V0 = "V0"
    V1 = "V1"
    V2 = "V2"
    V3 = "V3"


class LevelOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    #: nothing could be observed. Distinct from FAIL: not a defect, not a pass.
    UNKNOWN = "UNKNOWN"
    #: a named human looked at it and said otherwise.
    REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"


#: Terminal states for a level. UNKNOWN is not one of them: it must be resolved
#: by re-running with a working probe, or by a human, before acceptance.
_SETTLED = frozenset({LevelOutcome.PASS, LevelOutcome.FAIL, LevelOutcome.REQUIRES_HUMAN_REVIEW})


class ReceiptStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    #: evidence is incomplete. Cannot be accepted, and must not be called a failure.
    UNVERIFIED = "UNVERIFIED"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class LevelResult:
    """One verification level's outcome, with the reason it is not better."""

    level: Level
    outcome: LevelOutcome
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def blocking(self) -> bool:
        return self.outcome in {LevelOutcome.FAIL, LevelOutcome.UNKNOWN}

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "outcome": self.outcome.value,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class ShotContract:
    """The subset of a ShotSpec V2 can actually check.

    Kept deliberately small. Anything not listed here cannot be verified, so it
    is not claimed: a contract that silently omits a requirement would make V2
    look stronger than it is.
    """

    aspect_ratio: str | None = None
    duration_min_s: float | None = None
    duration_max_s: float | None = None
    requires_audio: bool = True
    min_width: int | None = None
    min_height: int | None = None

    @classmethod
    def from_shot_spec(
        cls, spec: Any, *, duration_tolerance_s: float = 1.0
    ) -> ShotContract:
        """Project a `director_contract.ShotSpec` onto the checkable subset."""
        duration = float(getattr(spec, "duration_sec", 0.0) or 0.0)
        return cls(
            duration_min_s=max(0.0, duration - duration_tolerance_s),
            duration_max_s=duration + duration_tolerance_s,
            requires_audio=bool(getattr(spec, "audio_intent", "")),
        )

    def requirements(self) -> tuple[CheckRequirement, ...]:
        reqs: list[CheckRequirement] = []
        if self.duration_min_s is not None:
            reqs.append(CheckRequirement("duration", self.duration_min_s, CheckOperator.GTE))
        if self.duration_max_s is not None:
            reqs.append(CheckRequirement("duration", self.duration_max_s, CheckOperator.LTE))
        if self.requires_audio:
            reqs.append(CheckRequirement("has_audio", True, CheckOperator.EQ))
        if self.min_width is not None:
            reqs.append(CheckRequirement("width", self.min_width, CheckOperator.GTE))
        if self.min_height is not None:
            reqs.append(CheckRequirement("height", self.min_height, CheckOperator.GTE))
        return tuple(reqs)


def verify_v0(path: str | Path) -> tuple[LevelResult, Any]:
    """V0 — the artifact exists, is non-empty, and has a real identity."""
    target = Path(path)
    if not target.is_file():
        return LevelResult(Level.V0, LevelOutcome.FAIL, "ARTIFACT_MISSING", {"path": str(target)}), None
    size = target.stat().st_size
    if size <= 0:
        return LevelResult(
            Level.V0, LevelOutcome.FAIL, "ARTIFACT_EMPTY",
            {"path": str(target), "size_bytes": size},
        ), None
    checksum = sha256_file(target)
    return (
        LevelResult(
            Level.V0, LevelOutcome.PASS, "",
            {"path": str(target), "size_bytes": size, "sha256": checksum},
        ),
        checksum,
    )


def verify_v1(
    path: str | Path, *, checksum: str = "", timeout_s: float = 30.0
) -> LevelResult:
    """V1 — media validity, via the existing fail-closed qualifier.

    A missing or failing ffprobe surfaces as ``qualify`` returning UNVERIFIED,
    which becomes ``UNKNOWN`` here. It never becomes PASS.
    """
    target = Path(path)
    payload = target.read_bytes()
    descriptor = describe(
        "production-artifact", payload,
        location=str(target), media_type="VIDEO",
    )
    result, state = qualify(
        descriptor, payload, (), validator="production.verification.v1",
    )
    probe = {
        name: check.observed
        for name, check in ((c.name, c) for c in result.checks)
        if name in {"container", "codec", "width", "height", "fps", "duration", "has_audio"}
    }
    evidence = {"artifact_state": state.value, "probe": probe}
    if state.value == "unverified":
        return LevelResult(
            Level.V1, LevelOutcome.UNKNOWN, "MEDIA_PROBE_FAILED", evidence
        )
    if not probe.get("duration"):
        return LevelResult(
            Level.V1, LevelOutcome.FAIL, "MEDIA_DURATION_INVALID", evidence
        )
    if probe.get("width") and probe.get("height"):
        evidence["aspect_ratio"] = _aspect(probe["width"], probe["height"])
    if checksum:
        evidence["sha256"] = checksum
    return LevelResult(Level.V1, LevelOutcome.PASS, "", evidence)


def verify_v1_subprocess(path: str | Path, *, timeout_s: float = 30.0) -> LevelResult:
    """V1 via ffprobe directly, for media the byte-based qualifier cannot load.

    Kept separate so a caller can choose the probe, not so two opinions exist:
    both report UNKNOWN rather than guessing when ffprobe is unavailable.
    """
    target = Path(path)
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format",
             "-of", "json", str(target)],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except FileNotFoundError:
        return LevelResult(
            Level.V1, LevelOutcome.UNKNOWN, "MEDIA_PROBE_FAILED:ffprobe not installed"
        )
    except subprocess.TimeoutExpired:
        return LevelResult(
            Level.V1, LevelOutcome.UNKNOWN, "MEDIA_PROBE_FAILED:ffprobe timed out"
        )
    if proc.returncode != 0:
        return LevelResult(
            Level.V1, LevelOutcome.FAIL, "MEDIA_PROBE_FAILED",
            {"stderr": proc.stderr[-500:]},
        )
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if not video:
        return LevelResult(Level.V1, LevelOutcome.FAIL, "MEDIA_CODEC_INVALID:no video stream")
    duration = float((data.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        return LevelResult(Level.V1, LevelOutcome.FAIL, "MEDIA_DURATION_INVALID")
    first = video[0]
    evidence = {
        "duration": duration,
        "codec": first.get("codec_name"),
        "width": first.get("width"),
        "height": first.get("height"),
        "fps": first.get("r_frame_rate"),
        "has_audio": bool(audio),
        "audio_codec": audio[0].get("codec_name") if audio else None,
        "audio_duration": float(audio[0].get("duration") or 0) if audio else None,
    }
    if first.get("width") and first.get("height"):
        evidence["aspect_ratio"] = _aspect(first["width"], first["height"])
    # Same envelope as verify_v1: V2 reads evidence["probe"], so both probes must
    # agree on where the observation lives.
    return LevelResult(Level.V1, LevelOutcome.PASS, "", {"probe": evidence})


def _aspect(width: Any, height: Any) -> str:
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError):
        return "unknown"
    if h == 0:
        return "unknown"
    g = _gcd(w, h)
    return f"{w // g}:{h // g}"


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a or 1


def verify_v2(
    evidence_v1: dict[str, Any], contract: ShotContract
) -> LevelResult:
    """V2 — contract compliance. A clean probe does not imply compliance."""
    observed = dict(evidence_v1.get("probe") or {})
    if not observed:
        return LevelResult(
            Level.V2, LevelOutcome.UNKNOWN, "CONTRACT_UNVERIFIABLE:no V1 evidence"
        )
    checks: list[dict[str, Any]] = []
    failed: list[str] = []
    unobserved: list[str] = []

    def _compare(name: str, ok: bool | None, got: Any, want: Any) -> None:
        if ok is None:
            unobserved.append(name)
            checks.append({"field": name, "expected": want, "observed": got, "observed?": False})
        else:
            checks.append({"field": name, "expected": want, "observed": got, "passed": ok})
            if not ok:
                failed.append(f"{name}: expected {want!r}, got {got!r}")

    if contract.aspect_ratio:
        _compare("aspect_ratio",
                 observed.get("aspect_ratio") == contract.aspect_ratio,
                 observed.get("aspect_ratio"), contract.aspect_ratio)
    if contract.duration_min_s is not None:
        _compare("duration_min_s",
                 observed.get("duration") is not None
                 and observed["duration"] >= contract.duration_min_s,
                 observed.get("duration"), f">={contract.duration_min_s}")
    if contract.duration_max_s is not None:
        _compare("duration_max_s",
                 observed.get("duration") is not None
                 and observed["duration"] <= contract.duration_max_s,
                 observed.get("duration"), f"<={contract.duration_max_s}")
    if contract.requires_audio:
        _compare("has_audio", observed.get("has_audio") is True,
                 observed.get("has_audio"), True)
    if contract.min_width is not None:
        _compare("min_width",
                 observed.get("width") is not None and observed["width"] >= contract.min_width,
                 observed.get("width"), f">={contract.min_width}")
    if contract.min_height is not None:
        _compare("min_height",
                 observed.get("height") is not None and observed["height"] >= contract.min_height,
                 observed.get("height"), f">={contract.min_height}")

    payload = {"checks": checks}
    if failed:
        return LevelResult(Level.V2, LevelOutcome.FAIL, "; ".join(failed), payload)
    if unobserved:
        return LevelResult(
            Level.V2, LevelOutcome.UNKNOWN,
            f"CONTRACT_UNOBSERVED:{sorted(unobserved)}", payload,
        )
    return LevelResult(Level.V2, LevelOutcome.PASS, "", payload)


def verify_v3(
    *, inputs: tuple[VerdictInput, ...], artifact_validated: bool,
    human_review: str | None = None,
) -> LevelResult:
    """V3 — creative verification, aggregated from named sources only."""
    if human_review is not None and human_review not in {"ACCEPT", "REVISE", "REJECT"}:
        raise ValueError(
            f"human_review must be ACCEPT, REVISE or REJECT; got {human_review!r}"
        )
    authority = ProductionVerdictAuthority()
    from hevi.validation.artifact import ValidationCheck, ValidationResult

    validation = ValidationResult(
        validator=VERIFIER_VERSION,
        checks=(ValidationCheck(
            name="artifact_validated", observed=artifact_validated, expected=True,
            operator=CheckOperator.EQ,
        ),),
    )
    verdict = authority.evaluate(inputs=inputs, artifact_validation=validation)
    evidence: dict[str, Any] = {
        "aggregate": verdict.outcome.value,
        "inputs": [{"source": i.source, "passed": i.passed, "detail": i.detail} for i in inputs],
        "artifact_validated": verdict.artifact_validated,
    }
    if human_review is not None:
        evidence["human_review"] = human_review

    if human_review == "REJECT":
        return LevelResult(Level.V3, LevelOutcome.FAIL, "HUMAN_REVIEW_REJECT", evidence)
    if verdict.outcome is VerdictOutcome.FAIL:
        return LevelResult(Level.V3, LevelOutcome.FAIL, "CREATIVE_VERDICT_FAIL", evidence)
    if verdict.outcome is not VerdictOutcome.PASS:
        # The machine aggregate has not settled. §20: human acceptance records a
        # decision, it does not manufacture evidence. A reviewer approving an
        # unvalidated artifact is not a creative pass, it is an unverified one.
        return LevelResult(
            Level.V3, LevelOutcome.UNKNOWN,
            "HUMAN_REVIEW_OVER_INSUFFICIENT_EVIDENCE", evidence,
        )
    if human_review == "ACCEPT":
        return LevelResult(Level.V3, LevelOutcome.PASS, "HUMAN_REVIEW_ACCEPT", evidence)
    if human_review == "REVISE":
        return LevelResult(Level.V3, LevelOutcome.REQUIRES_HUMAN_REVIEW, "HUMAN_REVIEW_REVISE", evidence)
    return LevelResult(Level.V3, LevelOutcome.PASS, "", evidence)


def verify_artifact(
    path: str | Path,
    *,
    run_id: str,
    task_id: str,
    contract: ShotContract | None = None,
    creative_inputs: tuple[VerdictInput, ...] = (),
    human_review: str | None = None,
    executor: str = "",
    provider: str = "",
    shot_spec_hash: str = "",
    revision_count: int = 0,
    use_subprocess_probe: bool = True,
) -> tuple[dict[str, Any], ReceiptStatus]:
    """Run V0..V3 in order. Returns the receipt dict and its status.

    The order matters: a level that fails stops the chain, because running V2
    against an artifact V1 already rejected would produce a contract verdict
    about bytes that are not a valid video.
    """
    levels: list[LevelResult] = []

    v0, checksum = verify_v0(path)
    levels.append(v0)
    if v0.outcome is not LevelOutcome.PASS:
        return _receipt(run_id, task_id, path, levels, executor, provider,
                        shot_spec_hash, revision_count), ReceiptStatus.REJECTED

    v1 = (verify_v1_subprocess(path) if use_subprocess_probe else verify_v1(path, checksum=checksum))
    levels.append(v1)
    if v1.outcome is not LevelOutcome.FAIL:
        levels.append(verify_v2(v1.evidence, contract or ShotContract()))
    else:
        levels.append(LevelResult(Level.V2, LevelOutcome.UNKNOWN, "SKIPPED:V1 failed"))

    if v1.outcome is LevelOutcome.PASS and creative_inputs:
        levels.append(verify_v3(
            inputs=creative_inputs,
            artifact_validated=True,
            human_review=human_review,
        ))
    elif human_review is not None or creative_inputs:
        # The artifact was never validated, so V3 has nothing to stand on. That is
        # insufficient evidence, not a creative failure, and it is reported as such
        # so a reviewer is not asked to bless an artifact nobody has probed.
        levels.append(LevelResult(
            Level.V3, LevelOutcome.UNKNOWN,
            "ARTIFACT_NOT_VALIDATED:V1 did not pass, so creative evidence is unusable",
            {"human_review": human_review} if human_review else {},
        ))

    return _receipt(run_id, task_id, path, levels, executor, provider,
                    shot_spec_hash, revision_count), _status_for(levels)


def _status_for(levels: list[LevelResult]) -> ReceiptStatus:
    if any(item.outcome is LevelOutcome.FAIL for item in levels):
        return ReceiptStatus.REJECTED
    # Any UNKNOWN anywhere means the evidence is incomplete. UNKNOWN is not a
    # pass and is not a failure; it blocks acceptance.
    if any(item.outcome is LevelOutcome.UNKNOWN for item in levels):
        return ReceiptStatus.UNVERIFIED
    if all(item.outcome in _SETTLED for item in levels) and levels:
        return ReceiptStatus.ACCEPTED
    return ReceiptStatus.UNVERIFIED


def _receipt(
    run_id: str, task_id: str, path: str | Path, levels: list[LevelResult],
    executor: str, provider: str, shot_spec_hash: str, revision_count: int,
) -> dict[str, Any]:
    """The §9 receipt. It records what was observed, not what was hoped."""
    status = _status_for(levels)
    artifact_id = f"artifact-{Path(path).stem}"
    v0 = next((item for item in levels if item.level is Level.V0), None)
    return {
        "run_id": run_id,
        "task_id": task_id,
        "artifact_id": artifact_id,
        "status": status.value,
        "verification": {"levels": [item.to_dict() for item in levels]},
        "evidence": {
            "artifact_path": str(path),
            "artifact_sha256": (v0.evidence.get("sha256") if v0 else ""),
            "artifact_size_bytes": (v0.evidence.get("size_bytes") if v0 else 0),
            "shot_spec_hash": shot_spec_hash,
            "verifier_version": VERIFIER_VERSION,
        },
        "revision_count": revision_count,
        "executor": executor,
        "provider": provider,
        "timestamp": _now(),
    }


__all__ = [
    "VERIFIER_VERSION",
    "Level",
    "LevelOutcome",
    "LevelResult",
    "ReceiptStatus",
    "ShotContract",
    "sha256_file",
    "verify_artifact",
    "verify_v0",
    "verify_v1",
    "verify_v1_subprocess",
    "verify_v2",
    "verify_v3",
]
