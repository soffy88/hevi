"""Browser check executor (``qa.browser_check_executor``).

Clean-room minimal executor for the *discipline* in
``hevi-vs-open-3d-skills.md`` section 2.7 (site-check), the B2 item
left undone by the A2 matrix gate. The matrix caliber is reused,
not redefined: the plan is judged first by
``qa.browser_check_matrix`` (Chromium plus WebKit at 1440 / 768 /
390, deep links, a caller-supplied ready expression and settle
wait, unexamined items stated, exit code 1 on any failing shot),
and the report this executor writes is judged by the same gate's
report check before it is returned.

Scope, stated plainly: this executor only ever loads pages the
caller supplies as local fixture text, served from a loopback
server it starts itself. A deep link that is not a local path, or
that has no fixture page, fails closed before any browser
launches; nothing here fetches the network. Each shot records
page errors, HTTP 4xx/5xx responses, blank canvases (a canvas
whose sampled pixels are a single colour), and horizontal
overflow, and saves a screenshot; a contact sheet marks failing
shots. What the matrix discipline leaves to human eyes (phone
cropping, text contrast, UI occlusion, lighting, WebKit colour
differences) is not claimed here: the plan's ``unexamined`` list
is carried into the report unchanged.

A browser that cannot launch is a hard failure, never a silent
subset: if the Playwright cache holds a newer browser build than
the installed driver expects (observed on this host for WebKit),
the executor retries with that cached build's own launcher and
records which executable ran each browser. No browser is ever
downloaded. A ready-expression timeout raises
:class:`CapabilityError` and no report is claimed, because a
shot that never became ready was never checked.
"""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hevi.capabilities.athenaion_browser import CHROMIUM_ARGS
from hevi.capabilities.browser_check_matrix import (
    REQUIRED_BROWSERS,
    REQUIRED_WIDTHS,
    check_browser_check_plan,
    check_browser_check_report,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_NAVIGATION_TIMEOUT_MS = 15000

_CANVAS_PROBE = """
() => {
  const out = [];
  for (const canvas of document.querySelectorAll('canvas')) {
    const w = canvas.width, h = canvas.height;
    if (!w || !h) { out.push({width: w, height: h, distinct: 0, unreadable: false}); continue; }
    try {
      const ctx = canvas.getContext('2d');
      if (!ctx) { out.push({width: w, height: h, distinct: 0, unreadable: true}); continue; }
      const data = ctx.getImageData(0, 0, w, h).data;
      const seen = new Set();
      for (let i = 0; i < data.length; i += 4) {
        seen.add((data[i] << 24) | (data[i+1] << 16) | (data[i+2] << 8) | data[i+3]);
        if (seen.size > 1) break;
      }
      out.push({width: w, height: h, distinct: seen.size, unreadable: false});
    } catch (err) {
      out.push({width: w, height: h, distinct: 0, unreadable: true});
    }
  }
  return out;
}
"""

_OVERFLOW_PROBE = (
    "() => document.documentElement.scrollWidth > window.innerWidth"
)


def _fail(message: str) -> CapabilityError:
    return CapabilityError(f"qa.browser_check_executor: {message}")


def _playwright_cache() -> Path:
    return Path.home() / ".cache" / "ms-playwright"


def _find_cached_executable(browser: str) -> Path | None:
    """Newest cached launcher for *browser*, or None.

    Only paths already present in the local Playwright cache are
    considered; nothing is downloaded. WebKit builds ship
    ``pw_run.sh``; Chromium builds ship a chrome binary.
    """
    cache = _playwright_cache()
    if not cache.is_dir():
        return None
    candidates: list[Path] = []
    for child in sorted(cache.iterdir(), key=lambda p: p.name, reverse=True):
        if browser == "webkit" and child.name.startswith("webkit-"):
            launcher = child / "pw_run.sh"
            if launcher.is_file():
                candidates.append(launcher)
        elif browser == "chromium" and child.name.startswith("chromium"):
            for rel in (
                "chrome-linux64/chrome",
                "chrome-linux/chrome",
                "chrome-headless-shell-linux64/chrome-headless-shell",
            ):
                binary = child / rel
                if binary.is_file():
                    candidates.append(binary)
    return candidates[0] if candidates else None


def _launch(pw: Any, browser: str) -> tuple[Any, str]:
    """Launch *browser*, retrying with a cached build on a missing executable.

    Returns (browser_handle, executable_description). The description
    is ``"playwright-default"`` when the default launch works, else
    the cached launcher path that was used.
    """
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception as exc:  # pragma: no cover - import guard
        raise _fail(f"Playwright is not importable: {exc}") from exc
    browser_type = getattr(pw, browser)
    kwargs: dict[str, Any] = {"headless": True}
    if browser == "chromium":
        kwargs["args"] = list(CHROMIUM_ARGS)
    try:
        return browser_type.launch(**kwargs), "playwright-default"
    except Exception as exc:
        if "Executable doesn't exist" not in str(exc):
            raise _fail(f"{browser} failed to launch: {exc}") from exc
    cached = _find_cached_executable(browser)
    if cached is None:
        raise _fail(
            f"{browser} executable is missing from the Playwright cache "
            f"({_playwright_cache()}) and nothing was downloaded; "
            "install the matching browser build before running a check"
        ) from None
    try:
        kwargs["executable_path"] = str(cached)
        return browser_type.launch(**kwargs), str(cached)
    except Exception as exc:
        raise _fail(
            f"{browser} failed to launch via cached executable {cached}: {exc}"
        ) from exc


def browsers_available() -> dict[str, bool]:
    """Probe-launch each matrix browser once. No page is checked."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {name: False for name in REQUIRED_BROWSERS}
    available: dict[str, bool] = {}
    with sync_playwright() as pw:
        for name in REQUIRED_BROWSERS:
            handle = None
            try:
                handle, _ = _launch(pw, name)
                page = handle.new_page()
                page.close()
                available[name] = True
            except Exception:
                available[name] = False
            finally:
                if handle is not None:
                    try:
                        handle.close()
                    except Exception:
                        pass
    return available


def _validate_fixtures(fixture_pages: Any) -> dict[str, str]:
    if not isinstance(fixture_pages, dict) or not fixture_pages:
        raise _fail("fixture_pages must be a non-empty object of path -> HTML text")
    out: dict[str, str] = {}
    for path, html in fixture_pages.items():
        if not isinstance(path, str) or not path.startswith("/"):
            raise _fail(f"fixture path {path!r} must start with '/' (local only)")
        if ".." in urlsplit(path).path.split("/"):
            raise _fail(f"fixture path {path!r} must not contain '..'")
        if not isinstance(html, str) or not html.strip():
            raise _fail(f"fixture page {path!r} must be non-empty HTML text")
        out[urlsplit(path).path] = html
    return out


class _FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        pages: dict[str, str] = self.server.fixture_pages  # type: ignore[attr-defined]
        body = pages.get(urlsplit(self.path).path)
        if body is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"not found: no fixture page for this path")
            return
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _shot_slug(url_path: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", urlsplit(url_path).path.strip("/"))
    return slug or "root"


def _build_contact_sheet(
    shots: list[dict[str, Any]], shots_dir: Path, out_path: Path
) -> Path:
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        raise _fail(f"Pillow is required for the contact sheet: {exc}") from exc
    thumbs: list[Any] = []
    thumb_w = 360
    for shot in shots:
        image = Image.open(shot["screenshot"]).convert("RGB")
        scale = thumb_w / max(1, image.width)
        thumb = image.resize((thumb_w, max(1, int(image.height * scale))))
        frame = Image.new("RGB", (thumb_w + 8, thumb.height + 8), (200, 30, 30) if shot["failures"] else (120, 120, 120))
        frame.paste(thumb, (4, 4))
        draw = ImageDraw.Draw(frame)
        draw.rectangle([0, 0, frame.width - 1, frame.height - 1], outline=(200, 30, 30) if shot["failures"] else (120, 120, 120), width=4)
        thumbs.append(frame)
    if not thumbs:
        raise _fail("no shots were captured; no contact sheet can be built")
    cols = 2
    rows = (len(thumbs) + cols - 1) // cols
    cell_h = max(t.height for t in thumbs)
    sheet = Image.new("RGB", (cols * (thumb_w + 16), rows * (cell_h + 8)), (255, 255, 255))
    for index, thumb in enumerate(thumbs):
        sheet.paste(thumb, ((index % cols) * (thumb_w + 16) + 4, (index // cols) * (cell_h + 8) + 4))
    sheet.save(out_path)
    return out_path


def run_browser_check(
    plan: Any,
    fixture_pages: Any,
    *,
    out_dir: Path,
    viewport_height: int = 800,
) -> dict[str, Any]:
    """Run a matrix check against local fixture pages only.

    Returns the report dict (also written to ``out_dir``). Raises
    :class:`CapabilityError` for a malformed plan, a non-local deep
    link, a missing fixture page, an unlaunchable browser, or a
    ready-expression timeout. A failing shot does not raise: it
    ends the report with ``exit_code`` 1, as the matrix requires.
    """
    gate = check_browser_check_plan(plan)
    if gate["verdict"] != "pass":
        codes = ", ".join(sorted({i["code"] for i in gate["issues"]}))
        raise _fail(f"plan fails qa.browser_check_matrix ({codes})")
    matrix = plan["matrix"]
    browsers: list[str] = list(matrix["browsers"])
    widths: list[int] = list(matrix["widths"])
    deep_links: list[str] = list(matrix["deep_links"])
    ready: str = matrix["ready"]
    wait_ms = matrix["wait_ms"]
    if not isinstance(viewport_height, int) or isinstance(viewport_height, bool) or viewport_height <= 0:
        raise _fail("viewport_height must be a positive integer")
    fixtures = _validate_fixtures(fixture_pages)
    for link in deep_links:
        if not isinstance(link, str) or not link.startswith("/"):
            raise _fail(
                f"deep link {link!r} is not a local path; this executor "
                "only checks local fixture pages and never fetches the network"
            )
        if urlsplit(link).path not in fixtures:
            raise _fail(f"deep link {link!r} has no fixture page in fixture_pages")

    out_dir = Path(out_dir)
    shots_dir = out_dir / "shots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
    server.fixture_pages = fixtures  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    shots: list[dict[str, Any]] = []
    executables: dict[str, str] = {}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        server.shutdown()
        raise _fail(f"Playwright is not importable: {exc}") from exc
    try:
        with sync_playwright() as pw:
            for browser_name in browsers:
                handle, executable = _launch(pw, browser_name)
                executables[browser_name] = executable
                try:
                    for width in widths:
                        for link in deep_links:
                            url = f"http://127.0.0.1:{port}{link}"
                            page_errors: list[str] = []
                            statuses: list[dict[str, Any]] = []
                            context = handle.new_context(
                                viewport={"width": int(width), "height": viewport_height}
                            )
                            page = context.new_page()
                            page.on("pageerror", lambda err: page_errors.append(str(err)))
                            page.on(
                                "response",
                                lambda resp: statuses.append(
                                    {"url": resp.url, "status": resp.status}
                                ),
                            )
                            try:
                                page.goto(url, timeout=_NAVIGATION_TIMEOUT_MS)
                                try:
                                    page.wait_for_function(
                                        f"() => ({ready})", timeout=int(wait_ms)
                                    )
                                except Exception as exc:
                                    raise _fail(
                                        f"ready expression {ready!r} never became "
                                        f"true on {browser_name} {width}px {link} "
                                        f"within {wait_ms}ms ({exc}); the shot "
                                        "was not checked and no report is claimed"
                                    ) from exc
                                page.wait_for_timeout(int(wait_ms))
                                canvases = page.evaluate(_CANVAS_PROBE)
                                overflow = bool(page.evaluate(_OVERFLOW_PROBE))
                                title = page.title()
                            finally:
                                shot_path = (
                                    shots_dir
                                    / f"{browser_name}_{width}_{_shot_slug(link)}.png"
                                )
                                page.screenshot(path=str(shot_path))
                                context.close()
                            failures: list[str] = []
                            if page_errors:
                                failures.append("page_error")
                            for entry in statuses:
                                status = entry["status"]
                                if 400 <= status < 500 and "http_4xx" not in failures:
                                    failures.append("http_4xx")
                                elif status >= 500 and "http_5xx" not in failures:
                                    failures.append("http_5xx")
                            canvas_blank = any(
                                isinstance(c, dict)
                                and not c.get("unreadable")
                                and c.get("width")
                                and c.get("height")
                                and c.get("distinct", 0) <= 1
                                for c in canvases
                            )
                            if canvas_blank:
                                failures.append("blank_canvas")
                            if overflow:
                                failures.append("horizontal_overflow")
                            shots.append(
                                {
                                    "browser": browser_name,
                                    "width": int(width),
                                    "url": url,
                                    "path": link,
                                    "title": title,
                                    "failures": failures,
                                    "page_errors": page_errors,
                                    "http_statuses": statuses,
                                    "canvases": canvases,
                                    "horizontal_overflow": overflow,
                                    "screenshot": str(shot_path),
                                }
                            )
                finally:
                    handle.close()
    finally:
        server.shutdown()
        server.server_close()

    saw_failure = any(shot["failures"] for shot in shots)
    exit_code = 1 if saw_failure else 0
    contact_sheet = _build_contact_sheet(shots, shots_dir, out_dir / "contact_sheet.jpg")
    report: dict[str, Any] = {
        "verdict": "fail" if saw_failure else "pass",
        "exit_code": exit_code,
        "shots_checked": len(shots),
        "saw_failure": saw_failure,
        "shots": [
            {
                "browser": s["browser"],
                "width": s["width"],
                "url": s["url"],
                "failures": s["failures"],
                "screenshot": s["screenshot"],
            }
            for s in shots
        ],
        "shot_detail": shots,
        "unexamined": list(plan.get("unexamined") or plan.get("not_checked") or []),
        "browser_executables": executables,
        "navigation_timeout_ms": _NAVIGATION_TIMEOUT_MS,
        "viewport_height": viewport_height,
        "contact_sheet": str(contact_sheet),
        "local_only": True,
    }
    report_gate = check_browser_check_report(
        {"shots": report["shots"], "exit_code": exit_code}
    )
    if report_gate["verdict"] != "pass":
        raise _fail(
            "the executor's own report fails qa.browser_check_matrix "
            f"({report_gate['issues']}); no report is returned"
        )
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = run_browser_check(
        params.get("plan"),
        params.get("fixture_pages"),
        out_dir=out_dir,
        viewport_height=params.get("viewport_height", 800),
    )
    report_path = out_dir / "browser_check_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "exit_code": report["exit_code"],
            "verdict": report["verdict"],
            "shots_checked": report["shots_checked"],
            "ok": report["verdict"] == "pass",
        },
    )


def register_browser_check_executor_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.browser_check_executor",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                    "fixture_pages": {"type": "object"},
                    "viewport_height": {"type": "integer"},
                },
                "required": ["plan", "fixture_pages"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=True,
            description=(
                "Browser check executor (open-3d B2, clean-room): runs "
                "a qa.browser_check_matrix plan with local Playwright "
                "against caller-supplied local fixture pages only "
                "(loopback server, no network), recording page "
                "errors, 4xx/5xx, blank canvases and horizontal "
                "overflow per shot, with screenshots and a contact "
                "sheet. Failing shots end with exit code 1. See "
                "OPEN_3D_SKILLS_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.browser_check_executor"]


register_browser_check_executor_capabilities_once()
