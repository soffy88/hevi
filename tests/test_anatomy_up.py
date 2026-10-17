"""Anatomy upstream补齐 (ANATOMY_UP) — real, mock-free verification.

The vendored tree, the 3D mode, the verification scripts, the craft rules, the
example regression baselines and the example video are all exercised here.
Every test that needs Chromium uses the same probed headless binary the
renderer uses (CPU / SwiftShader), and every slow test is marked ``slow`` so the
unit run stays quick.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from hevi.capabilities import get
from hevi.capabilities.anatomy_explainer import craft
from hevi.capabilities.anatomy_explainer.chrome import chrome_env, resolve_chrome
from hevi.capabilities.anatomy_explainer.renderer import validate_anatomy_params
from hevi.capabilities.anatomy_explainer.verify import (
    AnatomyVerifyError,
    check_lines,
    check_turn,
    image_stats,
    scripts_dir,
    turning_builder,
)

REPO = Path(__file__).resolve().parents[1]
ANATOMY = REPO / "third_party" / "anatomy"

# Run the scripts with the interpreter that is running this test file: the repo
# venv (``/data/soffy/projects/hevi/.venv``) has pydantic, Pillow and numpy, a
# bare ``~/.venv`` does not.
PYTHON = Path(sys.executable)


# ── the vendored upstream ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "relative",
    [
        "kit/turn.mjs",
        "kit/turn-build.mjs",
        "kit/turn-audit.mjs",
        "kit/iso-kit.mjs",
        "kit/audit.mjs",
        "kit/lathe.mjs",
        "kit/tube.mjs",
        "kit/canvas-painter.mjs",
        "scripts/capture.mjs",
        "scripts/drive.mjs",
        "scripts/lines.mjs",
        "scripts/turn-check.mjs",
        "scripts/line-ends.mjs",
        "scripts/inline-kit.mjs",
        "references/craft.md",
        "references/kit.md",
        "references/motion.md",
        "references/verify.md",
        "references/webgl.md",
        "references/3d.md",
        "examples/dial-indicator/build.mjs",
        "examples/ripple-tank/build.mjs",
        "examples/turning-dial/build.mjs",
    ],
)
def test_vendored_file_present(relative: str):
    path = ANATOMY / relative
    assert path.is_file(), f"vendored file missing: {relative}"
    assert path.stat().st_size > 0


def test_notice_records_the_upstream_commit():
    notice = (ANATOMY / "NOTICE").read_text(encoding="utf-8")
    # The pinned upstream commit the vendored files were taken from.
    assert "e9488296a44211c42701ff71705b7901470ec78f" in notice
    assert "wheresryan22/anatomy" in notice
    assert "MIT" in notice
    # The React part of the upstream kit is deliberately not vendored.
    assert not (ANATOMY / "kit" / "react").exists()
    assert not (ANATOMY / "references" / "react.md").exists()


def test_3d_kit_exports_the_builder_runtime_and_audit():
    turn = (ANATOMY / "kit" / "turn.mjs").read_text(encoding="utf-8")
    build = (ANATOMY / "kit" / "turn-build.mjs").read_text(encoding="utf-8")
    audit = (ANATOMY / "kit" / "turn-audit.mjs").read_text(encoding="utf-8")
    assert "export const TURN" in turn and "TURN_CSS" in turn
    assert "export function turning" in build
    assert 'T.group = (name' in build.replace("T.group", "T.group")  # builder API
    assert "export function orbit" in audit and "export function orbitOrExit" in audit
    # references/3d.md documents the API this renderer drives.
    doc = (ANATOMY / "references" / "3d.md").read_text(encoding="utf-8")
    for token in ("window.__isoTurn", "T.build", "orbit audit", "TURN.mount"):
        assert token in doc


# ── craft rules ──────────────────────────────────────────────────────────────

def test_craft_rules_cover_every_reference_document():
    sources = {rule.source.split(" ")[0] for rule in craft.RULES}
    assert sources == {
        "references/craft.md",
        "references/motion.md",
        "references/verify.md",
        "references/webgl.md",
        "references/3d.md",
    }
    hard = [rule for rule in craft.RULES if rule.enforcement == "hard"]
    assert len(hard) >= 8, hard
    # every rule has a checkable id and a named source document
    for rule in craft.RULES:
        assert rule.id.startswith(("craft.", "motion.", "verify.", "webgl.", "3d.")), rule
        assert (ANATOMY / rule.source.split(" ")[0]).is_file(), rule
        assert rule.text and rule.enforcement in {"hard", "advisory"}


def test_craft_constraints_reject_unbuildable_requests():
    with pytest.raises(ValueError, match="mode"):
        validate_anatomy_params({"object": "windmill", "mode": "4d", "duration": 5.0})
    with pytest.raises(ValueError, match="3d"):
        validate_anatomy_params({"object": "soap_pump", "mode": "3d", "duration": 5.0})
    with pytest.raises(ValueError, match="[verify.capture_and_look]"):
        validate_anatomy_params({"object": "windmill", "mode": "2d", "duration": 1.0})
    ok = validate_anatomy_params({"object": "windmill", "mode": "3d", "duration": 4.0})
    assert ok["mode"] == "3d" and ok["object"] == "windmill"
    assert craft.constraints_for_prompt(mode="3d").count("3d.") >= 3
    assert "3d." not in craft.constraints_for_prompt(mode="2d")


def test_craft_measurement_flags_a_page_that_breaks_the_rules():
    """A page with a typed-in part colour and two engraved labels must fail."""
    page = (
        "<style>--anatomy-paper:#fff</style>"
        '<svg viewBox="0 0 1920 1080"><rect width="1920" height="1080" fill="#ff0000"/>'
        '<rect width="40" height="40" fill="#123456"/>'
        '<text class="iso-face-text">A</text><text class="iso-face-text">B</text>'
        '<g data-lit/><g data-lit/>'
        "</svg>"
    )
    path = Path.cwd() / ".tmp" / "anatomy_up_craft_bad.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    report = craft.measure_figure(path, mode="2d")
    assert report["violations"], report
    with pytest.raises(craft.ConstraintViolation):
        craft.enforce(report)
    ids = " ".join(report["violations"])
    assert "craft.theme_tokens" in ids and "craft.no_text_in_drawing" in ids and "craft.one_lit_part" in ids


def test_craft_measurement_accepts_a_token_only_page():
    page = (
        "<style>--anatomy-paper:#fbfbfa;--anatomy-top:#fff</style>"
        '<svg viewBox="0 0 1920 1080"><rect width="1920" height="1080" fill="#dbeafe"/>'
        '<path class="iso-line" d="M0 0 1 1" stroke="var(--anatomy-hi)"/></svg>'
    )
    path = Path.cwd() / ".tmp" / "anatomy_up_craft_ok.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    report = craft.measure_figure(path, mode="3d")
    assert report["violations"] == [], report["violations"]
    craft.enforce(report)  # must not raise


# ── the toolchain ────────────────────────────────────────────────────────────

def test_headless_chromium_is_resolvable():
    binary = resolve_chrome()
    assert binary.exists() and Path(binary).is_file()
    out = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0
    env = chrome_env()
    assert env["CHROME_PATH"] == str(binary)
    # the socket-safe TMPDIR override keeps Chrome's DevTools path short
    assert len(env["TMPDIR"]) <= 52 or env["TMPDIR"] == "/tmp"
    assert scripts_dir().joinpath("turn-check.mjs").is_file()
    assert turning_builder().is_file()


def test_the_floating_line_checker_catches_a_planted_line():
    """lines.mjs must fail on a line whose end touches nothing (real failure)."""
    page = ANATOMY / "examples" / "turning-dial" / "turning-dial-light.html"
    assert page.is_file()
    broken = Path.cwd() / ".tmp" / "anatomy_up_planted_line.html"
    broken.parent.mkdir(parents=True, exist_ok=True)
    html = page.read_text(encoding="utf-8")
    planted = '<path class="iso-line" data-tone="faint" d="M 12 12 L 240 210" style="stroke-width:2"/>'
    assert "</svg>" in html
    broken.write_text(html.replace("</svg>", planted + "</svg>", 1), encoding="utf-8")
    with pytest.raises(AnatomyVerifyError) as exc:
        check_lines(broken)
    assert "floating" in str(exc.value).lower() or " 0 of " not in str(exc.value)


# ── the 3D mode ──────────────────────────────────────────────────────────────

@pytest.mark.slow
def test_the_3d_figure_passes_the_vendored_checks():
    """turn-check --order/--lines and --fidelity on the Hevi 3D builder."""
    builder = turning_builder()
    out_dir = Path.cwd() / ".tmp" / "anatomy_up_turncheck"
    out_dir.mkdir(parents=True, exist_ok=True)
    page = out_dir / "turn-windmill.html"
    build = subprocess.run(
        ["node", str(builder), "--verify", "--out", str(page), "--aspect", "16:9", "--theme", "light"],
        capture_output=True,
        text=True,
        env=chrome_env(),
        timeout=900,
    )
    assert build.returncode == 0, build.stderr[-3000:]
    assert page.is_file()

    turn = check_turn(page, order=True, out_dir=out_dir / "turn-check")
    joined = " ".join(turn["report"])
    assert "turn check passed" in joined
    assert "0 with a live pair drawn out of order" in joined
    assert "24 angles · 0 floating ends" in joined
    assert "fails as it should" in joined  # the planted control really fails

    from hevi.capabilities.anatomy_explainer.verify import check_fidelity

    fidelity = check_fidelity(builder, angles="7,97,187")
    assert any("fidelity passed" in row for row in fidelity["report"])
    stats = image_stats(out_dir / "keyframe.png") if (out_dir / "keyframe.png").exists() else None
    assert stats is None or stats["ink_ratio"] > 0.05


@pytest.mark.slow
def test_3d_mode_renders_a_turning_mp4(tmp_path: Path):
    cap = get("anatomy_explainer")
    out_dir = tmp_path / "out_3d"
    result = cap.render(
        {"object": "windmill", "mode": "3d"},
        out_dir,
        duration=4.0,
        aspect="16:9",
        seed=42,
    )
    mp4 = Path(result.mp4)
    assert mp4.exists()
    assert result.qa["mode"] == "3d"
    assert result.qa["probe"]["duration_s"] >= 3.95
    assert result.qa["probe"]["codec"] == "h264"
    assert result.qa["passed"] is True
    assert result.sha256 == __import__("hashlib").sha256(mp4.read_bytes()).hexdigest()

    checks = result.qa["verify"]
    for key in ("build", "kit_fidelity", "turn_check", "capture", "frames", "video", "kids_gate"):
        assert key in checks, sorted(checks)
    assert checks["frames"]["count"] == 120
    # the frames were seeked: the first and mid stills are both real ink
    assert checks["still_0"]["ink_ratio"] > 0.05 and checks["still_mid"]["ink_ratio"] > 0.05

    verify_report = json.loads(Path(result.qa["verify_report"]).read_text(encoding="utf-8"))
    assert verify_report["passed"] is True
    craft_report = json.loads(Path(result.qa["craft_report"]).read_text(encoding="utf-8"))
    assert craft_report["violations"] == []

    # the turn really turned: a frame 30 degrees on differs from the first one
    # (the rotor has four blades, so a 90 degree step would look the same).
    frames = sorted((out_dir / "frames").glob("*.png"))
    assert len(frames) == 120
    import numpy as np
    from PIL import Image

    a = np.asarray(Image.open(frames[0]).convert("RGB"), dtype="int16")
    thirty_degrees = np.asarray(Image.open(frames[10]).convert("RGB"), dtype="int16")
    symmetric = np.asarray(Image.open(frames[90]).convert("RGB"), dtype="int16")
    changed = float((np.abs(a - thirty_degrees).max(2) > 8).mean())
    restored = float((np.abs(a - symmetric).max(2) > 8).mean())
    assert changed > 0.01, changed
    # a full turn is 72 degrees per second of a 4-second loop, so frame 90 is the
    # same pose as frame 0 plus one 90-degree symmetry step: nearly identical.
    assert restored < changed, (changed, restored)


# ── the example regression baselines ─────────────────────────────────────────

@pytest.mark.slow
def test_examples_are_byte_stable(tmp_path: Path):
    res = subprocess.run(
        [str(PYTHON), str(REPO / "scripts" / "anatomy_up_examples.py")],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env={**__import__("os").environ, "PYTHONPATH": str(REPO), "JWT_SECRET": "test-only", "TMPDIR": str(tmp_path)},
        timeout=3600,
    )
    assert res.returncode == 0, res.stdout[-4000:] + res.stderr[-4000:]
    manifest = json.loads((REPO / "audit" / "anatomy_up" / "baselines" / "examples.json").read_text())
    assert set(manifest) == {"dial-indicator", "ripple-tank", "turning-dial"}
    for entry in manifest.values():
        assert len(entry["page_sha256"]) == 64


@pytest.mark.slow
def test_example_video_from_drive_is_at_least_ten_seconds(tmp_path: Path):
    res = subprocess.run(
        [
            str(PYTHON),
            str(REPO / "scripts" / "anatomy_up_example_video.py"),
            "--fps",
            "8",
            "--frames",
            "88",
            "--seconds",
            "10.0",
            "--example",
            "turning-dial",
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env={**__import__("os").environ, "PYTHONPATH": str(REPO), "JWT_SECRET": "test-only", "TMPDIR": str(tmp_path)},
        timeout=3600,
    )
    assert res.returncode == 0, res.stdout[-4000:] + res.stderr[-4000:]
    summary = json.loads((REPO / "audit" / "anatomy_up" / "example_video.json").read_text())
    assert summary["video"]["duration_s"] >= 10.0
    assert summary["frames"] == 88
    assert summary["largest_frame_change"] > 0.002
    assert (REPO / "audit" / "anatomy_up" / "video" / "turning-dial-drive.mp4").exists()
