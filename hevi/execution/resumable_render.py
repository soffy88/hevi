"""Resumable multi-shot render used for crash-takeover and local live closure.

The production long-video orchestrator is a paid provider path.  This adapter
uses the same attempt/checkpoint/artifact contract so a second worker can
finish a crashed render without redoing shots that already committed a
checkpoint.  Live tests inject a crash by stopping after N shots; recovery
then claims a new attempt and continues from ``AttemptRepository.latest``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from hevi.production.artifacts import Artifact, ArtifactManifest


async def execute_checkpoint_render(task: dict[str, Any], pool: Any) -> dict[str, Any]:
    """Render remaining shots, checkpoint each boundary, then emit a final artifact."""

    task_id = str(task["id"])
    config = dict(task.get("config_json") or {})
    total = max(1, int(config.get("total_shots") or 4))
    output_dir = Path("output/tasks") / task_id
    output_dir.mkdir(parents=True, exist_ok=True)

    checkpoint = task.get("_resume_checkpoint")
    if checkpoint is None and pool is not None:
        from hevi.tasks.attempt_repository import AttemptRepository

        latest = await AttemptRepository(pool).latest(uuid.UUID(task_id))
        checkpoint = latest
    completed = int((checkpoint or {}).get("completed_shots") or 0)
    state = dict((checkpoint or {}).get("state_json") or {})
    shots: list[dict[str, Any]] = list(state.get("shots") or [])
    # Crash injection is first-attempt only. A resumed worker must finish.
    crash_after = None if completed > 0 else config.get("crash_after_shot")

    attempt_id = task.get("_attempt_id") or task.get("current_attempt_id")
    attempts = None
    if pool is not None and attempt_id:
        from hevi.tasks.attempt_repository import AttemptRepository

        attempts = AttemptRepository(pool)

    for index in range(completed, total):
        if crash_after is not None and index >= int(crash_after):
            raise RuntimeError(f"injected crash at shot {index}")
        shot_path = output_dir / f"shot_{index:03d}.bin"
        shot_path.write_bytes(f"{task_id}:{index}\n".encode())
        shots.append({"index": index, "path": str(shot_path), "kind": "shot"})
        if attempts is not None:
            await attempts.checkpoint(
                attempt_id=uuid.UUID(str(attempt_id)),
                task_id=uuid.UUID(task_id),
                stage=f"shot:{index}",
                progress_pct=100.0 * (index + 1) / total,
                completed_shots=index + 1,
                total_shots=total,
                state={"shots": shots, "stage": f"shot:{index}"},
            )
        completed = index + 1

    final_path = output_dir / "final.mp4"
    payload = b"FTW1" + b"".join(Path(item["path"]).read_bytes() for item in shots)
    final_path.write_bytes(payload)
    manifest = ArtifactManifest(
        production_id=str(config.get("production_id") or ""),
        revision_id=(str(config["revision_id"]) if config.get("revision_id") else None),
        attempt_id=str(attempt_id or task_id),
        tenant_id=str(task.get("user_id") or "anonymous"),
        artifacts=[
            Artifact.from_path(
                final_path,
                kind="video",
                media_type="video/mp4",
                primary=True,
                logical_role="final",
            ),
            *[
                Artifact.from_path(
                    item["path"],
                    kind="shot",
                    media_type="application/octet-stream",
                    logical_role="raw",
                )
                for item in shots
            ],
        ],
    )
    return {
        "status": "completed",
        "result_video_path": str(final_path),
        "completed_shots": completed,
        "total_shots": total,
        "shots": shots,
        "config_json": {
            **config,
            "artifact_manifest": manifest.model_dump(mode="json"),
            "resumed_from_shot": int((checkpoint or {}).get("completed_shots") or 0),
        },
    }


__all__ = ["execute_checkpoint_render"]
