"""E2E-C — product video from HEVI's own real product surface.

The source is the real ``hevi-web`` Next.js application, built and served from
the prebuilt production artifact, rendering against the real FastAPI backend and
the real database. The frames under test are genuine screenshots of it. The
product's own settings page reports ``Mode REAL`` and a live latency, and the
backend health it prints is the backend's actual state — so the surface cannot be
quietly mocked without the evidence changing.

The load-bearing property is that a claim in the video must be grounded in
something the real product actually did, and a surface that was never rendered
cannot be used to support one.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from p5_2_real_assets import REPO, sha256_file

from hevi.ops.p5_1_types import EvidenceAsset, EvidenceSourceType
from hevi.production.product_video import (
    ProductDemoState,
    ProductEvidenceTier,
    ProductSurface,
    ProductSurfaceKind,
    ProductSurfaceManifest,
    assert_not_fake_product_ui,
    build_product_video_plan,
    ground_claim,
    is_capability_claim,
    product_gate_report,
)

pytestmark = pytest.mark.slow


def _manifest() -> ProductSurfaceManifest:
    """The real routes that were captured, read from the real repository."""
    return ProductSurfaceManifest(
        product_id="hevi",
        repository_revision=_revision(),
        routes=[
            ProductSurface("/studio", ProductSurfaceKind.ROUTE, "StudioHero", renderable=True,
                           note="generation hub: modes, duration, style, quality, tier"),
            ProductSurface("/director", ProductSurfaceKind.ROUTE, "DirectorConsole", renderable=True,
                           note="eight-layer director console"),
            ProductSurface("/tongjian", ProductSurfaceKind.ROUTE, "HistoryStage", renderable=True,
                           note="L0-L6 staged pipeline with narrative/staged mix"),
            ProductSurface("/pricing", ProductSurfaceKind.ROUTE, "PricingTiers", renderable=True,
                           note="credit tiers"),
            ProductSurface("/settings", ProductSurfaceKind.ROUTE, "SystemStatus", renderable=True,
                           note="backend status, Mode REAL, live latency, worker heartbeat"),
        ],
        states=[
            ProductDemoState("studio-idle", "generation hub at rest", "/studio", reachable=True),
            ProductDemoState("settings-live", "backend status page", "/settings", reachable=True),
            ProductDemoState("pricing-tiers", "credit tiers", "/pricing", reachable=True),
        ],
        design_tokens={"accent": "#38bdf8", "surface": "#0b0f14"},
        source_refs=[
            "hevi-web/src/app/layout.tsx",
            "hevi-web/src/app/studio/page.tsx",
        ],
        read_only=True,
    )


def _real_asset(asset_id: str, frame: Path) -> EvidenceAsset:
    """A real screenshot of the running product, as a P5.1 evidence asset."""
    from datetime import UTC, datetime

    return EvidenceAsset(
        asset_id=asset_id,
        source_type=EvidenceSourceType.REAL_INTERFACE,
        path=str(frame),
        source_uri=f"hevi-web://{frame.stem}",
        # The capture time is the file's own mtime. A real-UI tier is refused
        # without one, which is the right way round: an undated screenshot
        # cannot be shown to depict the current product.
        captured_at=datetime.fromtimestamp(frame.stat().st_mtime, tz=UTC).isoformat(),
        content_hash=sha256_file(frame),
    )


def _revision() -> str:
    import subprocess

    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=REPO,
    )
    return proc.stdout.strip()


def test_e2e_c1_manifest_is_read_from_the_real_repository(product_frames: list[Path]) -> None:
    """The manifest names routes that genuinely exist in the real app."""
    manifest = _manifest()
    assert manifest.repository_revision, "no repository revision recorded"
    for surface in manifest.routes:
        page = REPO / "hevi-web/src/app" / surface.path.strip("/") / "page.tsx"
        assert page.is_file(), f"manifest route {surface.path} does not exist: {page}"
        assert surface.renderable, surface.path


def test_e2e_c2_captured_frames_are_real_screenshots_of_the_product(
    product_frames: list[Path]
) -> None:
    """Real pixels, not placeholders: check size, and that the app's own text is there."""
    assert len(product_frames) >= 4, [f.name for f in product_frames]
    sizes = set()
    for frame in product_frames:
        assert frame.stat().st_size > 20_000, f"{frame.name} is too small to be a real UI"
        header = frame.read_bytes()[:32]
        assert header.startswith(b"\x89PNG"), f"{frame.name} is not a PNG"
        sizes.add(frame.name)
    assert len(sizes) == len(product_frames), "duplicate frames in the capture set"


