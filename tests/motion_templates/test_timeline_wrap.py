"""Timeline template word-boundary wrapping and CJK punctuation prohibition tests.

Asserts:
  (a) No line begins with prohibited Chinese punctuation: ，。、；：！？）》」』”’】
  (b) No line ends with opening Chinese punctuation: （《「『“‘【
  (c) Gold domain vocabulary is never severed across adjacent line seams
      (e.g. 帧间, 动力学, 外部, 管线, 严苛, 零幻觉, 短视频).
"""

import asyncio
import json
from pathlib import Path
import pytest
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "hevi" / "motion_templates" / "templates"
SPECS_DIR = ROOT / "hevi" / "motion_templates" / "specs"

TIMELINE_SPECS = [
    "timeline_ai_video_evolution.json",
    "timeline_hevi_milestones.json",
]

ASPECTS = [
    ("9:16", 1080, 1920),
    ("16:9", 1920, 1080),
    ("1:1", 1080, 1080),
]

BANNED_LINE_START = set("，。、；：！？）》」』”’】")
BANNED_LINE_END = set("（《「『“‘【")

GOLD_WORDS = [
    "帧间",
    "动力学",
    "外部",
    "管线",
    "严苛",
    "零幻觉",
    "短视频",
]


def _check_lines(lines: list[str]) -> list[str]:
    violations = []
    for line in lines:
        for p in BANNED_LINE_START:
            if line.startswith(p):
                violations.append(f"Prohibited leading punctuation '{p}' in line: '{line}'")
        for p in BANNED_LINE_END:
            if line.endswith(p):
                violations.append(f"Prohibited trailing punctuation '{p}' in line: '{line}'")

    for k in range(len(lines) - 1):
        l1, l2 = lines[k], lines[k + 1]
        for w in GOLD_WORDS:
            for split_i in range(1, len(w)):
                prefix = w[:split_i]
                suffix = w[split_i:]
                if l1.endswith(prefix) and l2.startswith(suffix):
                    violations.append(
                        f"Gold word '{w}' severed across seam: '{l1}' <-> '{l2}'"
                    )
    return violations


async def _collect_timeline_lines(spec_name: str, w: int, h: int) -> list[str]:
    template_path = TEMPLATES_DIR / "timeline_explainer.html"
    spec_path = SPECS_DIR / spec_name
    spec_data = json.loads(spec_path.read_text(encoding="utf-8"))

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
        page = await browser.new_page(viewport={"width": w, "height": h})
        await page.goto(f"file://{template_path.resolve()}")
        await page.evaluate(f"window.initTemplate({json.dumps(spec_data)}, {w}, {h})")
        await page.evaluate("window.setRecordText(true)")
        # At t=10.0s, all timeline milestones are fully settled
        await page.evaluate("window.draw(10.0)")
        boxes = await page.evaluate("() => window.__textBoxes")
        await page.close()
        await browser.close()

    return [b["text"] for b in boxes if b.get("text")]


@pytest.mark.parametrize("spec_name", TIMELINE_SPECS)
@pytest.mark.parametrize("aspect,w,h", ASPECTS)
def test_timeline_word_wrap_and_punctuation_rules(spec_name: str, aspect: str, w: int, h: int):
    lines = asyncio.run(_collect_timeline_lines(spec_name, w, h))
    assert lines, f"No text lines collected for {spec_name} at {aspect}"

    violations = _check_lines(lines)
    if violations:
        msg = f"{spec_name} [{aspect}] failed wrapping/punctuation invariants ({len(violations)} violations):\n"
        msg += "\n".join(f"  - {v}" for v in violations)
        pytest.fail(msg)
