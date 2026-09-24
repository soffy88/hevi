"""Canonical local/file delivery provider.

This is a real, local delivery target (an on-disk delivery drop), not a fake
external publish.  It exists so a finished production artifact can be
delivered somewhere verifiable without any external account or CLI: the
delivered file is a byte copy of the approved source, the destination is
confined to a configured delivery root, and a repeated call with the same
idempotency key never produces a second logical side effect.

It owns no orchestration state: job lifecycle/provenance stay in
``hevi.distribution`` (``DistributionJobStore``); this module is a provider.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from hevi.distribution.models import (
    DistributionAccount,
    DistributionArtifact,
    DistributionJob,
    DistributionPlatform,
    DistributionProvenance,
    DistributionResult,
)
from hevi.distribution.provider import DistributionProvider

DEFAULT_DELIVERY_ROOT = "data/distribution/delivered"

# Anything that could escape the delivery root, name an absolute path, or hide
# in a path segment.  Segments are validated, never sanitized into a different
# path than the caller asked for.
_UNSAFE_SEGMENT = re.compile(r"(^\.\.?$)|[\\/\x00]|^~|^[A-Za-z]:")

# Credential-looking material must never reach a delivery record.  This is a
# scan, not a redactor for our own outputs: matching content fails the call.
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|bearer)\b\s*[:=]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


class LocalFileDeliveryError(RuntimeError):
    """A local delivery prerequisite or safety gate failed."""

    def __init__(self, failure_class: str, message: str) -> None:
        super().__init__(f"{failure_class}: {message}")
        self.failure_class = failure_class


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_segment(value: str, *, field: str) -> str:
    text = str(value or "").strip()
    if not text or _UNSAFE_SEGMENT.search(text):
        raise LocalFileDeliveryError(
            "UNSAFE_DELIVERY_PATH", f"{field} is not a safe single path segment: {value!r}"
        )
    return text


def _contained(root: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and require it to stay inside ``root``."""

    resolved_root = root.expanduser().resolve()
    resolved = candidate.expanduser().resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise LocalFileDeliveryError(
            "PATH_CONTAINMENT_VIOLATION", f"delivery path escapes root: {resolved}"
        )
    return resolved


def scan_for_secrets(payload: Any) -> list[str]:
    """Return secret-looking findings in a delivery record (never the value)."""

    findings: list[str] = []
    for text in _strings(payload):
        for pattern in _SECRET_VALUE_PATTERNS:
            if pattern.search(text):
                findings.append(pattern.pattern)
                break
    return findings


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for key, item in value.items():
            out.extend(_strings(str(key)))
            out.extend(_strings(item))
        return out
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            out.extend(_strings(item))
        return out
    return []


