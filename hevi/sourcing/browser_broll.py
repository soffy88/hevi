"""Browser-agent B-roll recorder for Explainer Master v8 Step 6.

Playwright is imported lazily so deployments without a browser can report a
structured capability error instead of returning a fake media path.
"""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


class BrowserBrollUnavailable(RuntimeError):
    """Playwright/browser capability is not installed or configured."""


class BrowserBrollError(RuntimeError):
    """The target page could not be recorded."""


async def browser_broll_recorder(
    target_url: str,
    *,
    highlight_selector: str | None = None,
    duration_s: float = 5.0,
    aspect_ratio: str = "9:16",
    output_path: Path,
    playwright_factory: Any = None,
) -> Path:
    """Record a real web page with a mobile/landscape viewport."""
    parsed = urlparse(target_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise BrowserBrollError("target_url 必须是 http(s) URL")
    if duration_s <= 0 or duration_s > 120:
        raise BrowserBrollError("B-roll duration_s 必须在 0 到 120 秒之间")
    if aspect_ratio not in {"9:16", "16:9"}:
        raise BrowserBrollError("aspect_ratio 仅支持 9:16 或 16:9")
    if playwright_factory is None:
        try:
            playwright_module = importlib.import_module("playwright.async_api")
            playwright_factory = playwright_module.async_playwright
        except ImportError as exc:
            raise BrowserBrollUnavailable(
                "Browser B-roll 不可用：未安装 Playwright 浏览器运行时"
            ) from exc

    viewport = (
        {"width": 1080, "height": 1920}
        if aspect_ratio == "9:16"
        else {"width": 1920, "height": 1080}
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    async with playwright_factory() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception as exc:
            raise BrowserBrollUnavailable(f"Browser B-roll 浏览器启动失败: {exc}") from exc
        context = await browser.new_context(
            viewport=viewport,
            record_video_dir=str(output_path.parent),
        )
        page = await context.new_page()
        try:
            await page.goto(target_url, wait_until="networkidle", timeout=30_000)
            if highlight_selector:
                await page.add_style_tag(
                    content=(
                        f"{highlight_selector} {{ outline: 4px solid #f59e0b !important; "
                        "background: rgba(245,158,11,.2) !important; }}"
                    )
                )
                await page.locator(highlight_selector).scroll_into_view_if_needed()
            await page.evaluate(
                """async (duration) => {
                    const start = performance.now();
                    await new Promise(resolve => {
                      const tick = now => {
                        window.scrollBy(0, 2);
                        if (now - start >= duration) resolve();
                        else requestAnimationFrame(tick);
                      };
                      requestAnimationFrame(tick);
                    });
                }""",
                duration_s * 1000,
            )
            await asyncio.sleep(0.2)
            recorded_path = await page.video.path()
        except Exception as exc:
            raise BrowserBrollError(f"Browser B-roll 页面录制失败: {exc}") from exc
        finally:
            await context.close()
            await browser.close()
    if not recorded_path or not Path(recorded_path).is_file():
        raise BrowserBrollError("Browser B-roll 未产出视频文件")
    Path(recorded_path).replace(output_path)
    return output_path
