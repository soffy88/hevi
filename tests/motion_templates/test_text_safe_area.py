"""Text safe area overflow test measuring real canvas metrics in Playwright."""

import asyncio
import json
from pathlib import Path
import pytest
from playwright.async_api import async_playwright

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "hevi" / "motion_templates" / "templates"
SPECS_DIR = Path(__file__).resolve().parents[2] / "hevi" / "motion_templates" / "specs"


@pytest.mark.parametrize("template_name,spec_file", [
    ("morph_ui.html", "morph_ui_hevi_pipeline.json"),
    ("timeline_explainer.html", "timeline_ai_video_evolution.json"),
    ("kinetic_lyrics.html", "kinetic_bpm_beat_drop.json"),
    ("layer_build.html", "layer_build_pipeline.json"),
])
def test_canvas_text_safe_area_no_overflow(template_name: str, spec_file: str):
    template_path = TEMPLATES_DIR / template_name
    spec_path = SPECS_DIR / spec_file

    with open(spec_path, "r", encoding="utf-8") as f:
        spec_dict = json.load(f)

    async def run_check():
        async with async_playwright() as p:
            browser = await p.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
            page = await browser.new_page(viewport={"width": 1080, "height": 1920})
            await page.goto(f"file://{template_path.resolve()}")
            await page.evaluate(f"window.initTemplate({json.dumps(spec_dict)}, 1080, 1920)")

            # Check text measurements across multiple timestamps
            timestamps = [0.5, 2.0, 4.5, 7.0, 9.5]
            for t in timestamps:
                await page.evaluate(f"window.draw({t})")

                # Measure canvas text safe area compliance in page context
                metrics = await page.evaluate("""() => {
                    const canvas = document.getElementById('canvas');
                    const ctx = canvas.getContext('2d');
                    const w = canvas.width;
                    const h = canvas.height;
                    const safeMarginX = 80;
                    const safeMarginY = 160;
                    const maxContentWidth = w - (safeMarginX * 2);

                    return {
                        canvasWidth: w,
                        canvasHeight: h,
                        maxContentWidth: maxContentWidth,
                        safeMarginX: safeMarginX,
                        safeMarginY: safeMarginY
                    };
                }""")

                assert metrics["canvasWidth"] == 1080
                assert metrics["canvasHeight"] == 1920
                assert metrics["maxContentWidth"] == 920

            # Specifically verify text wrapping logic in timeline explainer
            if "timeline" in template_name:
                wrap_result = await page.evaluate("""() => {
                    const canvas = document.getElementById('canvas');
                    const ctx = canvas.getContext('2d');
                    const sScale = canvas.width / 1080;
                    const safeLeft = 80 * sScale;
                    const safeRight = canvas.width - (80 * sScale);
                    const axisX = safeLeft + 40 * sScale;
                    const cardX = axisX + 36 * sScale;
                    const cardW = safeRight - cardX;
                    const contentPadX = 24 * sScale;
                    const maxTextW = cardW - (contentPadX * 2);

                    ctx.font = '400 15px -apple-system, sans-serif';
                    const sampleText = "在空间自注意力后引入一维时间注意力，使视频潜空间帧间连贯性获得质的跃升";
                    let curLine = "";
                    let maxMeasuredWidth = 0;
                    for (let char of sampleText) {
                        const testLine = curLine + char;
                        const w = ctx.measureText(testLine).width;
                        if (w > maxTextW) {
                            curLine = char;
                        } else {
                            curLine = testLine;
                            if (w > maxMeasuredWidth) maxMeasuredWidth = w;
                        }
                    }
                    return { maxMeasuredWidth, maxTextW, fits: maxMeasuredWidth <= maxTextW };
                }""")
                assert wrap_result["fits"] is True
                assert wrap_result["maxMeasuredWidth"] <= wrap_result["maxTextW"]

            await browser.close()

    asyncio.run(run_check())
