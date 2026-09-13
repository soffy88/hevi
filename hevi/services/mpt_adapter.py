"""MoneyPrinterTurbo adapter for the canonical Hevi task lifecycle.

MPT remains an external renderer, but its submission and completion now live
behind one Hevi TaskService adapter.  The adapter waits for MPT's terminal
state, resolves the shared storage path, and returns the same artifact
manifest contract as native Hevi renderers.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from hevi.production.artifacts import Artifact, ArtifactManifest
from hevi.resilience import RetryPolicy, with_retry_evidence
from hevi.resilience.errors import RetryableError
from hevi.services.mpt_integration import MPTClient
from hevi.video.quality_check import quality_report


def _terminal_state(value: Any) -> str:
    if isinstance(value, int) or (isinstance(value, str) and value.strip().lstrip("-").isdigit()):
        number = int(value)
        return "completed" if number == 1 else "failed" if number == -1 else "running"
    state = str(value or "").strip().lower()
    if state in {"complete", "completed", "success", "succeeded", "done"}:
        return "completed"
    if state in {"failed", "failure", "error", "cancelled", "canceled"}:
        return "failed"
    return "running"


def _video_values(payload: dict[str, Any]) -> list[str]:
    # MPT's combined preview may intentionally omit narration. Prefer the
    # canonical ``videos`` result so HEVI validates one final deliverable.
    for key in ("videos", "video_paths", "outputs", "combined_videos"):
        values: list[str] = []
        raw = payload.get(key)
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, str):
                values.append(item)
            elif isinstance(item, dict):
                value = item.get("path") or item.get("file") or item.get("url")
                if value:
                    values.append(str(value))
        if values:
            return list(dict.fromkeys(values))
    return []


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(raw_tmp, path)
    finally:
        if os.path.exists(raw_tmp):
            os.unlink(raw_tmp)


def _resolve_shared_path(value: str, config: dict[str, Any]) -> Path | None:
    candidate = Path(value.removeprefix("file://"))
    if candidate.is_file():
        return candidate
    container_root = "/MoneyPrinterTurbo/storage"
    host_root = Path(
        str(config.get("mpt_host_storage") or os.getenv("MPT_HOST_STORAGE", "services/mpt/storage"))
    )
    if value.startswith(container_root):
        mapped = host_root / value.removeprefix(container_root).lstrip("/")
        if mapped.is_file():
            return mapped
    if value.startswith("/tasks/"):
        mapped = host_root / value.lstrip("/")
        if mapped.is_file():
            return mapped
    storage_value = config.get("mpt_storage_path") or os.getenv("MPT_STORAGE_PATH", "")
    storage_root = Path(storage_value) if storage_value else None
    if storage_root is not None and storage_root.is_dir():
        mapped = storage_root / candidate.name
        if mapped.is_file():
            return mapped
    return None


def _remote_filename(value: str, index: int) -> str:
    name = Path(urlparse(value).path).name
    return name or f"mpt_video_{index:02d}.mp4"


async def execute_mpt_task(task: dict[str, Any], _pool: Any) -> dict[str, Any]:
    """Submit MPT work and translate its terminal result into Hevi artifacts."""

    config = dict(task.get("config_json") or {})
    request = dict(config.get("mpt_request") or {})
    topic = str(request.pop("topic", "") or task.get("topic") or "").strip()
    if not topic:
        raise ValueError("MPT topic 不能为空")
    poll_interval = max(0.05, float(request.pop("poll_interval_s", 1.0)))
    timeout_s = max(1.0, float(request.pop("timeout_s", os.getenv("MPT_POLL_TIMEOUT_S", 3600))))
    request.pop("require_audio", None)
    if not request.get("voice_name") and not request.get("custom_audio_file"):
        request["voice_name"] = "zh-CN-XiaoxiaoNeural-Female"
    output_dir = Path(config.get("output_dir") or Path("output/tasks") / str(task["id"]))
    output_dir.mkdir(parents=True, exist_ok=True)

    receipt_path = output_dir / "mpt-submission.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.is_file() else {}

    async def run_once(attempt: int) -> tuple[str, dict[str, Any], list[Path]]:
        async with MPTClient() as client:
            external_id = str(receipt.get("mpt_task_id") or "")
            if external_id:
                submitted = {"task_id": external_id}
            else:
                submitted = await client.generate_video(topic, **request)
                external_id = str(submitted.get("task_id") or submitted.get("id") or "")
                if not external_id:
                    raise RuntimeError("MPT 未返回 task_id")
                receipt.update({"logical_task_id": str(task["id"]), "mpt_task_id": external_id})
                _write_json_atomic(receipt_path, receipt)
                if attempt == 1 and os.getenv("HEVI_MPT_FAULT_INJECTION") == "transient_once":
                    receipt["fault_injected"] = "after_submit_before_poll"
                    _write_json_atomic(receipt_path, receipt)
                    raise RetryableError("controlled transient MPT transport failure")
            status = dict(submitted)
            deadline = time.monotonic() + timeout_s
            while _terminal_state(status.get("state")) == "running":
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"MPT 任务 {external_id} 等待超时")
                await asyncio.sleep(poll_interval)
                status = await client.check_task_status(external_id)

            if _terminal_state(status.get("state")) != "completed":
                raise RuntimeError(str(status.get("error") or f"MPT 任务失败: {external_id}"))
            paths: list[Path] = []
            for index, value in enumerate(_video_values(status), start=1):
                resolved = _resolve_shared_path(value, config)
                if resolved is None:
                    destination = output_dir / f"mpt_{index:02d}_{_remote_filename(value, index)}"
                    try:
                        resolved = await client.download_artifact(value, destination)
                    except Exception as exc:
                        raise RuntimeError(f"MPT artifact unavailable: {value}: {exc}") from exc
                paths.append(resolved)
            return external_id, status, paths

    (external_id, status, paths), retry_evidence = await with_retry_evidence(
        run_once,
        operation_id=f"mpt:{task['id']}",
        idempotency_key=str(config.get("idempotency_key") or task.get("idempotency_key") or task["id"]),
        policy=RetryPolicy(max_attempts=3, base_delay_s=0.1, max_delay_s=1.0, jitter=False),
    )
    if not paths:
        raise RuntimeError(
            "MPT 已完成但 Hevi 找不到视频文件；请挂载 MPT_STORAGE_PATH/MPT_HOST_STORAGE 共享目录"
        )

    quality_reports = [
        await quality_report(path, require_audio=True, n_samples=4) for path in paths
    ]
    quality_violations = [
        f"artifact[{index}]: {violation}"
        for index, report in enumerate(quality_reports)
        for violation in report.violations
    ]
    quality_passed = all(report.passed for report in quality_reports)

    artifacts = [
        Artifact.from_path(
            path,
            kind="video",
            media_type="video/mp4",
            primary=index == 0,
            logical_role="mpt_video",
            metadata={"mpt_task_id": external_id, "index": index},
        )
        for index, path in enumerate(paths)
    ]
    manifest = ArtifactManifest(artifacts=artifacts)
    return {
        "status": "completed",
        "result_video_path": str(paths[0]),
        "total_shots": len(paths),
        "completed_shots": len(paths),
        "quality": {
            # MPT's terminal state only proves that its own task runner
            # finished.  The HEVI quality gate must use measured media
            # evidence; it must never turn "files_found" into a static PASS.
            "passed": quality_passed,
            "verdict": "pass" if quality_passed else "fail",
            "violations": quality_violations,
            "checks": {
                "mpt_terminal_state": "completed",
                "artifacts_found": len(paths),
                "media_quality_reports": [
                    {
                        "duration": report.stats.duration,
                        "width": report.stats.width,
                        "height": report.stats.height,
                        "fps": report.stats.fps,
                        "has_audio": report.stats.has_audio,
                        "loudness_lufs": report.loudness_lufs,
                        "passed": report.passed,
                    }
                    for report in quality_reports
                ],
            },
        },
        "config_json": {
            **config,
            "mpt_task_id": external_id,
            "mpt_status": status,
            "artifact_manifest": manifest.model_dump(mode="json"),
            "retry_evidence": retry_evidence.to_dict(),
        },
    }


__all__ = ["execute_mpt_task"]
