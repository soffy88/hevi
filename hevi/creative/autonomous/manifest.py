"""production_manifest.json —— S1 唯一的绿地。

它是整个 autonomous production 的 **durable projection**,不是第二套状态机:
- 状态从 mission/artifact 投影而来,自己不推进状态;
- 可随时从 mission 重建(纯函数 + 内容哈希);
- 不含 provider 凭据、不含模型内部参数。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "autonomous-production-manifest/1"
SECRET_KEYS = ("api_key", "apikey", "token", "secret", "password", "credential",
               "auth", "bearer")


@dataclass(frozen=True)
class StageProjection:
    node_id: str
    kind: str
    status: str
    attempts: int = 0
    artifact_ids: tuple[str, ...] = ()
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "kind": self.kind, "status": self.status,
                "attempts": self.attempts, "artifact_ids": list(self.artifact_ids),
                "error": self.error}


@dataclass(frozen=True)
class ProductionManifest:
    production_id: str
    request: str
    director_plan: dict[str, Any]
    stages: tuple[StageProjection, ...] = ()
    assets: tuple[dict[str, Any], ...] = ()
    voice: dict[str, Any] = field(default_factory=dict)
    music: dict[str, Any] = field(default_factory=dict)
    subtitle: dict[str, Any] = field(default_factory=dict)
    edit: dict[str, Any] = field(default_factory=dict)
    render: dict[str, Any] = field(default_factory=dict)
    qc: dict[str, Any] = field(default_factory=dict)
    verdict: dict[str, Any] = field(default_factory=dict)
    repairs: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    status: str = "PLANNED"
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "production_id": self.production_id, "request": self.request,
            "director_plan": self.director_plan,
            "stages": [s.to_dict() for s in self.stages],
            "assets": list(self.assets), "voice": self.voice, "music": self.music,
            "subtitle": self.subtitle, "edit": self.edit, "render": self.render,
            "qc": self.qc, "verdict": self.verdict, "repairs": list(self.repairs),
            "provenance": self.provenance, "status": self.status,
        }

    def content_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2,
                                   sort_keys=True) + "\n", encoding="utf-8")
        return path


def assert_no_secrets(payload: Any, *, trail: str = "manifest") -> None:
    """spec §39:production receipt/manifest 不得持久化凭据。

    `*_ref`(如 auth_ref=env:VOICE_KEY)是**引用**不是凭据,允许;其余疑似键一律拒绝。
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            lowered = str(key).lower()
            if (not lowered.endswith("_ref") and value
                    and any(bad in lowered for bad in SECRET_KEYS)):
                raise ValueError(f"SECRET_IN_MANIFEST:{trail}.{key}")
            assert_no_secrets(value, trail=f"{trail}.{key}")
    elif isinstance(payload, (list, tuple)):
        for index, item in enumerate(payload):
            assert_no_secrets(item, trail=f"{trail}[{index}]")


def build_from_mission(mission: Any, *, production_id: str, request: str,
                       director_plan: dict[str, Any],
                       extra: dict[str, Any] | None = None) -> ProductionManifest:
    """从 p3 ProductionMission 投影。不推进状态,只读。"""
    plan = getattr(mission, "plan", None)
    stages = [
        StageProjection(node.node_id, node.kind, node.status, node.attempts,
                        tuple(node.artifact_ids), node.error)
        for node in (plan.nodes if plan is not None else [])
    ]
    artifacts = [
        {"artifact_id": aid, "type": record.type, "status": record.status,
         "hash": record.hash, "producer": record.producer}
        for aid, record in sorted(getattr(mission, "artifacts", {}).items())
    ]
    payload = {
        "production_id": production_id, "request": request,
        "director_plan": director_plan, "stages": tuple(stages),
        "assets": tuple(artifacts),
        "provenance": {"mission_id": getattr(mission, "mission_id", ""),
                       "mission_revision": getattr(mission, "revision", 1),
                       "schema_owner": "hevi/creative/autonomous/manifest.py"},
        "status": getattr(mission, "status", "CREATED"),
    }
    payload.update(extra or {})
    manifest = ProductionManifest(**payload)  # type: ignore[arg-type]
    assert_no_secrets(manifest.to_dict())
    return manifest


__all__ = [
    "SCHEMA_VERSION",
    "ProductionManifest",
    "StageProjection",
    "assert_no_secrets",
    "build_from_mission",
]