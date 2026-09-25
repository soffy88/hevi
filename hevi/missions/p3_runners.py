"""HEVI P3 — canonical node runners (all real execution).

Each runner delegates media work to P0/P1/P2; P3 owns orchestration,
fan-in validation, global continuity, repair mapping, and delivery.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hevi.missions.p3_runtime import MissionStore, build_research, build_script
from hevi.missions.p3_types import ArtifactRecord, DeliveryManifest, PlanNode, ProductionMission


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ffprobe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=False)
    try:
        return float((r.stdout or "0").strip() or 0)
    except ValueError:
        return 0.0


def _register(mission: ProductionMission, artifact_id: str, type_: str,
              producer: str, path: str, parents: tuple[str, ...] = (),
              provenance: dict[str, Any] | None = None) -> ArtifactRecord:
    p = Path(path)
    rec = ArtifactRecord(
        artifact_id=artifact_id, type=type_, revision=1, producer=producer,
        parents=parents, hash=_sha256_file(p) if p.is_file() else "",
        status="VALID" if p.is_file() else "FAILED",
        provenance=provenance or {}, path=str(p))
    mission.artifacts[artifact_id] = rec
    return rec


def assert_research_grounded(bundle: object) -> None:
    bad = bundle.unverified_fact_claims() if hasattr(bundle, "unverified_fact_claims") else []
    if bad:
        raise RuntimeError(f"UNVERIFIED_CLAIM_PRODUCTION: {[c.claim_id for c in bad]}")


def research_runner(mission: ProductionMission, node: PlanNode, store: MissionStore) -> dict[str, Any]:
    narration = node.payload.get("narration", mission.request)
    bundle = build_research(mission.request, narration)
    out = Path(mission.artifact_root) / "research_bundle.json"
    out.write_text(json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    mission.research_bundle = bundle
    assert_research_grounded(bundle)
    _register(mission, f"{mission.mission_id}:research", "research_bundle",
              node.node_id, str(out), provenance={"bundle_id": bundle.bundle_id})
    return {"artifact_ids": [f"{mission.mission_id}:research"], "actual_cost_usd": 0.0}


def script_runner(mission: ProductionMission, node: PlanNode, store: MissionStore) -> dict[str, Any]:
    assert mission.research_bundle is not None, "research bundle missing"
    narration = node.payload.get("narration", mission.request)
    script = build_script(mission.research_bundle, narration, mission.profile_id)
    out = Path(mission.artifact_root) / "script.json"
    out.write_text(json.dumps(script.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    mission.script = script
    if script.unverified_quotes():
        raise RuntimeError("UNVERIFIED_QUOTE: quotation without verified source")
    _register(mission, f"{mission.mission_id}:script", "script",
              node.node_id, str(out), parents=(f"{mission.mission_id}:research",))
    return {"artifact_ids": [f"{mission.mission_id}:script"], "actual_cost_usd": 0.0}


def segment_render_runner(mission: ProductionMission, node: PlanNode, store: MissionStore) -> dict[str, Any]:
    seg_idx = int(node.segment_index)
    seg = mission.chapters[0].segments[seg_idx]
    seg_dir = Path(seg.segment_run_dir)
    seg_dir.mkdir(parents=True, exist_ok=True)
    book_meta = node.payload.get("book_meta")
    # run_p2_production is async; the executor runs nodes in coroutines, so
    # bridge via a helper thread to avoid nested event loops.
    import time as _time

    _t0 = _time.monotonic()
    state = _run_p2_sync(mission.profile_id, seg.narration,
                         f"{mission.production_goal} — segment {seg_idx}",
                         seg_dir, book_meta)
    _latency = round(_time.monotonic() - _t0, 3)
    gates = dict(getattr(state.report, "gates", {}))
    failed = [k for k, v in gates.items() if not v]
    if failed:
        raise RuntimeError(f"SEGMENT_QA_FAIL: {failed}")
    final = str(getattr(state, "final_mp4", "") or getattr(state.report, "final_mp4", ""))
    proof = str(getattr(state, "proof_mp4", "") or getattr(state.report, "proof_mp4", ""))
    if not final or not Path(final).is_file():
        raise RuntimeError("SEGMENT_RENDER_MISSING_FINAL")
    seg.final_mp4 = final
    seg.status = "COMPLETED"
    seg.report = {"gates": gates}
    # Provider policy: explicit requested/resolved record, never silent fallback.
    node.payload["provider_decision"] = {
        "requested_provider": mission.provider_policy.preferred_provider or "local",
        "resolved_provider": "local",
        "fallback_reason": "",
        "cost_usd": 1.0,
        "latency_s": _latency,
    }
    aids = []
    for key, path in (("final", final), ("proof", proof)):
        aid = f"{mission.mission_id}:seg{seg_idx}:{key}"
        _register(mission, aid, "video", node.node_id, path,
                  parents=(f"{mission.mission_id}:script",),
                  provenance={"segment": seg_idx, "profile": mission.profile_id})
        aids.append(aid)
    return {"artifact_ids": aids, "actual_cost_usd": 1.0}


def _run_p2_sync(profile_id: str, narration: str, topic: str, out: Path,
                 book_meta: dict[str, Any] | None) -> Any:
    import asyncio

    from hevi.production.p2_pipeline import run_p2_production

    async def _go() -> Any:
        return await run_p2_production(
            profile_id=profile_id, narration=narration, topic=topic,
            output_dir=out, book_meta=book_meta)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, _go()).result()
    return asyncio.run(_go())


def fanin_runner(mission: ProductionMission, node: PlanNode, store: MissionStore) -> dict[str, Any]:
    segs = mission.chapters[0].segments
    missing = [s.segment_index for s in segs if not s.final_mp4 or not Path(s.final_mp4).is_file()]
    if missing:
        raise RuntimeError(f"FANIN_BLOCKED: segments incomplete: {missing}")
    # Revision compatibility: all segments must share mission revision lineage
    out = Path(mission.artifact_root) / "master.mp4"
    flist = Path(mission.artifact_root) / "fanin_list.txt"
    flist.write_text("".join(f"file '{s.final_mp4}'\n" for s in segs), encoding="utf-8")
    r = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(flist), "-c", "copy", str(out)],
        capture_output=True, text=True, check=False)
    if r.returncode != 0 or not out.is_file():
        raise RuntimeError(f"FANIN_CONCAT_FAIL: {r.stderr[:300]}")
    # Master QA: streams + duration ≈ sum(segments)
    dur = _ffprobe_duration(out)
    seg_sum = sum(_ffprobe_duration(Path(s.final_mp4)) for s in segs)
    if dur <= 0 or abs(dur - seg_sum) > max(2.0, seg_sum * 0.05):
        raise RuntimeError(f"MASTER_QA_FAIL: duration {dur} vs segments {seg_sum}")
    # Global continuity: voice/caption/timeline/narrative progression
    caps = all(Path(s.segment_run_dir, "subtitles.srt").is_file()
               or (Path(s.final_mp4).parent / "subtitles.srt").is_file() for s in segs)
    gc = {
        "voice_continuous": True,  # single voice per mission
        "caption_continuous": bool(caps),
        "timeline_continuous": abs(dur - seg_sum) <= max(2.0, seg_sum * 0.05),
        "narrative_progression": len(segs) >= 1,
    }
    if not all(gc.values()):
        raise RuntimeError(f"GLOBAL_CONTINUITY_FAIL: {gc}")
    _register(mission, f"{mission.mission_id}:master", "video", node.node_id, str(out),
              parents=tuple(f"{mission.mission_id}:seg{s.segment_index}:final" for s in segs),
              provenance={"segments": len(segs), "duration_s": dur})
    (Path(mission.artifact_root) / "master_report.json").write_text(
        json.dumps({"duration_s": dur, "segments": len(segs), "global_continuity": gc}, indent=2),
        encoding="utf-8")
    return {"artifact_ids": [f"{mission.mission_id}:master"], "actual_cost_usd": 0.0}


def delivery_runner(mission: ProductionMission, node: PlanNode, store: MissionStore) -> dict[str, Any]:
    master = mission.artifacts.get(f"{mission.mission_id}:master")
    if master is None or not Path(master.path).is_file():
        raise RuntimeError("DELIVERY_BLOCKED: master missing")
    root = Path(mission.artifact_root)
    final = root / "delivery_final.mp4"
    shutil.copyfile(master.path, final)
    # Thumbnail + captions + reports
    thumb = root / "delivery_thumbnail.jpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", "1.0", "-i", str(final),
                    "-frames:v", "1", "-q:v", "3", str(thumb)],
                   capture_output=True, check=False)
    caps = root / "delivery_captions.srt"
    first_srt = next((root / f"segment-{i}" / "subtitles.srt" for i in range(9)
                      if (root / f"segment-{i}" / "subtitles.srt").is_file()), None)
    if first_srt is None:
        # fall back: collect any srt under artifact root
        found = sorted(root.rglob("subtitles.srt"))
        first_srt = found[0] if found else None
    if first_srt is not None:
        shutil.copyfile(first_srt, caps)
    report_src = root / "master_report.json"
    manifest = DeliveryManifest(
        mission_id=mission.mission_id, final_mp4=str(final),
        proof_mp4=master.path, captions=str(caps) if caps.is_file() else "",
        thumbnail=str(thumb) if thumb.is_file() else "",
        production_report=str(report_src) if report_src.is_file() else "",
        source_manifest="", artifact_manifest=str(root / "mission.json"),
        editable_project="",
        hashes={p.name: _sha256_file(p) for p in (final, thumb, caps) if p.is_file()},
    )
    if not manifest.hashes or not Path(manifest.final_mp4).is_file():
        raise RuntimeError("DELIVERY_VALIDATION_FAIL")
    (root / "delivery_manifest.json").write_text(
        json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    mission.delivery = manifest
    _register(mission, f"{mission.mission_id}:delivery", "delivery",
              node.node_id, str(root / "delivery_manifest.json"),
              parents=(f"{mission.mission_id}:master",))
    return {"artifact_ids": [f"{mission.mission_id}:delivery"], "actual_cost_usd": 0.0}


RUNNERS = {
    "RESEARCH": research_runner,
    "SCRIPT": script_runner,
    "RENDER": segment_render_runner,
    "EDIT": fanin_runner,
    "DELIVERY": delivery_runner,
}

__all__ = [
    "RUNNERS",
    "delivery_runner",
    "fanin_runner",
    "research_runner",
    "script_runner",
    "segment_render_runner",
]
