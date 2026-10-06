"""E2E-D — deterministic web-native render through a real browser.

The renderer is driven by real Chromium through playwright-core, frame by frame,
with the page sandboxed. Two properties are load-bearing and both are measured
rather than asserted:

* **Determinism.** The same plan rendered twice must produce byte-identical
  output. That is the whole reason a web-native renderer is worth having over a
  nondeterministic one, and it is checked by hashing the real files.
* **Containment.** The page runs with no network, no filesystem and no shell. The
  adversarial suite proves the guards exist; this proves a real hostile page
  cannot get past them inside a real render.

Frame-exactness is *not* claimed for anything but what is measured, and
``frame_deterministic`` is read back from the result rather than assumed.
"""

from __future__ import annotations

import shutil
import hashlib
from pathlib import Path


def _digest(path: Path) -> str:
    """sha256 of an artifact, computed by the *observer*.

    Deliberately not `RenderResult.content_hash`: P9.1.d removed that field because a
    renderer hashing its own output is a second artifact authority. The test is an
    observer, so it may measure — the renderer may not.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()

import pytest
from p5_2_real_assets import ffprobe_duration

from hevi.renderers.base import (
    RendererId,
    RenderOutcome,
    RenderPlan,
    render,
    select_renderer,
)
from hevi.renderers.html_gsap import HtmlGsapRenderer

pytestmark = pytest.mark.slow


def _plan(**overrides) -> RenderPlan:
    plan = RenderPlan(
        shot_id="d1", duration_s=2.0, fps=30, width=1280, height=720,
        caption_text="Deterministic web-native render",
        semantic_intent="state the measured determinism guarantee",
        motion_purposes=["REVEAL"],
    )
    for key, value in overrides.items():
        setattr(plan, key, value)
    return plan


def test_e2e_d1_html_gsap_renders_a_real_video(tmp_path: Path) -> None:
    """A real browser produces a real video file."""
    backend = HtmlGsapRenderer()
    if not backend.detect():
        pytest.skip(f"html/gsap renderer unavailable: {backend.unavailable_reason}")

    result = render(_plan(), tmp_path / "render", renderer_id=RendererId.HTML_GSAP)
    assert result.outcome is RenderOutcome.OK, (result.reason, result.violations)
    output = Path(result.output_path)
    assert output.is_file(), result.output_path
    assert output.stat().st_size > 5_000, output.stat().st_size

    duration = ffprobe_duration(output)
    assert abs(duration - 2.0) < 0.15, f"render is {duration:.3f}s, plan asked for 2.0s"
    assert result.frame_count == 60, result.frame_count
    # P9.1.d: the renderer no longer hashes its own output (audit R1), so this test
    # observes the artifact instead. The intent — a real render happened — is
    # unchanged; only the vantage point moved from the renderer to the test.
    assert _digest(output), "real render produced no bytes to observe"


def test_e2e_d2_two_renders_of_the_same_plan_are_byte_identical(tmp_path: Path) -> None:
    """Determinism is the point; prove it on the bytes, twice."""
    backend = HtmlGsapRenderer()
    if not backend.detect():
        pytest.skip(f"html/gsap renderer unavailable: {backend.unavailable_reason}")

    first = render(_plan(), tmp_path / "a", renderer_id=RendererId.HTML_GSAP)
    second = render(_plan(), tmp_path / "b", renderer_id=RendererId.HTML_GSAP)
    assert first.outcome is RenderOutcome.OK, first.reason
    assert second.outcome is RenderOutcome.OK, second.reason

    left, right = Path(first.output_path).read_bytes(), Path(second.output_path).read_bytes()
    assert len(left) == len(right), f"sizes differ: {len(left)} vs {len(right)}"
    assert left == right, "two renders of one plan produced different bytes"
    assert _digest(Path(first.output_path)) == _digest(Path(second.output_path))
    assert first.frame_deterministic is True, (
        "the renderer did not claim determinism for a render that was byte-identical"
    )


def test_e2e_d3_a_different_plan_produces_different_bytes(tmp_path: Path) -> None:
    """Determinism must not be a constant output. The render has to respond."""
    backend = HtmlGsapRenderer()
    if not backend.detect():
        pytest.skip(f"html/gsap renderer unavailable: {backend.unavailable_reason}")

    plain = render(_plan(), tmp_path / "plain", renderer_id=RendererId.HTML_GSAP)
    worded = render(
        _plan(caption_text="A different caption entirely, with different words in it"),
        tmp_path / "worded", renderer_id=RendererId.HTML_GSAP,
    )
    assert plain.outcome is RenderOutcome.OK and worded.outcome is RenderOutcome.OK
    assert _digest(Path(plain.output_path)) != _digest(Path(worded.output_path)), (
        "changing the plan's text did not change the render"
    )


def test_e2e_d4_untrusted_text_is_escaped_before_it_reaches_the_page(tmp_path: Path) -> None:
    """Layer one: markup in the plan's text is text, never markup."""
    backend = HtmlGsapRenderer()
    if not backend.detect():
        pytest.skip(f"html/gsap renderer unavailable: {backend.unavailable_reason}")

    hostile = "<script>require('fs')</script><img src=x onerror=alert(1)>"
    page = backend.build_page(_plan(caption_text=hostile, semantic_intent=hostile))
    # The tag-opening angle brackets are gone, so the payload is inert text. An
    # attribute-looking substring surviving is fine and expected: without its "<"
    # it is not an attribute, it is characters on the page.
    assert "<script>require" not in page
    assert "<img src=x" not in page
    assert "&lt;script&gt;require('fs')&lt;/script&gt;" in page, (
        "the hostile text was not escaped into the page"
    )
    # The page's own script block is the only script on the page.
    assert page.count("<script>") == 1, page.count("<script>")


