"""Hevi capability registry per CAPABILITY_CONTRACT.md.
Provides register, get, list, resolve for capabilities including qa.kids_gate.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.renderers.ffmpeg import resolve_ffmpeg_bin
from hevi.operations.bridge import OperationBridge, SqliteOperationsStore, OperationError
from hevi.operations.registry import list_operations as _list_operations
from hevi.quality.kids_gate import kids_gate_workflow


@dataclass
class CapabilityResult:
    mp4: str | None = None
    png: str | None = None
    wav: str | None = None
    duration_s: float = 0.0
    sha256: str = ""
    qa: dict[str, Any] = field(default_factory=dict)


@dataclass
class OperationCapabilityResult(CapabilityResult):
    operations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Capability:
    name: str
    kind: str
    aspects: list[str]
    params_schema: dict[str, Any]
    cpu_cost_hint: float
    render: Any
    description: str = ""
    line: str = ""

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise ValueError(f"params must be a dict, got {type(params)}")
        allowed = self.params_schema.get("properties", {})
        if not self.params_schema.get("additionalProperties", True):
            extra = set(params.keys()) - set(allowed.keys())
            if extra:
                raise ValueError(f"unsupported parameters: {sorted(extra)}")
        for k, v in params.items():
            spec = allowed.get(k, {})
            expected_type = spec.get("type")
            if expected_type == "string" and not isinstance(v, str):
                raise ValueError(f"parameter {k} must be string, got {type(v)}")
            if expected_type == "integer" and not isinstance(v, int):
                raise ValueError(f"parameter {k} must be integer, got {type(v)}")
            if "enum" in spec and v not in spec["enum"]:
                raise ValueError(f"parameter {k} must be one of {spec['enum']}, got {v!r}")
        return params


_REGISTRY: dict[str, Capability] = {}


def register(cap: Capability) -> Capability:
    _REGISTRY[cap.name] = cap
    return cap


def get(name: str) -> Capability:
    cap = _REGISTRY.get(name)
    if not cap:
        raise RuntimeError(f"Unknown capability: {name}")
    return cap


def resolve(name: str) -> Capability:
    return get(name)


def list_capabilities(kind: str | None = None, aspect: str | None = None) -> list[Capability]:
    out = []
    for c in _REGISTRY.values():
        if kind and c.kind != kind:
            continue
        if aspect and aspect not in c.aspects:
            continue
        out.append(c)
    return out


list = list_capabilities


# ── agent.ops_bridge ──────────────────────────────────────────────────────────


def _render_ops_bridge(
    params: dict[str, Any],
    out_dir: Path | str,
    *,
    duration: float = 2.0,
    aspect: str = "9:16",
    seed: int = 1,
) -> OperationCapabilityResult:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    ops = [d.to_dict() for d in _list_operations()]
    report_file = out_path / "ops_bridge_inventory.json"
    report_file.write_text(json.dumps(ops, ensure_ascii=False, indent=2), encoding="utf-8")

    op_receipt: dict[str, Any] = {}
    op_name = params.get("operation")
    if op_name:
        import asyncio
        db_path = params.get("db_path", "data/agent_ops.db")
        bridge = SqliteOperationsStore(db_path)
        br = OperationBridge(bridge, read_only=(params.get("mode") == "read-only"))
        try:
            op_params = params.get("params", {})
            op_id = params.get("opId")
            if params.get("expectedRevision") is not None:
                op_params.setdefault("expectedRevision", params["expectedRevision"])
            op_receipt = asyncio.run(br.execute(op_name, op_params, op_id=op_id))
        except OperationError as exc:
            op_receipt = {"operation": op_name, "error": exc.code, "detail": exc.detail}
        except Exception as exc:
            op_receipt = {"operation": op_name, "error": "execution_failed", "detail": str(exc)}
        (out_path / "ops_receipt.json").write_text(json.dumps(op_receipt, ensure_ascii=False, indent=2), encoding="utf-8")

    mp4_file: Path | None = None
    sha256_val = ""
    dur = float(duration) if duration > 0 else 2.0

    # 生成 2 秒演示视频产物（lavfi 纯 CPU 合成，遵守无云 API / 零网络）
    res = "320x568" if aspect == "9:16" else "568x320"
    mp4_path = out_path / "ops_bridge_preview.mp4"
    ffmpeg_bin = resolve_ffmpeg_bin()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=indigo:s={res}:d={dur}:rate=24",
        "-f",
        "lavfi",
        "-i",
        f"sine=f=440:r=48000:d={dur}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(mp4_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    sha256_val = hashlib.sha256(mp4_path.read_bytes()).hexdigest()
    mp4_file = mp4_path

    return OperationCapabilityResult(
        mp4=str(mp4_file),
        duration_s=dur,
        sha256=sha256_val,
        operations=ops,
        qa={"count": len(ops), "names": [o["name"] for o in ops], "report_file": str(report_file), "op_receipt": op_receipt},
    )


register(
    Capability(
        name="agent.ops_bridge",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {
                "format": {"type": "string", "enum": ["summary", "preview"]},
            },
            "additionalProperties": False,
        },
        cpu_cost_hint=0.05,
        render=_render_ops_bridge,
        description="Agent 画布操作桥：只读 + 写(CAS/幂等) + 付费 propose 闸",
        line="anime",
    )
)


# ── qa.kids_gate ─────────────────────────────────────────────────────────────


def _render_kids_gate(
    params: dict[str, Any],
    out_dir: Path,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> CapabilityResult:
    video_path = Path(params.get("video_path", ""))
    srt_path = Path(params.get("srt_path")) if params.get("srt_path") else None
    meta_path = Path(params.get("metadata_path")) if params.get("metadata_path") else None

    report = kids_gate_workflow(video_path, srt_path=srt_path, metadata_path=meta_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "kids_gate_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return CapabilityResult(
        mp4=str(video_path) if video_path.exists() else None,
        duration_s=duration,
        qa=report,
    )


register(
    Capability(
        name="qa.kids_gate",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={"type": "object"},
        cpu_cost_hint=0.1,
        render=_render_kids_gate,
        description="幼儿动漫安全与节奏质检闸门",
        line="anime",
    )
)
