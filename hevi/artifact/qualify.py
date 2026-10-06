"""HEVI P8.4 — Descriptors, requirements and the qualification verdict.

    Artifact  ->  ValidationResult

**Existence is not validity.** A descriptor records that bytes were located. That is
``FOUND`` and nothing more. ``QUALIFIED`` requires every requirement to be observed
*and* satisfied, which is a strictly stronger statement — it is the difference between
"there is a file" and "the file is the video we asked for".

Four rules fall out of that:

1. **Existence yields FOUND, never VALID.** :func:`describe` cannot produce a
   qualification on its own.
2. **A checksum mismatch is INVALID_ARTIFACT**, distinct from a metadata mismatch. The
   first means the bytes are not what was receipted; the second means the bytes are
   right but the content is not acceptable. Different defects, different responses.
3. **Metadata mismatch is not a pass.** 1280x720 does not satisfy 1920x1080.
4. **Validation never repairs.** The probe reads; :func:`qualify` compares. Nothing
   here can write, remux or transcode.

An unobserved requirement cannot pass. That is the property that makes a missing probe
safe: if ffprobe is absent the artifact does not quietly qualify on defaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hevi.artifact.checks import CheckOperator, CheckRequirement, ValidationCheck
from hevi.artifact.probes import ArtifactProbe, probe_containerised, probe_image
from hevi.evidence.acquisition import checksum_bytes
from hevi.validation.artifact import ValidationResult

#: Fields a probe may report are mirrored here so qualification can reject an
#: observation it does not understand rather than silently ignoring it.
KNOWN_FIELDS = frozenset(
    {"checksum", "container", "codec", "width", "height", "resolution", "duration",
     "fps", "sample_rate", "channels", "format", "size_bytes", "has_audio"}
)


class ArtifactState(StrEnum):
    """How far an artifact got. Namespaced like every other layer's states."""

    #: bytes were located; nothing has been checked
    FOUND = "artifact_found"
    #: every requirement observed and satisfied
    QUALIFIED = "artifact_qualified"
    #: the bytes are not the ones the receipt covers
    INVALID_ARTIFACT = "invalid_artifact"
    #: the bytes match, but the content does not meet the requirement
    METADATA_MISMATCH = "metadata_mismatch"
    #: nothing could be observed, so nothing can be claimed
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class ArtifactDescriptor:
    """The object being validated. A location and an identity, not a verdict."""

    artifact_id: str
    location: str
    media_type: str
    size_bytes: int
    checksum: str

    def __post_init__(self) -> None:
        if not self.artifact_id:
            raise ValueError("ARTIFACT_DESCRIPTOR_WITHOUT_ID:artifact_id required")
        if not self.location:
            raise ValueError(
                f"ARTIFACT_DESCRIPTOR_WITHOUT_LOCATION:{self.artifact_id}"
            )
        if not self.media_type:
            raise ValueError(f"ARTIFACT_DESCRIPTOR_WITHOUT_MEDIA_TYPE:{self.artifact_id}")
        if self.size_bytes < 0:
            raise ValueError(f"NEGATIVE_ARTIFACT_SIZE:{self.artifact_id}")
        if not _is_sha256_hex(self.checksum):
            raise ValueError(
                f"ARTIFACT_DESCRIPTOR_BAD_CHECKSUM:{self.artifact_id}:"
                f"{self.checksum!r}; a descriptor without a real digest identifies nothing"
            )

    @property
    def state(self) -> ArtifactState:
        """A descriptor is only ever FOUND. Validity is decided by qualification."""
        return ArtifactState.FOUND

    def matches_payload(self, payload: bytes) -> bool:
        """Whether these bytes are the ones this descriptor names."""
        return self.checksum == checksum_bytes(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "location": self.location,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "state": self.state.value,
        }


