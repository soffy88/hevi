"""HEVI VideoAgent 事务：证据索引、语义检索与受约束执行。

这是对 VideoAgent VideoRAG/Storyboard/Graph Router 的 3O 内化，不引入上游
依赖。索引使用 SQLite + 注入/内置轻量 embedding；ASR、VLM 和高级 embedding
由调用方通过输入或 provider 边界注入。
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import math
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.montage.oprim.video_agent import (
    EvidenceQuery,
    EvidenceRef,
    VideoAgentPlan,
    build_storyboard_queries,
    compute_video_plan_fingerprint,
)
from hevi.montage.oskill.video_agent import (
    build_video_agent_plan,
    rank_evidence_candidates,
    reflect_video_agent_plan,
)
from hevi.production.artifacts import Artifact, ArtifactManifest


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        raw = value.model_dump()
        return dict(raw) if isinstance(raw, dict) else {}
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


@dataclass
class VideoEvidenceConfig:
    """视频证据索引配置。"""

    segment_length_s: float = 10.0
    max_segments: int = 10_000
    license: str = "unknown"
    whisper_fallback: bool = False
    embedder: Callable[[str], list[float]] | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_sha256 TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    duration_s REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    source_sha256 TEXT NOT NULL,
    source_path TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    transcript TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    keyframe_paths_json TEXT NOT NULL DEFAULT '[]',
    embedding_json TEXT NOT NULL DEFAULT '[]',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    license TEXT NOT NULL DEFAULT 'unknown',
    UNIQUE(source_sha256, segment_id)
);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_sha256);
CREATE INDEX IF NOT EXISTS idx_evidence_time ON evidence(source_sha256, start_s, end_s);
"""


async def _notify(on_step: Callable[[dict[str, Any]], Any] | None, event: dict[str, Any]) -> None:
    if on_step is None:
        return
    result = on_step(event)
    if inspect.isawaitable(result):
        await result


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duration(path: Path) -> float:
    try:
        from hevi.production.delivery_gate import probe_video

        return max(0.0, float(probe_video(path).duration_s))
    except Exception:
        return 0.0


def _sidecar_segments(source: Path, input_data: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = input_data.get("segments")
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, dict)]

    transcript = input_data.get("transcript")
    if isinstance(transcript, list):
        return [dict(item) if isinstance(item, dict) else {"text": str(item)} for item in transcript]
    if isinstance(transcript, str) and transcript.strip():
        duration = _number(input_data.get("duration_s"))
        return [{"start_s": 0.0, "end_s": max(duration, 1.0), "transcript": transcript.strip()}]

    transcript_path = str(input_data.get("transcript_path") or "").strip()
    candidates = [Path(transcript_path)] if transcript_path else []
    candidates.extend(source.with_suffix(ext) for ext in (".srt", ".vtt"))
    for path in candidates:
        if not path.is_file():
            continue
        try:
            from hevi.ingest.video_transcript import read_subtitle_file

            return [
                {"start_s": item.start, "end_s": item.end, "transcript": item.text}
                for item in read_subtitle_file(path)
            ]
        except Exception:
            continue
    return []


def _normalize_segments(
    source: Path,
    duration_s: float,
    input_data: Mapping[str, Any],
    cfg: VideoEvidenceConfig,
) -> list[dict[str, Any]]:
    raw_segments = _sidecar_segments(source, input_data)
    if not raw_segments:
        if duration_s <= 0:
            return []
        count = min(cfg.max_segments, max(1, math.ceil(duration_s / cfg.segment_length_s)))
        return [
            {
                "segment_id": f"segment-{index:05d}",
                "start_s": round(index * cfg.segment_length_s, 3),
                "end_s": round(min(duration_s, (index + 1) * cfg.segment_length_s), 3),
                "transcript": "",
                "caption": "",
            }
            for index in range(count)
            if index * cfg.segment_length_s < duration_s
        ]

    segments: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_segments[: cfg.max_segments]):
        start = _number(raw.get("start_s", raw.get("start", 0.0)))
        end = _number(raw.get("end_s", raw.get("end", start + cfg.segment_length_s)))
        if end <= start:
            continue
        segments.append(
            {
                "segment_id": str(raw.get("segment_id") or f"segment-{index:05d}"),
                "start_s": start,
                "end_s": end,
                "transcript": str(raw.get("transcript") or raw.get("text") or "").strip(),
                "caption": str(raw.get("caption") or raw.get("visual_caption") or "").strip(),
                "keyframe_paths": [str(item) for item in raw.get("keyframe_paths", [])],
                "provenance": dict(raw.get("provenance") or {}),
                "license": str(raw.get("license") or cfg.license),
            }
        )
    return segments


