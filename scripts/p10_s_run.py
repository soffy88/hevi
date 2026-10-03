"""P10-S 端到端竖切驱动:Idea -> Direction -> Shot -> Audio -> Frame -> Evidence.

全走真实链路(TTS/ffmpeg/现有 ShotPlanner/规则引擎);无 mock,无 LLM。
用法: uv run .venv/bin/python scripts/p10_s_run.py  (或 .venv/bin/python ...)
产物: artifacts/p10_s/<ts>/ (mp4 + json + verdict + explain)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hevi.audio.tts_alignment import synthesize_with_alignment  # noqa: E402
from hevi.cinematic.shot_intelligence.models import BeatCue, ShotIntent  # noqa: E402
from hevi.cinematic.shot_intelligence.selector import ShotSelector  # noqa: E402
from hevi.director.script_identity import (  # noqa: E402
    ScriptUnit,
    assign_unit_ids,
    inherit_unit_ids,
)
from hevi.studio.anchor_resolver import Anchor, resolve_anchor  # noqa: E402
from hevi.verdict.delivery_gate import parse_silence_events  # noqa: E402
from hevi.verdict.silence_probe import ffmpeg_version  # noqa: E402
from hevi.verdict.zoom_measure import estimate_scale_change, load_gray  # noqa: E402

FPS = 30
VOICE = "en-US-AriaNeural"
SPIKE = ROOT / "docs" / "p10" / "p10_s"
TS = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
OUT = ROOT / "artifacts" / "p10_s" / TS
SEG_TAIL_MS = 800
GAP_MS = 600
CUE_SILENCE_MS = 320


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def run(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{proc.stderr[-800:]}")
    return proc


def ffprobe_duration_ms(path: Path) -> int:
    proc = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return round(float(proc.stdout.strip()) * 1000)


def to_wav(src: Path, dst: Path) -> Path:
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-ar", "44100", "-ac", "1", str(dst)])
    return dst


def silence_wav(ms: int, dst: Path) -> Path:
    run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", f"anullsrc=r=44100:cl=mono:d={ms / 1000}",
         "-ar", "44100", "-ac", "1", str(dst)])
    return dst


def concat_wavs(parts: list[Path], dst: Path) -> Path:
    lst = dst.parent / "concat.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-ar", "44100", "-ac", "1", str(dst)])
    return dst


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    def _note(m: str) -> None:
        log.append(m)
        print(m, flush=True)

    note = _note

    # ── S1: spike 对象 pin + 手动审批记录 ──
    pins = {p.name: sha256_file(SPIKE / p.name) for p in
            [Path("thesis.json"), Path("treatment.json"), Path("benchmark.json"),
             Path("signature_shot.json"), Path("cue.json")]}
    treatment = json.loads((SPIKE / "treatment.json").read_text(encoding="utf-8"))
    cue = json.loads((SPIKE / "cue.json").read_text(encoding="utf-8"))
    approval = {"actor": "user", "authorized_by": "chat instruction 2026-10-02 (启动 P10-S 实施)",
                "scope": "spike structure + cue C21", "pinned": pins, "at": TS}
    (OUT / "approval.json").write_text(json.dumps(approval, ensure_ascii=False, indent=2), encoding="utf-8")
    note(f"[S1] pinned 5 objects, approval by user: {next(iter(pins.values()))[:12]}…")

    # ── S2/H1: ScriptUnit → ShotIntent(+creative refs) → 现有 ShotPlanner ──
    units = assign_unit_ids([ScriptUnit("", "scene1", i, line["text"]) for i, line in enumerate(treatment["script"])])
    units = inherit_unit_ids([], [(u.scene_id, u.text, "") for u in units])
    selector = ShotSelector()
    purposes = ["hook", "evidence", "cta"]
    plans = []
    for i, u in enumerate(units):
        intent = ShotIntent(
            line=u.text, scene_intent=f"black-hole scale reveal seg{i + 1}",
            narrative_purpose=purposes[i], subject="black hole", narration_present=True,
            target_duration_s=6.0, beat_map=(BeatCue(time_s=0.0, cue_id="cue:C21",
                                                     creative_cue_ref="ccue:C21"),) if i == 1 else (),
            creative_direction_ref="cd:spike黑洞", decision_refs=("D18",), cue_refs=("cue:C21",),
        )
        result = selector.select(intent)
        plans.append({"unit_id": u.unit_id, "recipe_id": result.selected.id,
                      "confidence": result.confidence, "rationale": result.rationale})
    (OUT / "shot_plans.json").write_text(json.dumps(plans, ensure_ascii=False, indent=2), encoding="utf-8")
    note(f"[H1] PASS: 3 ShotIntents → existing ShotSelector, recipes {[p['recipe_id'] for p in plans]}")

    # ── S3/H2: TTS 对齐 + anchor 解析 ──
    async def _tts() -> list[tuple[Path, object]]:
        out = []
        for u in units:
            path, align = await synthesize_with_alignment(
                text=u.text, voice=VOICE, audio_id=f"tts:{u.unit_id}#r1",
                output_path=OUT / f"{u.unit_id}.mp3")
            out.append((path, align))
        return out

    tts_results = asyncio.run(_tts())
    dialogue_end_ms = {u.unit_id: a.words[-1].end_ms for u, (_, a) in zip(units, tts_results, strict=True)}
    assert all(a.words for _, a in tts_results), "word timing missing"
    # 行内锚点(相对 line2 音频起点);film 偏移在音频装配后叠加(见下)
    line_anchor = resolve_anchor(
        Anchor(cue["at"]["type"], cue["at"]["target"], offset_ms=cue["at"]["offset_ms"]),
        dialogue_end_ms=dialogue_end_ms, fps=FPS,
        alignment_hash="align:tts-r1", timeline_hash="tl:pending")
    note(f"[H2] PASS: dialogue ends {dialogue_end_ms} → line-local anchor {line_anchor.time_ms}ms")

    # ── S4a: 音频时间线(先行) → film 级锚点 → CompliancePlan 编译期冻结(渲染前) ──
    wavs = [to_wav(OUT / f"{u.unit_id}.mp3", OUT / f"{u.unit_id}.wav") for u in units]
    line_ms = [ffprobe_duration_ms(w) for w in wavs]
    tails = [silence_wav(SEG_TAIL_MS, OUT / f"tail{i}.wav") for i in range(3)]
    gap = silence_wav(GAP_MS, OUT / "gap.wav")
    cue_sil = silence_wav(CUE_SILENCE_MS, OUT / "cue_sil.wav")
    seg1 = concat_wavs([wavs[0], tails[0]], OUT / "seg1.wav")
    seg3 = concat_wavs([wavs[2], tails[2]], OUT / "seg3.wav")
    full_audio = concat_wavs([seg1, wavs[1], gap, cue_sil, seg3], OUT / "full.wav")
    d1, d2, d3 = (ffprobe_duration_ms(seg1),
                  line_ms[1] + GAP_MS + CUE_SILENCE_MS,
                  ffprobe_duration_ms(seg3))
    total_ms = d1 + d2 + d3
    # film 锚点 = seg1 偏移 + 行内锚点(Timeline resolve 的组合语义)
    anchor_ms = d1 + line_anchor.time_ms
    resolved_frame = round(anchor_ms * FPS / 1000)
    line2end_film_ms = d1 + dialogue_end_ms["scene1.line002"]
    note(f"[H2] film anchor {anchor_ms}ms frame {resolved_frame} "
         f"(seg offset {d1} + line-local {line_anchor.time_ms})")

    anchor_ms_plan = anchor_ms
    plan = {"checks": [
        {"id": "CHK-DUR", "severity": "must", "class": "D", "expected": {"duration_lte_ms": 30000}},
        {"id": "CHK-SIL", "severity": "must", "class": "D",
         "expected": {"silence_window_ms": [anchor_ms_plan, anchor_ms_plan + CUE_SILENCE_MS]}},
        {"id": "CHK-ZOOM", "severity": "must", "class": "M",
         "expected": {"scale_change_ratio": [0.65, 0.75]}, "detector": "ncc_scale@spike"},
        {"id": "CHK-SYNC", "severity": "must", "class": "D",
         "expected": {"anchor_ms": anchor_ms_plan, "dialogue_end_ms": line2end_film_ms,
                      "tolerance_ms": 250}},
        {"id": "CHK-MUS", "severity": "may", "class": "H",
         "expected": "NOT_EVALUABLE: spike 无配乐 (cue.json 已声明)"}],
        "compliance_plan_hash": "", "ffmpeg_version": ffmpeg_version()}
    plan["compliance_plan_hash"] = sha256_json({k: v for k, v in plan.items() if k != "compliance_plan_hash"})
    (OUT / "compliance_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    note(f"[PLAN] frozen {plan['compliance_plan_hash'][:12]}… (after audio, before render)")

    # ── S4b: 视频渲染 ──
    note(f"[AUDIO] seg ms: {d1}/{d2}/{d3} total {total_ms}ms; anchor expect {anchor_ms_plan}ms")

    still = OUT / "still.png"
    # 非周期纹理(随机几何 + 噪声):周期图案(testsrc2)会在多尺度 NCC 下产生混叠误峰
    import numpy as _np
    from PIL import Image as _Image
    from PIL import ImageDraw as _Draw
    rng = _np.random.default_rng(42)
    base = _np.tile(_np.linspace(20, 200, 720, dtype=float)[:, None], (1, 1280))
    canvas = _Image.fromarray(_np.stack([base] * 3, axis=-1).astype("uint8"), "RGB")
    draw = _Draw.Draw(canvas)
    for _ in range(220):
        x, y = rng.integers(0, 1280), rng.integers(0, 720)
        r = int(rng.integers(8, 90))
        fill = tuple(int(v) for v in rng.integers(0, 255, size=3))
        (draw.ellipse if rng.random() < 0.5 else draw.rectangle)([x - r, y - r, x + r, y + r], fill=fill)
    canvas.save(still)
    Regime = OUT
    v1 = Regime / "v1.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(still),
         "-t", f"{d1 / 1000}", "-r", "30", "-pix_fmt", "yuv420p", str(v1)])
    frames2 = round(d2 / 1000 * FPS)
    v2 = Regime / "v2.mp4"
    # 单 still 输入(无 -loop):zoompan 每输入帧产出 d 帧,on 计数精确,1.5→1.0 即 pull_back
    run(["ffmpeg", "-v", "error", "-y", "-i", str(still),
         "-vf", f"zoompan=z='1.5-0.5*on/{frames2}':d={frames2}:s=1280x720:fps=30",
         "-frames:v", str(frames2), "-pix_fmt", "yuv420p", str(v2)])
    v3 = Regime / "v3.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(still),
         "-t", f"{d3 / 1000}", "-r", "30", "-pix_fmt", "yuv420p", str(v3)])
    vcat = Regime / "vcat.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(v1), "-i", str(v2), "-i", str(v3),
         "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", str(vcat)])
    mp4 = OUT / "spike.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-i", str(vcat), "-i", str(full_audio),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(mp4)])
    mp4_hash = sha256_file(mp4)
    dur_ms = ffprobe_duration_ms(mp4)
    note(f"[RENDER] spike.mp4 {dur_ms}ms sha256 {mp4_hash[:12]}…")

    # ── S5/H3: 观测 + verdict(规则引擎,无 LLM) + explain ──
    proc = run(["ffmpeg", "-v", "info", "-i", str(mp4), "-af", "silencedetect=noise=-60dB:d=0.32",
                "-f", "null", "-"])
    sil_events = parse_silence_events(proc.stderr, floor_s=0.32)
    anchor_expect = anchor_ms_plan
    in_window = [s for s, d in sil_events
                 if s <= anchor_expect / 1000 <= s + d and (s + d) * 1000 >= anchor_expect + CUE_SILENCE_MS - 80]
    # 对白结束事件 = 覆盖 anchor-500 的静音段起点(对齐词级结束,非音频 duration)
    sync_ev = min(sil_events, key=lambda e: abs(e[0] * 1000 - line2end_film_ms)) if sil_events else None

    for name, t in (("z0", d1 / 1000 + 0.1), ("z1", (d1 + d2) / 1000 - 0.1)):
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(mp4),
             "-frames:v", "1", str(OUT / f"{name}.png")])
    scale, conf = estimate_scale_change(load_gray(str(OUT / "z0.png")), load_gray(str(OUT / "z1.png")))

    obs = {"duration_ms": dur_ms, "artifact_hash": mp4_hash,
           "silence_events_s": sil_events, "scale_change_ratio": scale, "scale_confidence": conf,
           "anchor_expected_ms": anchor_expect, "anchor_resolved_ms": anchor_ms}
    (OUT / "observation_set.json").write_text(json.dumps(obs, ensure_ascii=False, indent=2), encoding="utf-8")

    results = []
    results.append({"id": "CHK-DUR", "result": "PASS" if dur_ms <= 30000 else "FAIL",
                    "observed_ms": dur_ms})
    results.append({"id": "CHK-SIL", "result": "PASS" if in_window else "FAIL",
                    "observed_events_s": sil_events})
    if conf < 0.5:
        results.append({"id": "CHK-ZOOM", "result": "INCONCLUSIVE", "observed_scale": scale,
                        "confidence": conf})
    else:
        results.append({"id": "CHK-ZOOM",
                        "result": "PASS" if 0.65 <= scale <= 0.75 else "FAIL",
                        "observed_scale": scale, "confidence": conf})
    sync_ok = sync_ev is not None and abs(sync_ev[0] * 1000 - line2end_film_ms) <= 250
    results.append({"id": "CHK-SYNC", "result": "PASS" if sync_ok else "FAIL",
                    "observed_silence_start_ms": sync_ev[0] * 1000 if sync_ev else None})
    results.append({"id": "CHK-MUS", "result": "NOT_EVALUABLE", "note": "spike 无配乐"})
    must = [r for r in results if r["id"] in ("CHK-DUR", "CHK-SIL", "CHK-ZOOM", "CHK-SYNC")]
    if any(r["result"] == "FAIL" for r in must):
        status = "REVISE"
    elif any(r["result"] in ("INCONCLUSIVE", "NOT_EVALUABLE") for r in must):
        status = "INCONCLUSIVE"
    else:
        status = "PASS"
    verdict = {"artifact_hash": mp4_hash, "compliance_plan_hash": plan["compliance_plan_hash"],
               "status": status, "checks": results}
    (OUT / "direction_verdict.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")

    explain = (
        f"为什么揭示点这里拉远?\n"
        f"-> 观测: silence {sil_events} / scale {scale:.3f}(conf {conf:.2f}) / 时长 {dur_ms}ms\n"
        f"-> ShotPlan {plans[1]['recipe_id']} <- ShotIntent(seg2, cue_refs=['cue:C21'])\n"
        f"-> Cue cue:C21 [revelation] action A1 camera pull_back (anchor {anchor_ms_plan}ms frame {resolved_frame})\n"
        f"-> Beat B7 [scale revelation] -> Decision D18 -> Treatment T1 -> Thesis: 先理解尺度,再生敬畏\n"
        f"-> Benchmark principle BP4 (Interstellar Gargantua reveal, principle_only)\n"
        f"-> verdict: {status} (plan {plan['compliance_plan_hash'][:12]}…, artifact {mp4_hash[:12]}…)"
    )
    (OUT / "explain.txt").write_text(explain, encoding="utf-8")
    note(f"[H3] verdict={status}\n{explain}")
    note(f"[DONE] artifacts in {OUT}")
    if status != "PASS":
        raise SystemExit(f"P10-S verdict {status}, see {OUT}")


if __name__ == "__main__":
    main()