def _is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def describe(
    artifact_id: str,
    payload: bytes,
    *,
    location: str,
    media_type: str,
) -> ArtifactDescriptor:
    """Build a descriptor. This is as far as existence gets."""
    return ArtifactDescriptor(
        artifact_id=artifact_id,
        location=location,
        media_type=media_type,
        size_bytes=len(payload),
        checksum=checksum_bytes(payload),
    )


def default_probe_for(media_type: str) -> ArtifactProbe:
    """The observation suited to a media type.

    Images are read by signature; containerised media needs ffprobe. Selection is by
    *media type*, not by what a provider is called.
    """
    if media_type.upper() == "IMAGE":
        return probe_image
    return probe_containerised


def evaluate_checks(
    requirements: tuple[CheckRequirement, ...], observed: dict[str, Any]
) -> tuple[ValidationCheck, ...]:
    """Compare what was required against what was observed."""
    return tuple(
        ValidationCheck(
            name=requirement.name,
            observed=observed.get(requirement.name),
            expected=requirement.expected,
            operator=requirement.operator,
        )
        for requirement in requirements
    )


def _checks_from_observed(
    observed: dict[str, Any], *, validator: str, artifact_id: str
) -> ValidationResult:
    """A validation result carrying every observation, when nothing was required."""
    checks = tuple(
        ValidationCheck(
            name=name,
            observed=value,
            expected=None,
            operator=CheckOperator.NON_EMPTY,
        )
        for name, value in sorted(observed.items())
        if name in KNOWN_FIELDS
    )
    return ValidationResult(
        validator=validator,
        checks=checks,
        validated_at=datetime.now(UTC),
        observed_checksum=observed.get("checksum", ""),
        artifact_id=artifact_id,
    )


def qualify(
    descriptor: ArtifactDescriptor,
    payload: bytes,
    requirements: tuple[CheckRequirement, ...] = (),
    *,
    probe: ArtifactProbe | None = None,
    validator: str = "artifact.qualify",
) -> tuple[ValidationResult, ArtifactState]:
    """Validate an artifact against requirements. Returns the verdict, never performs it.

    The checksum is recomputed from the payload rather than trusted from the
    descriptor. That is what makes rule 2 enforceable: if the bytes on disk differ
    from the descriptor, the artifact is ``INVALID_ARTIFACT`` regardless of what the
    probe reports.
    """
    if not descriptor.matches_payload(payload):
        result = ValidationResult(
            validator=validator,
            checks=(
                ValidationCheck(
                    name="checksum",
                    observed=checksum_bytes(payload),
                    expected=descriptor.checksum,
                    operator=CheckOperator.EQ,
                ),
            ),
            observed_checksum=checksum_bytes(payload),
            artifact_id=descriptor.artifact_id,
        )
        return result, ArtifactState.INVALID_ARTIFACT

    observer = probe or default_probe_for(descriptor.media_type)
    observed = dict(observer(payload))

    unknown = set(observed) - KNOWN_FIELDS
    if unknown:
        raise ValueError(f"PROBE_REPORTED_UNKNOWN_FIELDS:{sorted(unknown)}")

    observed.setdefault("checksum", descriptor.checksum)
    observed.setdefault("size_bytes", descriptor.size_bytes)

    if not requirements:
        return (
            _checks_from_observed(
                observed, validator=validator, artifact_id=descriptor.artifact_id
            ),
            ArtifactState.QUALIFIED,
        )

    checks = evaluate_checks(requirements, observed)
    result = ValidationResult(
        validator=validator,
        checks=checks,
        observed_checksum=observed["checksum"],
        artifact_id=descriptor.artifact_id,
    )

    # An unobserved requirement cannot pass. This is what makes a missing probe safe:
    # no ffprobe means no qualification on defaults.
    if any(not check.was_observed for check in checks):
        return result, ArtifactState.UNVERIFIED

    if all(check.passed for check in checks):
        return result, ArtifactState.QUALIFIED
    return result, ArtifactState.METADATA_MISMATCH


__all__ = [
    "ArtifactDescriptor",
    "ArtifactState",
    "describe",
    "evaluate_checks",
    "qualify",
]
