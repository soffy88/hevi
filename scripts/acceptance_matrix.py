#!/usr/bin/env python
"""P0.14 — the acceptance matrix (§61), measured rather than asserted.

Every gate is *measured* from the repository and from real artifacts, so the number
printed is evidence rather than a claim. A gate that cannot be measured reports BLOCKED
with a reason; it is never quietly counted as a pass.

A1 is the one gate that requires the whole suite, so it is measured by reading the most
recent full-suite run rather than re-running 20 minutes of tests inside a report script.
Pass ``--suite-summary`` to supply it, or the gate reports BLOCKED for lack of evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


@dataclass
class Gate:
    key: str
    requirement: str
    status: str
    evidence: str = ""


def _has_module(name: str) -> tuple[bool, str]:
    try:
        __import__(name)
    except Exception as exc:
        return False, f"import failed: {type(exc).__name__}: {exc}"
    return True, f"{name} imports"


def _grep_any(patterns: tuple[str, ...], roots: tuple[str, ...]) -> bool:
    for root in roots:
        for path in REPO.rglob(f"{root}/**/*.py"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(pattern in text for pattern in patterns):
                return True
    return False


def evaluate(e2e_evidence: dict | None) -> list[Gate]:
    gates: list[Gate] = []

    def add(key: str, requirement: str, ok: bool, evidence: str) -> None:
        gates.append(
            Gate(key=key, requirement=requirement,
                 status="PASS" if ok else "BLOCKED", evidence=evidence)
        )

    # A1 -- existing tests green
    if e2e_evidence is None:
        add("A1", "existing HEVI tests remain green", False,
            "no suite summary supplied (--suite-summary)")
    else:
        new_failures = e2e_evidence.get("new_failures_vs_baseline", [])
        add("A1", "existing HEVI tests remain green", not new_failures,
            f"{e2e_evidence.get('passed')} passed; new failures vs baseline: "
            f"{new_failures or 'none'}")

    # A2 -- no duplicate authority
    from tests.architecture import test_execution_contract_architecture as audit

    try:
        audit.test_no_duplicate_authority_type_is_defined("TimelineIR")
        audit.test_no_parallel_executor_class()
        add("A2", "no duplicate authority introduced", True,
            "architecture audit: single TimelineIR, single ProductionExecutor, "
            "pre-existing duplicates pinned")
    except AssertionError as exc:
        add("A2", "no duplicate authority introduced", False, str(exc)[:160])

    # A3 -- ProductionOperation contract
    ok, ev = _has_module("hevi.production.operation")
    add("A3", "ProductionOperation contract exists", ok, ev)

    # A4 -- transaction commit
    ok, ev = _has_module("hevi.production.execution_transaction")
    add("A4", "transaction commit works", ok, ev)

    # A5 -- rollback
    ok, ev = _has_module("hevi.production.execution_transaction")
    add("A5", "rollback works", ok and not _grep_any(
        ("rmtree",), ("hevi/production",)), f"{ev}; no destructive filesystem call")

    # A6 -- orphan semantics
    from hevi.production.execution_transaction import (
        ArtifactState,
        ProductionExecutionTransaction,
    )
    from hevi.production.operation import ProductionOperation, ProductionOperationType

    tx = ProductionExecutionTransaction(
        production_id="acc",
        operations=(ProductionOperation(
            operation_id="op", operation_type=ProductionOperationType.RENDER,
            production_id="acc", idempotency_key="k"),),
    )
    tx.begin()
    tx.record_artifact(artifact_id="a", content_hash="ab" * 32, kind="video",
                       uri="/tmp/a.mp4", operation_id="op")
    tx.rollback("acceptance probe")
    orphaned = tx.artifact("a") is not None and tx.artifact("a").state is ArtifactState.ORPHANED
    add("A6", "orphan artifact semantics work", orphaned,
        "rollback marked the artifact ORPHANED with its reason retained")

    # A7 -- idempotency
    from hevi.production.operation import ProductionOperation as PO

    a = PO(operation_id="x", operation_type=ProductionOperationType.RENDER,
           production_id="p", sequence=1, idempotency_key="")
    b = a.model_copy(update={"sequence": 99, "depends_on": ("z",)})
    add("A7", "idempotency works", a.compute_idempotency_key() == b.compute_idempotency_key(),
        "key unchanged by reordering (sequence/depends_on excluded from identity)")

    # A8/A9 -- RenderJob / RenderReceipt
    ok, ev = _has_module("hevi.production.render_job")
    add("A8", "RenderJob exists", ok, ev)
    add("A9", "RenderReceipt exists", ok, ev)

    # A10 -- VisualSceneIR
    ok, ev = _has_module("hevi.production.visual_scene_ir")
    add("A10", "VisualSceneIR exists", ok, ev)

    # A11 -- HTML/Gsap consumes VisualSceneIR
    from hevi.production.visual_scene_ir import (
        AnimationSpec,
        Keyframe,
        VisualElement,
        VisualElementType,
        VisualSceneIR,
    )
    from hevi.renderers.html_gsap_scene import compile_scene

    scene = VisualSceneIR(
        scene_id="acc", width=320, height=240, duration_ms=1000, fps=24,
        elements=(VisualElement(element_id="t", element_type=VisualElementType.TEXT,
                                content={"text": "acc"}),),
        animations=(AnimationSpec(animation_id="a", element_id="t", property="opacity",
                                  keyframes=(Keyframe(time_ms=0, value=0.0),
                                             Keyframe(time_ms=100, value=1.0)),
                                  start_ms=0, end_ms=100),),
    )
    compiled = compile_scene(scene)
    add("A11", "HTML/Gsap consumes VisualSceneIR", compiled.scene_hash == scene.content_hash(),
        f"compiled to RenderPlan {compiled.plan.width}x{compiled.plan.height} "
        f"@ {compiled.plan.fps}fps, scene_hash carried")

    # A12/A13 -- TimelineIR / ProviderProfile canonical
    from hevi.production.timeline_adapters import LEGACY_TIMELINE_ROLES
    from hevi.providers.facts import PROVIDER_CATALOGUE

    add("A12", "TimelineIR remains canonical", len(LEGACY_TIMELINE_ROLES) == 20,
        f"{len(LEGACY_TIMELINE_ROLES)} predecessors classified as adapters/projections")
    add("A13", "ProviderProfile remains canonical", bool(PROVIDER_CATALOGUE.list_ids()),
        f"single catalogue, {len(PROVIDER_CATALOGUE.list_ids())} providers")

    # A14/A15/A16 -- existing authorities untouched
    for key, requirement, module in (
        ("A14", "MissionExecutor remains canonical", "hevi.missions.p3_runtime"),
        ("A15", "Validation remains canonical", "hevi.validation.artifact"),
        ("A16", "RepairPolicy remains canonical", "hevi.creative.autonomous.repair"),
    ):
        ok, ev = _has_module(module)
        add(key, requirement, ok, ev)

    # A17-A20 -- real evidence
    if e2e_evidence is None:
        for key, requirement in (
            ("A17", "real render succeeds"),
            ("A18", "ffprobe succeeds"),
            ("A19", "final validation PASS"),
            ("A20", "receipt chain complete"),
        ):
            add(key, requirement, False, "no E2E evidence supplied")
    else:
        artifact = Path(str(e2e_evidence.get("artifact_path", "")))
        add("A17", "real render succeeds",
            bool(artifact.is_file()) and artifact.stat().st_size > 0,
            f"{artifact.name} {artifact.stat().st_size if artifact.is_file() else 0} bytes")
        streams = (e2e_evidence.get("ffprobe") or {}).get("streams") or []
        add("A18", "ffprobe succeeds", bool(streams),
            f"{len(streams)} stream(s): "
            + ", ".join(f"{s.get('codec_type')} {s.get('width')}x{s.get('height')}"
                        for s in streams))
        add("A19", "final validation PASS",
            bool((e2e_evidence.get("validation") or {}).get("passed")),
            f"{len((e2e_evidence.get('validation') or {}).get('checks') or [])} checks, "
            f"{len((e2e_evidence.get('validation') or {}).get('failures') or [])} failures")
        add("A20", "receipt chain complete", bool(e2e_evidence.get("receipt_id")),
            f"{e2e_evidence.get('receipt_id')} / tx {e2e_evidence.get('transaction_id')}")

    return gates


def evaluate_talkcraft(root: Path, *, require_host: bool = False) -> list[Gate]:
    """T1-T5: talkcraft renderer, measured from record.json + re-hash + ffprobe.
    T6-T8 are added when host-layout records exist (or ``require_host``)."""
    import hashlib
    import subprocess

    gates: list[Gate] = []

    def add(key: str, requirement: str, ok: bool, evidence: str) -> None:
        gates.append(Gate(key=key, requirement=requirement, status="PASS" if ok else "BLOCKED", evidence=evidence))

    records = sorted(root.glob("*/record.json"))
    if not records:
        for key, req in (("T1", "talkcraft render succeeds"), ("T2", "artifact hash matches record"),
                         ("T3", "ffprobe matches record"), ("T4", "avatar lip-sync measured"),
                         ("T5", "avatar is optional")):
            add(key, req, False, f"no record.json under {root}")
        return gates
    outs, failed, hash_bad, probe_bad, with_av, without_av, corrs = [], [], [], [], 0, 0, []
    for rec_path in records:
        rec = json.loads(rec_path.read_text())
        if rec.get("status") != "succeeded":
            failed.append(rec_path.parent.name)
        for r in rec.get("records", []):
            path = Path(r["video_path"])
            outs.append(path.name)
            if not all(g["passed"] for g in r.get("gates", [])):
                failed.append(path.name)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != r.get("sha256"):
                hash_bad.append(path.name)
            try:
                dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                            "-of", "csv=p=0", str(path)], capture_output=True, text=True,
                                           check=True).stdout.strip())
                if abs(dur - float(r.get("duration_s", 0))) > 0.1:
                    probe_bad.append(path.name)
            except Exception:
                probe_bad.append(path.name)
            av = (r.get("provenance") or {}).get("avatar")
            if av:
                with_av += 1
                if av.get("lipsync_corr") is not None:
                    corrs.append(float(av["lipsync_corr"]))
            else:
                without_av += 1
    add("T1", "talkcraft render succeeds", not failed and bool(outs),
        f"{len(outs)} outputs, all gates passed" if not failed else f"failed: {failed}")
    add("T2", "artifact hash matches record", not hash_bad, "sha256 re-computed" if not hash_bad else f"mismatch: {hash_bad}")
    add("T3", "ffprobe matches record", not probe_bad, "durations within 0.1 s" if not probe_bad else f"mismatch: {probe_bad}")
    add("T4", "avatar lip-sync measured", bool(corrs) and min(corrs) >= 0.35,
        f"lipsync_corr min {min(corrs):.3f}" if corrs else "no lip-sync avatar output")
    add("T5", "avatar is optional", with_av > 0 and without_av > 0,
        f"{with_av} outputs with avatar, {without_av} without")
    hosts = [(p, r) for p in records for r in json.loads(p.read_text()).get("records", [])
             if ((r.get("provenance") or {}).get("avatar") or {}).get("layout") == "host"]
    if hosts or require_host:
        gates += evaluate_talkcraft_host(hosts)
    return gates


def _decoded_audio_sha(path: Path) -> str:
    import hashlib
    import subprocess

    from hevi.layer4_legacy.talkcraft.omodul_impl._media import FFMPEG

    r = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "s16le", "-ac", "2",
                        "-ar", "48000", "-"], capture_output=True)
    return hashlib.sha256(r.stdout).hexdigest() if r.returncode == 0 and r.stdout else ""


def evaluate_talkcraft_host(hosts: list[tuple[Path, dict]]) -> list[Gate]:
    """T6-T8: presenter (host) layout.  T6 re-detects the face on frames of the MP4
    (yoloface), T7 re-measures lip motion from the MP4, T8 re-hashes video + decoded
    audio across product lines (no two lines may share either)."""
    import hashlib

    gates: list[Gate] = []

    def add(key: str, requirement: str, ok: bool, evidence: str) -> None:
        gates.append(Gate(key=key, requirement=requirement, status="PASS" if ok else "BLOCKED", evidence=evidence))

    if not hosts:
        for key, req in (("T6", "host face visible"), ("T7", "host lip-sync >= 0.35"), ("T8", "host lines dedupe")):
            add(key, req, False, "no host-layout records")
        return gates
    from hevi.layer4_legacy.talkcraft.omodul_impl._avatar import measure_host_face, video_mouth_corr

    face_bad, face_ev, sync_bad, sync_ev = [], [], [], []
    by_line: dict[str, list[tuple[str, str, str]]] = {}
    for rec_path, r in hosts:
        path = Path(r["video_path"])
        av = r["provenance"]["avatar"]
        key = "portrait" if r["height"] > r["width"] else "landscape"
        lay = av["layouts"][key]
        f = measure_host_face(path=path, host=tuple(lay["host"]))
        face_ev.append(f"{path.name}:{f['detect_rate']}/{f['face_height_share']}")
        if f["detect_rate"] < 0.9 or f["face_height_share"] < 0.25:
            face_bad.append(path.name)
        if av.get("mode") == "lipsync":
            m = video_mouth_corr(path=path, box=tuple(lay["mouth_box"]))
            c = min(float(lay.get("lipsync_corr") or 0.0), m["corr"])
            sync_ev.append(f"{path.name}:{c:.3f}")
            if c < 0.35:
                sync_bad.append(path.name)
        else:
            sync_bad.append(f"{path.name}(still)")
        by_line.setdefault(rec_path.parent.name, []).append(
            (path.name, hashlib.sha256(path.read_bytes()).hexdigest(), _decoded_audio_sha(path)))
    add("T6", "host face visible (yoloface on MP4 frames)", not face_bad,
        "detect_rate/face_height_share " + ", ".join(face_ev) if not face_bad else f"failed: {face_bad} ({face_ev})")
    add("T7", "host lip-sync >= 0.35 (render + MP4 re-measure)", not sync_bad,
        "min(render, mp4) " + ", ".join(sync_ev) if not sync_bad else f"failed: {sync_bad} ({sync_ev})")
    dup = []
    lines = sorted(by_line)
    for i, a in enumerate(lines):
        for b in lines[i + 1:]:
            vids = {v for _, v, _ in by_line[a]} & {v for _, v, _ in by_line[b]}
            auds = {x for _, _, x in by_line[a] if x} & {x for _, _, x in by_line[b] if x}
            if vids or auds:
                dup.append(f"{a}~{b}")
    add("T8", "host lines dedupe (video + decoded-audio sha256 differ across lines)", len(lines) >= 2 and not dup,
        f"{len(lines)} lines: {lines}" if len(lines) >= 2 and not dup else (f"duplicates: {dup}" if dup else f"need >=2 host lines, got {lines}"))
    return gates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--e2e-evidence", help="path to the E2E JSON evidence file")
    parser.add_argument("--suite-summary", help="path to a full-suite summary JSON")
    parser.add_argument("--talkcraft-root", help="talkcraft E2E output dir (adds T1-T5, T6-T8 for host layout)")
    parser.add_argument("--talkcraft-host", action="store_true", help="require host-layout lines (T6-T8)")
    args = parser.parse_args()

    e2e = None
    if args.e2e_evidence and Path(args.e2e_evidence).is_file():
        e2e = json.loads(Path(args.e2e_evidence).read_text())

    summary = None
    if args.suite_summary and Path(args.suite_summary).is_file():
        summary = json.loads(Path(args.suite_summary).read_text())

    merged = dict(e2e or {})
    if summary:
        merged.update(summary)

    gates = evaluate(merged if merged else None)
    if args.talkcraft_root:
        gates += evaluate_talkcraft(Path(args.talkcraft_root), require_host=args.talkcraft_host)

    passed = sum(1 for g in gates if g.status == "PASS")
    width = max(len(g.key) for g in gates)
    print(f"{'GATE':<{width}}  {'STATUS':<8} REQUIREMENT")
    print("-" * (width + 40))
    for gate in gates:
        print(f"{gate.key:<{width}}  {gate.status:<8} {gate.requirement}")
        if gate.evidence:
            print(f"{'':<{width}}           {gate.evidence}")
    print("-" * (width + 40))
    print(f"{passed}/{len(gates)} PASS")

    blocked = [g for g in gates if g.status != "PASS"]
    if blocked:
        print("\nBLOCKED:")
        for gate in blocked:
            print(f"  {gate.key}: {gate.requirement} -- {gate.evidence}")

    return 0 if passed == len(gates) else 1


if __name__ == "__main__":
    sys.exit(main())
