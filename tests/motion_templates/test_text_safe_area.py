"""Real canvas text bounding-box measurement for safe-area and overlap compliance.

This test does not re-implement wrapping logic. It reads the actual bounding box of
every ``fillText`` emitted by a template at sample times across 9:16, 16:9 and 1:1,
then asserts:

  (a) every recorded text box lies inside the template's declared safe area;
  (b) at any sampled instant, text boxes whose opacity > 0.5 do not intersect;
  (c) every text box that belongs to a drawn container stays inside that container.

Templates expose ``window.setRecordText(true)`` (recording is off by default so the
pure ``draw(t)`` output is unchanged). If a template predates that instrumentation a
prototype-level fallback recorder is injected, which is what lets the test fail
loudly against the pre-fix R1 16:9 layout.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = Path(os.environ.get("AMTPL_TEMPLATES_DIR", ROOT / "hevi" / "motion_templates" / "templates"))
SPECS_DIR = ROOT / "hevi" / "motion_templates" / "specs"

TEMPLATE_SPECS = [
    ("morph_ui.html", ["morph_ui_hevi_pipeline.json", "morph_ui_studio_ops.json"]),
    ("timeline_explainer.html", ["timeline_ai_video_evolution.json", "timeline_hevi_milestones.json"]),
    ("kinetic_lyrics.html", ["kinetic_bpm_beat_drop.json", "kinetic_engine_tempo.json"]),
    ("layer_build.html", ["layer_build_pipeline.json", "layer_build_datarun.json"]),
]

ASPECTS = [("9:16", 1080, 1920), ("16:9", 1920, 1080), ("1:1", 1080, 1080)]

# Prototype fallback recorder (used only when a template has no setRecordText).
FALLBACK_INJECT = r"""
(() => {
  const proto = CanvasRenderingContext2D.prototype;
  const orig = proto.fillText;
  window.__probeOn = false;
  window.__probeBoxes = [];
  function tx(c, x, y) {
    const m = c.getTransform();
    return { x: m.a * x + m.c * y + m.e, y: m.b * x + m.d * y + m.f };
  }
  proto.fillText = function (text, x, y, maxW) {
    orig.call(this, text, x, y, maxW);
    if (!window.__probeOn) return;
    const str = String(text == null ? "" : text);
    if (!str.trim()) return;
    const m = this.measureText(str);
    const left = x - m.actualBoundingBoxLeft;
    const right = x + m.actualBoundingBoxRight;
    const top = y - m.actualBoundingBoxAscent;
    const bottom = y + m.actualBoundingBoxDescent;
    const p0 = tx(this, left, top);
    const p1 = tx(this, right, bottom);
    window.__probeBoxes.push({
      x: Math.min(p0.x, p1.x), y: Math.min(p0.y, p1.y),
      w: Math.abs(p1.x - p0.x), h: Math.abs(p1.y - p0.y),
      text: str, alpha: this.globalAlpha, container: null
    });
  };
})();
"""

TOL = 1.5


def _cases():
    out = []
    for template_name, specs in TEMPLATE_SPECS:
        for spec_file in specs:
            for aspect, w, h in ASPECTS:
                out.append((template_name, spec_file, aspect, w, h))
    return out


def _intersection_area(a, b):
    ix = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    iy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    if ix > TOL and iy > TOL:
        return ix * iy
    return 0.0


async def _run_case(template_name, spec_file, w, h):
    template_path = TEMPLATES_DIR / template_name
    with open(SPECS_DIR / spec_file, "r", encoding="utf-8") as f:
        spec_dict = json.load(f)
    duration = float(spec_dict.get("duration", 10.0))

    violations = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
        page = await browser.new_page(viewport={"width": w, "height": h})
        await page.add_init_script(FALLBACK_INJECT)
        await page.goto(f"file://{template_path.resolve()}")
        await page.evaluate(f"window.initTemplate({json.dumps(spec_dict)}, {w}, {h})")

        native = await page.evaluate("() => typeof window.setRecordText === 'function'")
        if native:
            await page.evaluate("window.setRecordText(true)")
        else:
            await page.evaluate("window.__probeOn = true")

        t = 0.0
        while t <= duration + 1e-6:
            if not native:
                await page.evaluate("window.__probeBoxes = []")
            await page.evaluate(f"window.draw({t:.6f})")
            state = await page.evaluate(
                """(native) => {
                    if (native) {
                        return { boxes: window.__textBoxes || [], containers: window.__containers || [], safe: window.__safeArea || null };
                    }
                    return { boxes: window.__probeBoxes || [], containers: [], safe: null };
                }""",
                native,
            )
            boxes = state["boxes"]
            containers = state["containers"]
            safe = state["safe"]
            if not native:
                safe = {"left": 40, "top": 40, "right": w - 40, "bottom": h - 40}

            for b in boxes:
                if safe is not None:
                    if (b["x"] < safe["left"] - TOL or b["y"] < safe["top"] - TOL
                            or b["x"] + b["w"] > safe["right"] + TOL
                            or b["y"] + b["h"] > safe["bottom"] + TOL):
                        violations.append(
                            f"t={t:.2f}s SAFE-AREA '{b['text']}' box=({b['x']:.1f},{b['y']:.1f},{b['w']:.1f},{b['h']:.1f}) "
                            f"safe={safe}"
                        )
                if b.get("container"):
                    c = b["container"]
                    if (b["x"] < c["x"] - TOL or b["y"] < c["y"] - TOL
                            or b["x"] + b["w"] > c["x"] + c["w"] + TOL
                            or b["y"] + b["h"] > c["y"] + c["h"] + TOL):
                        violations.append(
                            f"t={t:.2f}s CONTAINER-OVERFLOW '{b['text']}' box=({b['x']:.1f},{b['y']:.1f},{b['w']:.1f},{b['h']:.1f}) "
                            f"container=({c['x']:.1f},{c['y']:.1f},{c['w']:.1f},{c['h']:.1f})"
                        )

            visible = [b for b in boxes if b["alpha"] > 0.5]
            for i in range(len(visible)):
                for j in range(i + 1, len(visible)):
                    area = _intersection_area(visible[i], visible[j])
                    if area > TOL:
                        violations.append(
                            f"t={t:.2f}s OVERLAP area={area:.1f}px2 '{visible[i]['text']}' <-> '{visible[j]['text']}'"
                        )
            t += 0.5

        await page.close()
        await browser.close()
    return violations


@pytest.mark.parametrize("template_name,spec_file,aspect,w,h", _cases())
def test_text_safe_area_and_no_overlap(template_name, spec_file, aspect, w, h):
    violations = asyncio.run(_run_case(template_name, spec_file, w, h))
    if violations:
        head = violations[:25]
        msg = (
            f"{template_name} / {spec_file} / {aspect}: {len(violations)} layout violation(s)\n"
            + "\n".join(head)
        )
        if len(violations) > len(head):
            msg += f"\n... and {len(violations) - len(head)} more"
        pytest.fail(msg)
