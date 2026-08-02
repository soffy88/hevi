from __future__ import annotations

from pathlib import Path

import pytest

from hevi.sourcing.browser_broll import BrowserBrollError, browser_broll_recorder


@pytest.mark.asyncio
async def test_browser_broll_rejects_non_http_urls(tmp_path: Path) -> None:
    with pytest.raises(BrowserBrollError, match=r"http\(s\)"):
        await browser_broll_recorder("javascript:alert(1)", output_path=tmp_path / "x.webm")


@pytest.mark.asyncio
async def test_browser_broll_records_real_playwright_video(tmp_path: Path) -> None:
    recorded = tmp_path / "recorded.webm"
    recorded.write_bytes(b"webm")

    class Video:
        async def path(self) -> str:
            return str(recorded)

    class Page:
        video = Video()

        async def goto(self, *_args, **_kwargs):
            return None

        async def evaluate(self, *_args, **_kwargs):
            return None

    class Context:
        async def new_page(self):
            return Page()

        async def close(self):
            return None

    class Browser:
        async def launch(self, **_kwargs):
            return self

        async def new_context(self, **_kwargs):
            return Context()

        async def close(self):
            return None

    class Playwright:
        chromium = Browser()

    class Factory:
        async def __aenter__(self):
            return Playwright()

        async def __aexit__(self, *_args):
            return None

    output = tmp_path / "nested" / "broll.webm"
    result = await browser_broll_recorder(
        "https://example.com", output_path=output, playwright_factory=lambda: Factory()
    )
    assert result == output
    assert output.read_bytes() == b"webm"