def _number(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _index_manifest_path(output_dir: Path) -> Path:
    return output_dir / "video_evidence_index.json"


def _index_db_path(output_dir: Path, input_data: Mapping[str, Any]) -> Path:
    explicit = str(input_data.get("index_path") or "").strip()
    return Path(explicit) if explicit else output_dir / "video_evidence.sqlite3"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _read_refs(db_path: Path) -> list[EvidenceRef]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT evidence_id, source_path, source_sha256, segment_id,
                   start_s, end_s, transcript, caption, keyframe_paths_json,
                   embedding_json, provenance_json, license
            FROM evidence ORDER BY source_path, start_s, evidence_id
            """
        ).fetchall()
    return [
        EvidenceRef(
            evidence_id=row["evidence_id"],
            source_path=row["source_path"],
            source_sha256=row["source_sha256"],
            segment_id=row["segment_id"],
            start_s=float(row["start_s"]),
            end_s=float(row["end_s"]),
            transcript=row["transcript"],
            caption=row["caption"],
            keyframe_paths=json.loads(row["keyframe_paths_json"] or "[]"),
            provenance=json.loads(row["provenance_json"] or "{}"),
            license=row["license"],
            embedding=[float(item) for item in json.loads(row["embedding_json"] or "[]")],
        )
        for row in rows
    ]


def _artifact_manifest(paths: list[Path]) -> dict[str, Any]:
    manifest = ArtifactManifest(
        artifacts=[
            Artifact.from_path(
                path,
                kind="evidence_index",
                media_type="application/json" if path.suffix == ".json" else "application/x-sqlite3",
                primary=index == 0,
                logical_role="video_evidence_index",
            )
            for index, path in enumerate(paths)
        ]
    )
    return manifest.model_dump(mode="json")


async def video_evidence_index(
    config: VideoEvidenceConfig | Mapping[str, Any] | None,
    input_data: Mapping[str, Any] | Any,
    output_dir: str | Path,
    *,
    on_step: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """把本地视频建立为可追溯的 segment evidence index。"""

    data = _mapping(input_data)
    cfg_data = _mapping(config)
    cfg = VideoEvidenceConfig(
        segment_length_s=max(0.5, float(cfg_data.get("segment_length_s") or data.get("segment_length_s") or 10.0)),
        max_segments=max(1, int(cfg_data.get("max_segments") or 10_000)),
        license=str(cfg_data.get("license") or data.get("license") or "unknown"),
        whisper_fallback=bool(cfg_data.get("whisper_fallback", data.get("whisper_fallback", False))),
        embedder=cfg_data.get("embedder") if callable(cfg_data.get("embedder")) else None,
    )
    out = Path(output_dir)
    report_path = out / "video_evidence_report.json"
    source_path = Path(str(data.get("source_path") or data.get("media_path") or "")).expanduser()
    trail: list[dict[str, Any]] = []
    try:
        if not source_path.is_file():
            raise FileNotFoundError(f"source video not found: {source_path}")
        source_hash = _hash_file(source_path)
        duration_s = _duration(source_path)
        segments = _normalize_segments(source_path, duration_s, {**data, "duration_s": duration_s}, cfg)
        if not segments:
            raise ValueError("video duration unavailable; provide timestamped segments")
        from hevi.memory.store import TfIdfEmbedder

        embedder = cfg.embedder or TfIdfEmbedder().embed
        db_path = _index_db_path(out, data)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR REPLACE INTO sources(source_sha256, source_path, duration_s, created_at, metadata_json) VALUES (?, ?, ?, ?, ?)",
                (
                    source_hash,
                    str(source_path),
                    duration_s,
                    datetime.now(UTC).isoformat(),
                    json.dumps(
                        data.get("metadata") if isinstance(data.get("metadata"), dict) else {},
                        ensure_ascii=False,
                    ),
                ),
            )
            for index, segment in enumerate(segments):
                transcript = str(segment.get("transcript") or "")
                caption = str(segment.get("caption") or "")
                text = f"{transcript} {caption}".strip()
                segment_id = str(segment["segment_id"])
                evidence_id = hashlib.sha256(f"{source_hash}:{segment_id}".encode()).hexdigest()[:24]
                conn.execute(
                    """
                    INSERT OR REPLACE INTO evidence(
                        evidence_id, source_sha256, source_path, segment_id,
                        start_s, end_s, transcript, caption, keyframe_paths_json,
                        embedding_json, provenance_json, license
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence_id,
                        source_hash,
                        str(source_path),
                        segment_id,
                        float(segment["start_s"]),
                        float(segment["end_s"]),
                        transcript,
                        caption,
                        json.dumps(segment.get("keyframe_paths") or [], ensure_ascii=False),
                        json.dumps(embedder(text), ensure_ascii=False),
                        json.dumps(
                            {
                                "indexed_at": datetime.now(UTC).isoformat(),
                                "source": "hevi.video_evidence_index",
                                **dict(segment.get("provenance") or {}),
                            },
                            ensure_ascii=False,
                        ),
                        str(segment.get("license") or cfg.license),
                    ),
                )
                if index % 50 == 0:
                    await _notify(on_step, {"stage": "evidence_index", "completed": index, "total": len(segments)})
            conn.commit()
        refs = _read_refs(db_path)
        semantic_ready = any((ref.transcript or ref.caption).strip() for ref in refs)
        manifest_path = _index_manifest_path(out)
        manifest = {
            "schema_version": 1,
            "source_path": str(source_path),
            "source_sha256": source_hash,
            "duration_s": duration_s,
            "segment_length_s": cfg.segment_length_s,
            "segment_count": len(refs),
            "semantic_ready": semantic_ready,
            "embedding": "injected" if cfg.embedder else "tfidf-256",
            "license": cfg.license,
            "db_path": str(db_path),
        }
        _write_json(manifest_path, manifest)
        trail.append({"stage": "index", "event": "completed", "segment_count": len(refs), "semantic_ready": semantic_ready})
        report = {
            "status": "completed" if semantic_ready else "planned",
            "findings": manifest,
            "index_path": str(db_path),
            "manifest_path": str(manifest_path),
            "artifact_manifest": _artifact_manifest([manifest_path, db_path]),
            "fingerprint": source_hash[:24],
            "decision_trail": trail,
            "report_path": str(report_path),
            "cost_usd": 0.0,
            "error": None,
        }
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        report = {
            "status": "failed",
            "findings": {},
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "decision_trail": trail,
            "report_path": str(report_path),
            "cost_usd": 0.0,
        }
    _write_json(report_path, report)
    return report


