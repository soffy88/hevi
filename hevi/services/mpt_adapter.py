"""MoneyPrinterTurbo adapter for the canonical Hevi task lifecycle.

MPT remains an external renderer, but its submission and completion now live
behind one Hevi TaskService adapter.  The adapter waits for MPT's terminal
state, resolves the shared storage path, and returns the same artifact
manifest contract as native Hevi renderers.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from hevi.production.artifacts import Artifact, ArtifactManifest
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
    values: list[str] = []
    for key in ("videos", "combined_videos", "video_paths", "outputs"):
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
    return list(dict.fromkeys(values))


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
    output_dir = Path(config.get("output_dir") or Path("output/tasks") / str(task["id"]))
    output_dir.mkdir(parents=True, exist_ok=True)

    async with MPTClient() as client:
        submitted = await client.generate_video(topic, **request)
        external_id = str(submitted.get("task_id") or submitted.get("id") or "")
        if not external_id:
            raise RuntimeError("MPT 未返回 task_id")
        status = dict(submitted)
        deadline = time.monotonic() + timeout_s
        while _terminal_state(status.get("state")) == "running":
            if time.monotonic() >= deadline:
                raise TimeoutError(f"MPT 任务 {external_id} 等待超时")
            await asyncio.sleep(poll_interval)
            status = await client.check_task_status(external_id)

        state = _terminal_state(status.get("state"))
        if state != "completed":
            raise RuntimeError(str(status.get("error") or f"MPT 任务失败: {external_id}"))
        paths: list[Path] = []
        for index, value in enumerate(_video_values(status), start=1):
            resolved = _resolve_shared_path(value, config)
            if resolved is None:
                # MPT's current API returns /tasks/... URIs. Download those
                # into the canonical Hevi task directory when the services do
                # not share a volume.
                destination = output_dir / f"mpt_{index:02d}_{_remote_filename(value, index)}"
                try:
                    resolved = await client.download_artifact(value, destination)
                except Exception as exc:
                    raise RuntimeError(f"MPT artifact unavailable: {value}: {exc}") from exc
            paths.append(resolved)
    if not paths:
        raise RuntimeError(
            "MPT 已完成但 Hevi 找不到视频文件；请挂载 MPT_STORAGE_PATH/MPT_HOST_STORAGE 共享目录"
        )

    quality_reports = [
        await quality_report(path, require_audio=False, n_samples=4) for path in paths
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
        },
    }


__all__ = ["execute_mpt_task"]
