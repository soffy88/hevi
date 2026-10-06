"""P9.1.d.3 — html_gsap adapter: execute only.

HTML -> browser -> capture -> video. The browser is Playwright, driven in-process, so
the runtime class is **LOCAL_PROCESS** — not CLI, because there is no renderer binary
on PATH. Saying CLI here would be the name-based classification P9's audit forbade.

The P9.1.d.3 required split is enforced: this adapter returns a locator. The legacy
``HtmlGsapRenderer`` renders the same artifact and, since P9.1.d, also only returns a
locator. Hashing and probing live in the framework.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from hevi.qualification.models import (
    AdapterAvailability,
    AdapterFailure,
    Availability,
    ExecutionResult,
    ExecutionState,
    QualificationRequest,
    RuntimeUnavailable,
)
from hevi.qualification.providers._shared import check_locator, result_for, unavailable

DEFAULT_SCENE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{margin:0;height:100%;background:#0f172a}
  .card{position:absolute;inset:18% 12%;border-radius:24px;background:#1e293b;
        display:flex;align-items:center;justify-content:center}
  h1{color:#f8fafc;font:600 56px system-ui,sans-serif}
  .dot{width:64px;height:64px;border-radius:50%%;background:#38bdf8;margin-left:32px}
</style></head>
<body>
  <div class="card"><h1>HEVI html_gsap</h1><div class="dot"></div></div>
  <script>
    const dot = document.querySelector('.dot');
    let t = 0;
    (function step(){
      t += 0.08;
      dot.style.transform = 'translateX(' + (120*Math.sin(t)) + 'px)';
      requestAnimationFrame(step);
    })();
  </script>
</body></html>
"""


class HtmlGsapAdapter:
    """Executes a Playwright capture of an HTML scene. Returns a locator."""

    provider_id = "html_gsap"

    def __init__(self, scene_source: str | None = None) -> None:
        self._scene = scene_source or DEFAULT_SCENE

    def available(self) -> AdapterAvailability:
        if shutil.which("ffmpeg") is None:
            return unavailable("ffmpeg_not_found:required to encode the capture")
        try:
            import playwright  # noqa: F401
        except ImportError:
            return unavailable("playwright_not_installed:in-process browser capture")
        return AdapterAvailability(Availability.AVAILABLE)

    def execute(self, request: QualificationRequest) -> ExecutionResult:
        availability = self.available()
        if not availability.can_run:
            raise RuntimeUnavailable(availability.reason)

        import asyncio


        work = Path(request.output_path).parent / "html_gsap_src"
        work.mkdir(parents=True, exist_ok=True)
        (work / "index.html").write_text(self._scene, encoding="utf-8")
        duration = float(request.params.get("duration_s", 1.5))

        target = Path(request.output_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        async def _capture() -> None:
            from playwright.async_api import async_playwright

            async with async_playwright() as pw:
                browser = await pw.chromium.launch(args=["--no-sandbox"])
                page = await browser.new_page(
                    viewport={"width": 640, "height": 360},
                    record_video_dir=str(work / "video"),
                    record_video_size={"width": 640, "height": 360},
                )
                await page.goto((work / "index.html").as_uri())
                await page.wait_for_timeout(int(duration * 1000))
                await page.close()
                await browser.close()

        try:
            asyncio.run(_capture())
        except Exception as exc:
            raise AdapterFailure(
                ExecutionState.FAILED, f"{type(exc).__name__}:{exc}"[:300]
            ) from exc

        recorded = sorted((work / "video").glob("*.webm"))
        if not recorded:
            raise AdapterFailure(
                ExecutionState.NO_ARTIFACT, "playwright recorded no video"
            )
        import subprocess

        proc = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(recorded[-1]),
             "-pix_fmt", "yuv420p", "-c:v", "libx264", str(target)],
            capture_output=True, timeout=300, check=False,
        )
        if proc.returncode != 0:
            raise AdapterFailure(
                ExecutionState.FAILED,
                f"ffmpeg_exit_{proc.returncode}:{proc.stderr.decode(errors='replace')[:200]}",
            )
        check_locator(request, self.provider_id)
        return result_for(
            request,
            {"runtime_class": "local_process", "browser": "chromium",
             "exit_code": "0", "encoder": "ffmpeg/libx264"},
        )


__all__ = ["DEFAULT_SCENE", "HtmlGsapAdapter"]
