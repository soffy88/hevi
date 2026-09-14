from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shlex
import time
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

PLATFORM_ALIASES: dict[DistributionPlatform, str] = {
    DistributionPlatform.DOUYIN: "dy",
    DistributionPlatform.KUAISHOU: "ks",
    DistributionPlatform.BILIBILI: "blbl",
    DistributionPlatform.XIAOHONGSHU: "xhs",
    DistributionPlatform.WECHAT_CHANNELS: "sph",
    DistributionPlatform.TOUTIAO: "tt",
    DistributionPlatform.BAIJIAHAO: "bjh",
    DistributionPlatform.FANQIE_VIDEO: "fqsp",
}


class MatrixMediaError(RuntimeError):
    def __init__(self, failure_class: str, message: str) -> None:
        super().__init__(message)
        self.failure_class = failure_class


class MatrixMediaDistributionProvider(DistributionProvider):
    """Invoke the isolated GPL MatrixMedia program; never import its source."""

    name = "matrixmedia"

    def __init__(
        self,
        *,
        executable: Sequence[str] | None = None,
        root: str | Path | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        env_bin = os.getenv("MATRIXMEDIA_BIN", "").strip()
        self.executable = tuple(executable or shlex.split(env_bin))
        root_value = root or os.getenv("MATRIXMEDIA_DIR", "")
        self.root = Path(root_value).expanduser() if root_value else None
        self.timeout_s = timeout_s

    def _command(self, *args: str) -> list[str]:
        if not self.executable:
            raise MatrixMediaError("MATRIXMEDIA_UNAVAILABLE", "MATRIXMEDIA_BIN is not configured")
        return [*self.executable, "cli", *args]

    async def _run(self, *args: str) -> dict[str, Any]:
        command = self._command(*args)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "ELECTRON_RUN_AS_NODE": ""},
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_s)
        except TimeoutError as exc:
            raise MatrixMediaError("TIMEOUT", "MatrixMedia CLI timed out") from exc
        except OSError as exc:
            raise MatrixMediaError("MATRIXMEDIA_UNAVAILABLE", str(exc)) from exc
        if process.returncode != 0:
            text = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
            failure = "ACCOUNT_LOGGED_OUT" if "login" in text.lower() else "PROVIDER_REJECTION"
            raise MatrixMediaError(failure, text or f"MatrixMedia exited {process.returncode}")
        raw = stdout.decode(errors="replace").strip()
        value: Any = None
        for line in reversed(raw.splitlines()):
            try:
                value = json.loads(line.strip())
                break
            except json.JSONDecodeError:
                continue
        if value is None:
            raise MatrixMediaError("INVALID_RESPONSE", "MatrixMedia did not return JSON")
        return value if isinstance(value, dict) else {"items": value}

    async def probe(self) -> dict[str, Any]:
        started = time.monotonic()
        try:
            result = await self._run("accounts", "--json")
        except MatrixMediaError as exc:
            return {"provider": self.name, "reachable": False, "failure_class": exc.failure_class, "message": str(exc)}
        return {"provider": self.name, "reachable": True, "latency_ms": round((time.monotonic() - started) * 1000, 2), "accounts": result}

    async def list_accounts(self) -> Sequence[DistributionAccount]:
        result = await self._run("accounts", "--json")
        raw_items = result.get("accounts", result.get("items", []))
        output: list[DistributionAccount] = []
        for item in raw_items if isinstance(raw_items, list) else []:
            platform = _platform(item.get("platform") or item.get("code"))
            if platform is None:
                continue
            output.append(
                DistributionAccount(
                    account_ref=str(item.get("account_ref") or item.get("phone") or item.get("id") or "unknown"),
                    platform=platform,
                    display_name=item.get("name"),
                    logged_in=bool(item.get("logged_in", item.get("isLogin", False))),
                    capabilities=["publish", "schedule", "draft"],
                    provider_metadata={"raw": item},
                )
            )
        return output

    async def validate_account(self, account: DistributionAccount) -> bool:
        return account.logged_in

    async def publish(self, job: DistributionJob, source: Path) -> DistributionResult:
        return await self._submit(job, source)

    async def schedule(self, job: DistributionJob, source: Path) -> DistributionResult:
        return await self._submit(job, source, "--publish-at", job.scheduled_at.isoformat() if job.scheduled_at else "")

    async def save_draft(self, job: DistributionJob, source: Path) -> DistributionResult:
        return await self._submit(job, source, "--draft")

    async def _submit(self, job: DistributionJob, source: Path, *extra: str) -> DistributionResult:
        alias = PLATFORM_ALIASES[job.platform]
        args = [
            "publish", "--platform", alias, "--file", str(source), "--title", job.title,
            "--description", job.description, "--phone", job.account_ref,
        ]
        for tag in job.tags:
            args.extend(("--tags", tag))
        args.extend(extra)
        try:
            raw = await self._run(*args)
        except MatrixMediaError as exc:
            state = "RETRYABLE_FAILED" if exc.failure_class in {"TIMEOUT", "UPLOAD_FAILURE"} else "NEEDS_ATTENTION"
            failed = job.model_copy(update={"state": state, "failure_class": exc.failure_class, "attempt": job.attempt + 1})
            return DistributionResult(job=failed, provider_status="failed", success=False, failure_class=exc.failure_class, message=str(exc))
        provider_ref = str(raw.get("id") or raw.get("job_id") or raw.get("external_id") or "") or None
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        artifact = DistributionArtifact(artifact_id=job.source_artifact_id, sha256=digest, uri=str(source))
        state = "DRAFTED" if "draft" in extra else ("SCHEDULED" if "--publish-at" in extra else "PUBLISHED")
        updated = job.model_copy(update={"state": state, "provider_job_ref": provider_ref, "attempt": job.attempt + 1})
        provenance = DistributionProvenance(
            source_artifact_id=job.source_artifact_id,
            source_artifact_sha256=digest,
            provider=self.name,
            platform=job.platform,
            account_ref=job.account_ref,
            provider_request={"command": "cli publish", "platform": alias, "idempotency_key": job.idempotency_key},
            provider_job_ref=provider_ref,
            provider_result=raw,
        )
        return DistributionResult(job=updated.model_copy(update={"provenance": provenance}), artifact=artifact, provider_status="success", success=True, message="MatrixMedia accepted the request")

    async def poll(self, job: DistributionJob) -> DistributionResult:
        history = await self.history(platform=job.platform.value)
        match = next((item for item in history if str(item.get("id")) == job.provider_job_ref), None)
        if match is None:
            return DistributionResult(job=job, provider_status="unknown", success=False, failure_class="NOT_FOUND", message="provider job not present in history")
        return DistributionResult(job=job, provider_status=str(match.get("status", "unknown")), success=match.get("status") == "success", message="history result normalized")

    async def history(self, *, platform: str | None = None) -> Sequence[dict[str, Any]]:
        args = ["history", "--json"]
        if platform:
            args.extend(("--platform", PLATFORM_ALIASES.get(DistributionPlatform(platform), platform)))
        result = await self._run(*args)
        items = result.get("history", result.get("items", []))
        return items if isinstance(items, list) else []


def _platform(value: Any) -> DistributionPlatform | None:
    text = str(value or "").lower()
    for platform, alias in PLATFORM_ALIASES.items():
        if text in {platform.value, alias}:
            return platform
    return None