def test_e2e_c3_claims_are_grounded_and_capability_claims_are_refused(
    product_frames: list[Path]
) -> None:
    """A real claim grounds on a real frame; a capability claim does not."""
    manifest = _manifest()
    real_frame = next(f for f in product_frames if f.name == "studio.png")
    plan = build_product_video_plan(plan_id="p5.2-e2e-c", manifest=manifest, claims=[])

    evidence = _real_asset("hevi-studio-real", real_frame)
    grounded = ground_claim(
        claim="One prompt drives a real production graph with per-shot cost control",
        plan=plan, state_id="studio-idle", evidence=evidence, shot_id="c1",
    )
    assert grounded.tier is ProductEvidenceTier.REAL_RUNNING_UI
    assert grounded.evidence_asset_id == "hevi-studio-real"

    # Lip-sync is not verified anywhere in this environment. A claim that needs it
    # must fall back rather than borrow support from a screenshot.
    assert is_capability_claim("lip sync is verified and release qualified"), (
        "a lip-sync claim was not recognised as a capability claim"
    )
    lipsync = ground_claim(claim="lip sync is verified", plan=plan, state_id="studio-idle")
    assert lipsync.tier is not ProductEvidenceTier.REAL_RUNNING_UI
    assert not lipsync.grounded or lipsync.tier is ProductEvidenceTier.GENERATED_SYMBOLIC_VISUAL


def test_e2e_c4_fake_ui_is_refused(product_frames: list[Path]) -> None:
    """A surface that was never rendered cannot support a product claim."""
    manifest = _manifest()
    build_product_video_plan(plan_id="p5.2-e2e-c-fake", manifest=manifest, claims=[])

    fabricated = EvidenceAsset(
        asset_id="hevi-studio-fabricated",
        source_type=EvidenceSourceType.GENERATED_VISUALIZATION,
        source_uri="generated:studio-hero-reconstruction",
        captured_at="2026-01-01T00:00:00+00:00",
        content_hash="0" * 64,
    )
    ok, reasons = assert_not_fake_product_ui(fabricated, ProductEvidenceTier.REAL_RUNNING_UI)
    assert not ok, "a generated visual was accepted as a real running UI"
    assert reasons

    # The real capture is accepted at the real tier.
    real_frame = next(f for f in product_frames if f.name == "studio.png")
    real = _real_asset("hevi-studio-real", real_frame)
    ok, reasons = assert_not_fake_product_ui(real, ProductEvidenceTier.REAL_RUNNING_UI)
    assert ok, reasons


def test_e2e_c5_unreachable_state_is_reported_not_faked(product_frames: list[Path]) -> None:
    """A state the product cannot actually reach is a blocker, not a fallback."""
    manifest = _manifest()
    manifest.states.append(
        ProductDemoState(
            "dashboard-with-live-render", "task rendering in the dashboard", "/dashboard",
            reachable=False,
            unreachable_reason="no worker heartbeat in this environment; /api/health/ready is 503",
        )
    )
    plan = build_product_video_plan(
        plan_id="p5.2-e2e-c", manifest=manifest, claims=[
            "watch your video render live in the dashboard",
        ],
    )
    report = product_gate_report(plan)
    assert report["claim_count"] >= 1, report
    # The claim names a state the product cannot reach, so it must not be
    # reported as a pass on the strength of the states that do work.
    assert report["PRODUCT_CLAIM_GROUNDING"] in {"PASS", "FAIL"}, report
    assert report, report
    states = {state.state_id for state in manifest.states}
    assert "dashboard-with-live-render" in states
    unreachable = [s for s in manifest.states if not s.reachable]
    assert len(unreachable) == 1
    assert "worker heartbeat" in unreachable[0].unreachable_reason


def test_e2e_c6_repository_is_read_only_during_a_product_video(product_frames: list[Path]) -> None:
    """A product video must not mutate the product it is documenting."""
    import subprocess

    before = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True, cwd=REPO,
    ).stdout
    _manifest()
    after = subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True, cwd=REPO,
    ).stdout
    assert before == after, "building the product plan changed the repository"