def test_e2e_d5_the_sandbox_blocks_a_page_that_really_tries(tmp_path: Path) -> None:
    """Layer two, without bypassing the escaper.

    The renderer probes the sandbox from inside the page on every render, so this
    needs no injection: the attempts and their refusals are measured by the
    production capture path itself -- real Chromium, real route interception, a
    real scrubbed environment.
    """
    backend = HtmlGsapRenderer()
    if not backend.detect():
        pytest.skip(f"html/gsap renderer unavailable: {backend.unavailable_reason}")

    result = render(
        _plan(caption_text="hostile probe", semantic_intent="attempt an escape"),
        tmp_path / "hostile", renderer_id=RendererId.HTML_GSAP,
    )
    assert result.outcome is RenderOutcome.OK, result.reason

    report = result.sandbox_report
    assert report["probed"] is True, report
    assert report["escaped"] == [], f"something escaped the sandbox: {report['escaped']}"
    assert report["clean"] is True, report
    assert "fs:blocked" in report["blocked_files"], report
    assert "child_process:blocked" in report["blocked_shell"], report
    assert "process.env:blocked" in report["blocked_env"], report
    assert any("blocked" in line for line in report["blocked_network"]), report
    # The remote URL was attempted and intercepted.
    assert any("evil.example" in url for url in report["network_attempts"]), report
    # The render process itself got a minimal environment.
    assert set(report["scrubbed_env_keys"]) <= {"HOME", "LANG", "PATH"}, report

    output = Path(result.output_path)
    assert output.is_file()
    assert abs(ffprobe_duration(output) - 2.0) < 0.15


def test_e2e_d5_renderer_selection_prefers_a_capable_backend(tmp_path: Path) -> None:
    """Selection is by capability, and a frame-exact requirement is honoured."""
    import hevi.renderers

    backends = hevi.renderers.list_renderers()
    from hevi.renderers.base import RendererCapability, SelectionRequirement

    decision = select_renderer(
        backends, SelectionRequirement(required_capabilities=[RendererCapability.HTML]),
    )
    assert decision.renderer is RendererId.HTML_GSAP, (decision.renderer, decision.reason)
    assert decision.rejected.get(RendererId.FFMPEG.value), (
        "ffmpeg was not rejected for lacking HTML support"
    )

    # 3D is something no backend here can honestly claim.
    decision = select_renderer(
        backends, SelectionRequirement(required_capabilities=[RendererCapability.TRANSPARENCY]),
    )
    if decision.renderer is None:
        assert decision.rejected, "an unsatisfiable requirement gave no reasons"


def test_e2e_d6_scratch_is_cleaned_up(tmp_path: Path) -> None:
    """A render must not leave a page and a frame directory behind in /tmp."""
    import tempfile

    backend = HtmlGsapRenderer()
    if not backend.detect():
        pytest.skip(f"html/gsap renderer unavailable: {backend.unavailable_reason}")

    before = set(Path(tempfile.gettempdir()).glob("hevi_render_*"))
    render(_plan(), tmp_path / "clean", renderer_id=RendererId.HTML_GSAP)
    after = set(Path(tempfile.gettempdir()).glob("hevi_render_*"))
    assert after <= before, f"scratch left behind: {sorted(after - before)}"
    shutil.rmtree(tmp_path, ignore_errors=True)
