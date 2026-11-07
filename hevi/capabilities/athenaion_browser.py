"""Shared headless-browser harness for the Athenaion graft (no capability).

Clean-room rewrite of the capture discipline only: serve a generated
page plus the vendored Three.js module already in this repository,
drive it with Playwright Chromium (SwiftShader), wait for the
``window.__hf`` settle confirmation, and capture whole frames.
Nothing is downloaded: if no vendored ``three.module.js`` is found
the harness raises instead of fetching one.

Pages built on this harness must expose ``window.__hf`` with
``getDurationFrames`` / ``seekFrame`` / ``destroy`` (see
``qa.frame_adapter_contract``), set ``window.__hfReady = true``
after the first render, and set ``window.__hfSettledFrame`` to the
frame just settled inside ``seekFrame``. View changes use
``window.__athenaion.show(name)`` plus a
``window.__athenaionSettled`` label; both are settle *confirmations*
read back from the page, never fixed waits.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError

CHROMIUM_ARGS = [
    "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
    "--ignore-gpu-blocklist", "--no-sandbox",
    "--disable-gpu-sandbox", "--disable-dev-shm-usage",
    "--font-render-hinting=none", "--disable-lcd-text",
    "--disable-font-subpixel-positioning", "--hide-scrollbars",
    "--force-color-profile=srgb", "--force-device-scale-factor=1",
]


def resolve_three_module() -> Path:
    """Locate the vendored Three.js module already in this repo."""
    candidates: list[Path] = []
    env = os.environ.get("HEVI_THREE_MODULE")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    candidates.extend([
        here.parents[1] / "layer4_legacy" / "scene3d" / "vendor" / "three" / "three.module.js",
        here.parents[1] / "manga" / "three_vendor" / "three" / "three.module.js",
        here.parents[1] / "video" / "hyperframes_vendor" / "three.module.js",
    ])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise CapabilityError(
        "athenaion harness: vendored three.module.js not found; checked "
        "HEVI_THREE_MODULE and the scene3d/manga/hyperframes vendor paths. "
        "Nothing is downloaded."
    )


def three_revision(three_path: Path) -> str:
    text = three_path.read_text(encoding="utf-8", errors="ignore")[:2000]
    for line in text.splitlines():
        if "REVISION" in line:
            return line.strip()
    return "unknown"


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/":
            body, ctype = self.server.html_bytes, "text/html; charset=utf-8"
        elif self.path == "/three.module.js":
            body, ctype = self.server.three_bytes, "text/javascript; charset=utf-8"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def page_html(body_script: str) -> str:
    """Wrap a module script in the minimal page shell."""
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">\n"
        "<style>html,body{margin:0;padding:0;background:#0b0b12;overflow:hidden}"
        "canvas{display:block}</style>\n"
        "<script>window.__hfError=null;window.__hfReady=false;"
        "window.__hfSettledFrame=-1;window.__athenaionSettled='';"
        "window.addEventListener('error',function(e){"
        "window.__hfError=String((e&&e.message)||'page error');});</script>\n"
        "<script type=\"importmap\">{\"imports\":{\"three\":\"/three.module.js\"}}</script>\n"
        "</head><body><div id=\"stage\"></div>\n"
        f"<script type=\"module\">{body_script}</script>\n"
        "</body></html>"
    )


def _browser_available() -> bool:
    try:
        import playwright  # noqa: F401
    except Exception:
        return False
    try:
        resolve_three_module()
    except Exception:
        return False
    cache = Path.home() / ".cache" / "ms-playwright"
    if cache.is_dir() and any("chromium" in d.name for d in cache.iterdir()):
        return True
    return any(Path(p).is_dir() for p in ("/home/soffy/.cache/ms-playwright",))


def capture_actions(
    html: str,
    actions: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Run one fresh browser; execute actions; return shots + stats.

    Each action: {"name": str, "evaluate": js-or-None,
    "settle": js-expression-or-None, "screenshot": bool}.
    ``settle`` defaults to the ``__hfSettledFrame`` check for a
    ``seekFrame`` call encoded in ``evaluate``; view actions must pass
    their own ``__athenaionSettled`` expression. The returned
    ``ready_ms`` is measured in Python from navigation to
    ``__hfReady``; no wall clock is read inside the page.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise CapabilityError(f"athenaion harness: Playwright is required: {exc}") from exc
    three_path = resolve_three_module()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.html_bytes = html.encode("utf-8")  # type: ignore[attr-defined]
    server.three_bytes = three_path.read_bytes()  # type: ignore[attr-defined]
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    shots: list[dict[str, Any]] = []
    stats: dict[str, Any] = {}
    ready_ms = 0.0
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=CHROMIUM_ARGS)
            try:
                page = browser.new_page(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                )
                started = time.perf_counter()
                page.goto(f"http://127.0.0.1:{port}/", wait_until="load", timeout=30000)
                page.wait_for_function("window.__hfReady === true", timeout=30000)
                ready_ms = round((time.perf_counter() - started) * 1000.0, 1)
                error = page.evaluate("window.__hfError")
                if error:
                    raise CapabilityError(f"athenaion harness: page failed to load: {error}")
                for action in actions:
                    name = str(action["name"])
                    if action.get("evaluate"):
                        page.evaluate(str(action["evaluate"]))
                    settle = action.get("settle")
                    if settle:
                        page.wait_for_function(str(settle), timeout=5000)
                    if action.get("screenshot", True):
                        shot = page.screenshot()
                        if not shot.startswith(b"\x89PNG"):
                            raise CapabilityError(
                                f"athenaion harness: capture for {name!r} did not return PNG"
                            )
                        shots.append({
                            "name": name,
                            "sha256": hashlib.sha256(shot).hexdigest(),
                            "bytes": len(shot),
                            "png_bytes": shot,
                        })
                stats = page.evaluate(
                    "window.__athenaionStats ? window.__athenaionStats() : null"
                ) or {}
            finally:
                browser.close()
    except CapabilityError:
        raise
    except Exception as exc:
        raise CapabilityError(f"athenaion harness: browser run failed: {exc}") from exc
    finally:
        server.shutdown()
        server.server_close()
    return {
        "shots": shots,
        "stats": stats,
        "ready_ms": ready_ms,
        "three_module": str(three_path),
        "three_revision": three_revision(three_path),
        "width": width,
        "height": height,
    }