async def video_evidence_search(
    config: Mapping[str, Any] | None,
    input_data: Mapping[str, Any] | Any,
    output_dir: str | Path,
    *,
    on_step: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """检索本地证据，返回 EvidenceRef 而不是路径字符串。"""

    del config
    data = _mapping(input_data)
    out = Path(output_dir)
    report_path = out / "video_evidence_search_report.json"
    trail: list[dict[str, Any]] = []
    try:
        index_path = Path(str(data.get("index_path") or ""))
        if not index_path.is_file():
            raise FileNotFoundError(f"evidence index not found: {index_path}")
        candidates = _read_refs(index_path)
        if not any((item.transcript or item.caption).strip() for item in candidates):
            raise ValueError("evidence index has no transcript or visual caption; semantic search is unavailable")
        raw_queries = data.get("queries") or data.get("scenes") or []
        if isinstance(raw_queries, str):
            raw_queries = [raw_queries]
        queries = [
            item if isinstance(item, EvidenceQuery) else EvidenceQuery.model_validate(item)
            for item in (raw_queries or [])
        ]
        if not queries:
            queries = build_storyboard_queries([str(data.get("query") or "")])
        if not queries:
            raise ValueError("at least one evidence query is required")
        selected: list[EvidenceRef] = []
        used: set[str] = set()
        per_query: list[dict[str, Any]] = []
        for query in queries:
            ranked = rank_evidence_candidates(candidates, query, used_segment_ids=used)
            if not ranked:
                ranked = rank_evidence_candidates(candidates, query)
            chosen = ranked[: query.top_k]
            selected.extend(chosen)
            used.update(item.segment_id for item in chosen)
            per_query.append(
                {
                    "query_id": query.query_id,
                    "query": query.text,
                    "matches": [item.model_dump(mode="json") for item in chosen],
                }
            )
            await _notify(on_step, {"stage": "evidence_search", "query_id": query.query_id, "matches": len(chosen)})
        selected = list({item.evidence_id: item for item in selected}.values())
        trail.append({"stage": "search", "event": "completed", "query_count": len(queries), "match_count": len(selected)})
        report = {
            "status": "completed" if selected else "failed",
            "findings": {"query_count": len(queries), "match_count": len(selected)},
            "evidence_refs": [item.model_dump(mode="json") for item in selected],
            "per_query": per_query,
            "decision_trail": trail,
            "report_path": str(report_path),
            "cost_usd": 0.0,
            "error": None if selected else {"type": "NoEvidence", "message": "no matching evidence"},
        }
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        report = {
            "status": "blocked" if isinstance(exc, (FileNotFoundError, ValueError)) else "failed",
            "findings": {},
            "evidence_refs": [],
            "decision_trail": trail,
            "report_path": str(report_path),
            "cost_usd": 0.0,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    _write_json(report_path, report)
    return report


async def video_script_from_transcript(
    config: Mapping[str, Any] | None,
    input_data: Mapping[str, Any] | Any,
    output_dir: str | Path,
    *,
    on_step: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """把带时间戳/纯文本转写转换为时间线可用脚本行。"""

    del config, output_dir, on_step
    data = _mapping(input_data)
    transcript = data.get("transcript")
    if isinstance(transcript, list):
        rows = transcript
    else:
        rows = []
        for line in str(transcript or "").splitlines():
            text = line.strip()
            if text:
                rows.append({"text": text})
    script_lines: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if isinstance(row, dict):
            text = str(row.get("text") or row.get("transcript") or "").strip()
            start = _number(row.get("start_s", row.get("start", 0.0)))
            end = _number(row.get("end_s", row.get("end", 0.0)))
        else:
            text = str(row).strip()
            start = end = 0.0
        if not text:
            continue
        duration = max(2.5, end - start) if end > start else max(2.5, min(8.0, len(text) / 8.0))
        script_lines.append({"text": text, "duration_s": round(duration, 3), "scene": index})
    if not script_lines:
        return {"status": "blocked", "reason": "transcript is empty; provide captions or an ASR provider", "script_lines": []}
    return {"status": "ok", "script_lines": script_lines, "source": "transcript"}


async def _default_executor(tool_id: str, arguments: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    """把语义端口翻译为 HEVI Studio 工具的实际参数。"""

    if tool_id == "timeline.export":
        timeline = arguments.pop("timeline", None)
        if isinstance(timeline, dict):
            arguments["timeline_id"] = timeline.get("timeline_id")
        arguments.setdefault("output_path", str(output_dir / "final.mp4"))
    from hevi.studio.tools import invoke_tool

    result = await invoke_tool(tool_id, arguments)
    return {"status": result.status, **result.payload, "reason": result.reason}


async def video_agent_transaction(
    config: Mapping[str, Any] | Any,
    input_data: Mapping[str, Any] | Any,
    output_dir: str | Path,
    *,
    on_step: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """VideoAgent 的 HEVI 业务事务：规划、反思、可选执行和报告。"""

    cfg = _mapping(config)
    data = _mapping(input_data)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / "video_agent_report.json"
    trail: list[dict[str, Any]] = []
    try:
        available = set(data.get("available_tools") or cfg.get("available_tools") or []) or None
        plan = await build_video_agent_plan(
            str(data.get("requirement") or data.get("prompt") or data.get("topic") or ""),
            input_data=data,
            source_path=str(data.get("source_path") or data.get("media_path") or ""),
            available_tools=available,
            caller=data.get("caller") or cfg.get("caller"),
        )
        plan_path = out / "video_agent_plan.json"
        plan_fingerprint = compute_video_plan_fingerprint(plan)
        reflection = reflect_video_agent_plan(plan, available_tools=available)
        _write_json(plan_path, plan.model_dump(mode="json"))
        trail.append({"stage": "plan", "event": "completed", "fingerprint": plan_fingerprint})
        trail.append({"stage": "reflection", "event": "completed", "passed": reflection["passed"]})

        if plan.feasibility == "Infeasible" or not reflection["passed"]:
            report = {
                "status": "failed",
                "findings": plan.model_dump(mode="json"),
                "reflection": reflection,
                "error": {"type": "InfeasiblePlan", "message": "; ".join(plan.warnings)},
                "fingerprint": plan_fingerprint,
                "decision_trail": trail,
                "report_path": str(report_path),
                "cost_usd": 0.0,
            }
        elif plan.feasibility == "NeedsInput":
            report = {
                "status": "blocked",
                "findings": plan.model_dump(mode="json"),
                "reflection": reflection,
                "error": {"type": "NeedsInput", "message": "; ".join(plan.intent.missing_inputs)},
                "fingerprint": plan_fingerprint,
                "decision_trail": trail,
                "report_path": str(report_path),
                "cost_usd": 0.0,
            }
        elif not bool(cfg.get("execute", data.get("execute", False))):
            report = {
                "status": "planned",
                "findings": plan.model_dump(mode="json"),
                "reflection": reflection,
                "plan_path": str(plan_path),
                "fingerprint": plan_fingerprint,
                "decision_trail": trail,
                "report_path": str(report_path),
                "cost_usd": 0.0,
            }
        else:
            executor = data.get("executor") or cfg.get("executor")
            context: dict[str, Any] = {}
            edge_map: dict[tuple[str, str], list[tuple[str, str]]] = {}
            for edge in plan.edges:
                edge_map.setdefault((edge.target_node, edge.target_port), []).append((edge.source_node, edge.source_port))
            for node in _topological_nodes(plan):
                arguments: dict[str, Any] = {}
                for port in node.inputs:
                    values = edge_map.get((node.node_id, port.name), [])
                    if values:
                        source_node, source_port = values[0]
                        arguments[port.name] = context.get(f"{source_node}.{source_port}")
                    elif port.name in node.requirements:
                        arguments[port.name] = node.requirements[port.name]
                    elif port.name == "source":
                        arguments[port.name] = str(data.get("source_path") or data.get("media_path") or "")
                    elif port.name == "index_path":
                        arguments[port.name] = str(data.get("evidence_index_path") or "")
                    elif port.required:
                        raise ValueError(f"missing execution input: {node.node_id}.{port.name}")
                if node.tool_id == "video.evidence.index":
                    arguments["source_path"] = arguments.get("source")
                if node.tool_id == "watch.video" and data.get("transcript"):
                    arguments["transcript"] = str(data["transcript"])
                    arguments["duration_s"] = float(data.get("duration_s") or 0.0)
                if node.tool_id == "watch.video":
                    arguments["whisper_fallback"] = bool(
                        cfg.get("whisper_fallback", data.get("whisper_fallback", False))
                    )
                    if data.get("language"):
                        arguments["language"] = str(data["language"])
                if node.tool_id == "video.evidence.search":
                    arguments["queries"] = arguments.get("queries") or [item.model_dump(mode="json") for item in plan.evidence_queries]
                if node.tool_id == "video.script.from_transcript":
                    arguments["transcript"] = arguments.get("transcript") or context.get("watch.transcript") or data.get("transcript", "")
                if node.tool_id == "timeline.export":
                    arguments.setdefault("output_path", str(out / "final.mp4"))
                if node.tool_id == "video.qa":
                    qa_caller = data.get("qa_caller") or cfg.get("qa_caller")
                    if qa_caller is not None:
                        arguments["caller"] = qa_caller
                if node.tool_id == "video.evidence.index":
                    result = await video_evidence_index(
                        cfg,
                        {
                            **data,
                            **arguments,
                            "transcript": context.get("watch.transcript") or data.get("transcript", ""),
                        },
                        out,
                        on_step=on_step,
                    )
                elif node.tool_id == "video.evidence.search":
                    result = await video_evidence_search(cfg, {**data, **arguments}, out, on_step=on_step)
                elif node.tool_id == "video.script.from_transcript":
                    result = await video_script_from_transcript(cfg, arguments, out, on_step=on_step)
                else:
                    raw_result = executor(node.tool_id, arguments) if callable(executor) else _default_executor(node.tool_id, arguments, out)
                    result = await raw_result if inspect.isawaitable(raw_result) else raw_result
                if not isinstance(result, dict):
                    raise RuntimeError(f"{node.node_id}: execution returned a non-object result")
                node_status = result.get("status")
                if node_status in {"failed", "blocked"}:
                    status = "blocked" if node_status == "blocked" else "failed"
                    message = result.get("reason") or result.get("error") or f"execution {status}: {node.node_id}"
                    report = {
                        "status": status,
                        "plan_id": plan.plan_id,
                        "node_id": node.node_id,
                        "error": message,
                        "trail": trail,
                        "artifacts": [],
                    }
                    report_path = out / "video_agent_report.json"
                    _write_json(report_path, report)
                    return {
                        "status": status,
                        "plan": plan.model_dump(mode="json"),
                        "report": report,
                        "report_path": str(report_path),
                        "artifacts": [],
                        "trail": trail,
                    }
                for port in node.outputs:
                    value = result.get(port.name)
                    if value is not None:
                        context[f"{node.node_id}.{port.name}"] = value
                trail.append({"stage": node.node_id, "event": "completed", "tool_id": node.tool_id})
            output_path = Path(str(context.get("export.video_path") or out / "final.mp4"))
            if not output_path.is_file() or output_path.stat().st_size <= 0:
                raise FileNotFoundError(f"execution produced no local video artifact: {output_path}")
            manifest = ArtifactManifest.for_video(output_path)
            report = {
                "status": "completed",
                "findings": {"context": context},
                "artifact_manifest": manifest.model_dump(mode="json"),
                "fingerprint": plan_fingerprint,
                "decision_trail": trail,
                "report_path": str(report_path),
                "cost_usd": 0.0,
                "error": None,
            }
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        report = {
            "status": "failed",
            "findings": {},
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "decision_trail": trail,
            "report_path": str(report_path),
            "cost_usd": 0.0,
        }
    _write_json(report_path, report)
    return report


def _topological_nodes(plan: VideoAgentPlan) -> list[Any]:
    node_map = {node.node_id: node for node in plan.nodes}
    remaining = {node.node_id for node in plan.nodes}
    ordered: list[Any] = []
    while remaining:
        ready = sorted(node_id for node_id in remaining if all(dep not in remaining for dep in node_map[node_id].depends_on))
        if not ready:
            raise ValueError("video agent plan cannot be topologically ordered")
        for node_id in ready:
            ordered.append(node_map[node_id])
            remaining.remove(node_id)
    return ordered


def compute_video_agent_fingerprint(config: Mapping[str, Any], input_data: Mapping[str, Any]) -> str:
    """暴露给服务层的去重指纹，不带真实身份字段。"""

    excluded = {"user_id", "phone", "email", "name", "caller", "executor", "llm"}
    payload = {
        "config": {key: value for key, value in dict(config).items() if key not in excluded and not callable(value)},
        "input": {key: value for key, value in dict(input_data).items() if key not in excluded and not callable(value)},
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:24]


__all__ = [
    "VideoEvidenceConfig",
    "compute_video_agent_fingerprint",
    "video_agent_transaction",
    "video_evidence_index",
    "video_evidence_search",
    "video_script_from_transcript",
]