class LocalFileDeliveryProvider(DistributionProvider):
    """Copy an approved artifact into a confined local delivery root."""

    name = "local_file"

    def __init__(self, *, root: str | Path | None = None) -> None:
        configured = root or os.getenv("HEVI_LOCAL_DELIVERY_ROOT") or DEFAULT_DELIVERY_ROOT
        self.root = Path(configured).expanduser()

    # ── destination planning ────────────────────────────────────────────────

    def destination_for(self, job: DistributionJob, source: Path) -> Path:
        platform = _safe_segment(str(job.platform), field="platform")
        account = _safe_segment(job.account_ref, field="account_ref")
        key = _safe_segment(job.idempotency_key, field="idempotency_key")
        filename = _safe_segment(source.name, field="filename")
        return _contained(self.root, self.root / platform / account / key / filename)

    # ── provider contract ───────────────────────────────────────────────────

    async def probe(self) -> dict[str, Any]:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {
                "provider": self.name,
                "reachable": False,
                "failure_class": "DELIVERY_ROOT_UNAVAILABLE",
                "message": str(exc),
            }
        return {
            "provider": self.name,
            "reachable": True,
            "delivery_root": str(self.root.expanduser().resolve()),
            "mode": "local_file_copy",
        }

    async def list_accounts(self) -> Sequence[DistributionAccount]:
        """A local drop has exactly one implicit account per platform."""

        return [
            DistributionAccount(
                account_ref="local",
                platform=platform,
                display_name="Local delivery drop",
                logged_in=True,
                capabilities=["publish"],
                provider_metadata={"mode": "local_file_copy"},
            )
            for platform in DistributionPlatform
        ]

    async def validate_account(self, account: DistributionAccount) -> bool:
        return account.account_ref == "local" and account.logged_in

    async def publish(self, job: DistributionJob, source: Path) -> DistributionResult:
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_file() or source_path.stat().st_size <= 0:
            raise LocalFileDeliveryError("UPLOAD_FAILURE", f"source is absent or empty: {source}")
        source_digest = _sha256(source_path)
        if job.source_artifact_sha256 and source_digest != job.source_artifact_sha256:
            raise LocalFileDeliveryError(
                "PROVENANCE_INCOMPLETE",
                "source sha256 changed after the job was created; refusing to deliver",
            )
        destination = self.destination_for(job, source_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        duplicate_side_effects = 0
        replay = destination.is_file() and destination.stat().st_size > 0
        if replay:
            if _sha256(destination) != source_digest:
                raise LocalFileDeliveryError(
                    "IDEMPOTENCY_CONFLICT",
                    "destination exists with different content for this idempotency key",
                )
        else:
            temp = destination.with_suffix(destination.suffix + ".part")
            shutil.copyfile(source_path, temp)
            os.replace(temp, destination)

        delivered_digest = _sha256(destination)
        if delivered_digest != source_digest:
            raise LocalFileDeliveryError(
                "DELIVERY_INTEGRITY_FAILED", "delivered copy hash differs from source hash"
            )
        record = {
            "provider": self.name,
            "mode": "local_file_copy",
            "delivery_root": str(self.root.expanduser().resolve()),
            "delivered_path": str(destination),
            "delivered_sha256": delivered_digest,
            "source_sha256": source_digest,
            "byte_size": destination.stat().st_size,
            "idempotency_key": job.idempotency_key,
            "replayed": replay,
        }
        findings = scan_for_secrets(record)
        if findings:
            raise LocalFileDeliveryError(
                "SECRET_MATERIAL_IN_DELIVERY_RECORD", f"secret-like material detected: {findings}"
            )
        artifact = DistributionArtifact(
            artifact_id=job.source_artifact_id,
            sha256=delivered_digest,
            uri=destination.as_uri(),
            media_type="video/mp4",
            byte_size=destination.stat().st_size,
        )
        provenance = DistributionProvenance(
            source_artifact_id=job.source_artifact_id,
            source_artifact_sha256=source_digest,
            provider=self.name,
            platform=job.platform,
            account_ref=job.account_ref,
            provider_request={
                "mode": "local_file_copy",
                "delivery_root": str(self.root.expanduser().resolve()),
                "idempotency_key": job.idempotency_key,
            },
            provider_job_ref=job.idempotency_key,
            provider_result={"delivered_path": str(destination), "replayed": replay},
            evidence_refs=[destination.as_uri()],
        )
        return DistributionResult(
            job=job.model_copy(
                update={"state": "PUBLISHED", "provider_job_ref": job.idempotency_key, "provenance": provenance}
            ),
            artifact=artifact,
            provider_status="idempotent_replay" if replay else "delivered",
            success=True,
            duplicate_side_effects=duplicate_side_effects,
            message=(
                "existing delivered file returned without a duplicate copy"
                if replay
                else "artifact copied into the local delivery root"
            ),
        )

    async def schedule(self, job: DistributionJob, source: Path) -> DistributionResult:
        if job.scheduled_at is None:
            raise LocalFileDeliveryError(
                "INVALID_REQUEST", "schedule requires scheduled_at for a local delivery"
            )
        return await self.publish(job, source)

    async def save_draft(self, job: DistributionJob, source: Path) -> DistributionResult:
        raise LocalFileDeliveryError(
            "UNSUPPORTED", "local file delivery has no draft state; publish is the only operation"
        )

    async def poll(self, job: DistributionJob) -> DistributionResult:
        destination = _contained(
            self.root,
            self.root
            / _safe_segment(str(job.platform), field="platform")
            / _safe_segment(job.account_ref, field="account_ref")
            / _safe_segment(job.idempotency_key, field="idempotency_key"),
        )
        files = sorted(item for item in destination.glob("*") if item.is_file()) if destination.is_dir() else []
        if not files:
            return DistributionResult(
                job=job,
                provider_status="not_delivered",
                success=False,
                failure_class="DELIVERY_MISSING",
                message="no delivered file for this job",
            )
        delivered = files[0]
        digest = _sha256(delivered)
        return DistributionResult(
            job=job.model_copy(update={"state": "PUBLISHED"}),
            artifact=DistributionArtifact(
                artifact_id=job.source_artifact_id,
                sha256=digest,
                uri=delivered.as_uri(),
                media_type="video/mp4",
                byte_size=delivered.stat().st_size,
            ),
            provider_status="delivered",
            success=True,
            message="delivered file confirmed on disk",
        )

    async def history(self, *, platform: str | None = None) -> Sequence[dict[str, Any]]:
        root = self.root.expanduser()
        if not root.is_dir():
            return []
        entries: list[dict[str, Any]] = []
        for item in sorted(root.rglob("*")):
            if not item.is_file() or item.name.endswith(".part"):
                continue
            relative = item.relative_to(root)
            if platform is not None and relative.parts and relative.parts[0] != platform:
                continue
            entries.append(
                {
                    "platform": relative.parts[0] if relative.parts else "",
                    "path": str(item),
                    "sha256": _sha256(item),
                    "byte_size": item.stat().st_size,
                }
            )
        return entries


def local_file_provider(root: str | Path | None = None) -> LocalFileDeliveryProvider:
    return LocalFileDeliveryProvider(root=root)


__all__ = [
    "DEFAULT_DELIVERY_ROOT",
    "LocalFileDeliveryError",
    "LocalFileDeliveryProvider",
    "local_file_provider",
    "scan_for_secrets",
]
