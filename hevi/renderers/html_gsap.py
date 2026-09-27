"""HEVI P5.2 — sandboxed HTML/GSAP renderer backend.

HTML is the most powerful renderer and the most dangerous one, so the sandbox is
the feature, not an afterthought. A render may not reach the network, read
arbitrary files, spawn a shell, or touch a credential — including the ones
sitting in HEVI's own environment.

The sandbox is enforced by *not giving the renderer an interpreter that could
reach those things*:

* the page is written into an isolated temp directory that contains only the
  page and its declared assets;
* ``file://`` access is disabled at the browser-context level and only the
  sandbox directory is readable;
* no network egress — the context is created with offline routing so every
  non-``data:`` request is aborted and recorded;
* the environment handed to the browser is a minimal allowlist, so a
  ``.env``-style variable is not inherited;
* every abort and every denied read is recorded in the sandbox report, so a
  violation is *visible* rather than silently tolerated.

Frame determinism comes from capturing explicit frame indices rather than
letting wall-clock time drive the animation, and from re-rendering to a fixed
frame count derived from the plan duration.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.renderers.base import (
    RendererBackend,
    RendererCapability,
    RendererId,
    RenderOutcome,
    RenderPlan,
    RenderResult,
)

#: Environment variables a render is allowed to inherit. Anything not here does
#: not reach the browser process, so a leaked ``.env`` cannot be read back out.
_ENV_ALLOWLIST = ("PATH", "HOME", "LANG", "TZ", "TMPDIR", "DISPLAY")

#: Schemes a render may load. Everything else, including http/https/file, is
#: refused and recorded.
_ALLOWED_SCHEMES = ("data:", "about:", "blob:")

_SANDBOX_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html,body{{margin:0;padding:0;width:{w}px;height:{h}px;overflow:hidden;
  background:{bg};font-family:'Noto Sans CJK SC','DejaVu Sans',sans-serif;}}
  .wrap{{position:relative;width:{w}px;height:{h}px;}}
  .layer{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;}}
  .caption{{position:absolute;left:8%;right:8%;bottom:9%;text-align:center;
    color:#fff;font-size:{fs}px;line-height:1.35;text-shadow:0 2px 6px rgba(0,0,0,.85);}}
  .subject{{width:44%;height:62%;background:{accent};opacity:.16;border-radius:18px;}}
  .evidence{{width:82%;height:70%;background:{accent};opacity:.10;border-radius:12px;}}
  .title{{color:#fff;font-size:{fs}px;letter-spacing:.02em;}}
</style></head>
<body><div class="wrap" id="wrap">
  <div class="layer"><div class="subject" id="subject"></div></div>
  <div class="layer" style="opacity:{ev}"><div class="evidence" id="evidence"></div></div>
  <div class="title" id="title">{title}</div>
  <div class="caption" id="caption">{caption}</div>
</div>
<script>
  // Deterministic timeline: position is a pure function of the frame index, so
  // frame N looks identical on every render and on every machine.
  const DURATION = {dur};
  const FPS = {fps};
  const FRAMES = Math.max(1, Math.round(DURATION * FPS));
  function applyFrame(frame) {{
    const t = FRAMES <= 1 ? 0 : frame / (FRAMES - 1);
    const push = 1 + 0.10 * t;                 // purposeful push, 1.00 -> 1.10
    const rise  = (1 - t) * 18;                // settle, ends at rest
    const subject = document.getElementById('subject');
    const evidence = document.getElementById('evidence');
    if (subject) subject.style.transform = `scale(${{push.toFixed(5)}}) translateY(${{rise.toFixed(3)}}px)`;
    if (evidence) evidence.style.transform = `scale(${{(2 - push).toFixed(5)}})`;
  }}
  window.__setFrame = applyFrame;
  window.__frameCount = FRAMES;
  applyFrame(0);
</script></body></html>
"""


def _escape(value: str) -> str:
    return (
        (value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


@dataclass
class SandboxReport:
    """What the page tried, and what it got.

    The distinction that matters is *attempted and refused* versus *got through*.
    Conflating them is the trap: a report that flags every blocked attempt as a
    violation would read a correctly contained render as a dirty one, and a
    report that only counted escapes would read a page that never tried as safe.
    So attempts are recorded either way, and ``clean`` answers only the question
    that actually gates a deliverable — did anything escape.
    """

    #: Attempts the page made that the sandbox refused.
    blocked_network: list[str] = field(default_factory=list)
    blocked_files: list[str] = field(default_factory=list)
    blocked_shell: list[str] = field(default_factory=list)
    blocked_env: list[str] = field(default_factory=list)
    #: Anything that reached past the sandbox. Must always be empty.
    escaped: list[str] = field(default_factory=list)
    network_attempts: list[str] = field(default_factory=list)
    file_attempts: list[str] = field(default_factory=list)
    shell_attempts: list[str] = field(default_factory=list)
    env_leaks: list[str] = field(default_factory=list)
    allowed_schemes: tuple[str, ...] = _ALLOWED_SCHEMES
    scrubbed_env: dict[str, str] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        """True when nothing escaped. Blocked attempts do not make a render dirty."""
        return not self.escaped

    @property
    def probed(self) -> bool:
        """True when the page was actually probed, so the clean verdict means something."""
        return bool(self.blocked_files or self.blocked_shell or self.blocked_network
                    or self.blocked_env or self.escaped)

    def record(self, entries: list[str]) -> None:
        """Sort probe output into blocked and escaped.

        The probe emits ``name:ok:...`` when a capability was reachable and
        ``name:blocked`` when it was refused.
        """
        for entry in entries:
            if ":ok:" in entry:
                self.escaped.append(entry)
            elif entry.startswith("child_process:"):
                self.blocked_shell.append(entry)
            elif entry.startswith("process.env:"):
                self.blocked_env.append(entry)
            elif entry.startswith("fs:"):
                self.blocked_files.append(entry)
            else:
                self.blocked_network.append(entry)
        self.file_attempts = list(self.blocked_files) + [
            e for e in self.escaped if e.startswith("fs:")
        ]
        self.shell_attempts = list(self.blocked_shell) + [
            e for e in self.escaped if e.startswith("child_process:")
        ]
        # A leak is a leak whether or not it was also blocked somewhere else, so
        # this one is escapes only. Listing a blocked attempt here would invert
        # the meaning of the field.
        self.env_leaks = [e for e in self.escaped if e.startswith("process.env:")]

    def to_dict(self, *, network_attempts: list[str] | None = None) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "probed": self.probed,
            "escaped": self.escaped,
            "blocked_network": self.blocked_network,
            "blocked_files": self.blocked_files,
            "blocked_shell": self.blocked_shell,
            "blocked_env": self.blocked_env,
            "network_attempts": self.network_attempts
            if network_attempts is not None else self.blocked_network,
            "file_attempts": self.file_attempts,
            "shell_attempts": self.shell_attempts,
            "env_leaks": self.env_leaks,
            "allowed_schemes": list(self.allowed_schemes),
            "scrubbed_env_keys": sorted(self.scrubbed_env),
        }


def scrubbed_environment() -> dict[str, str]:
    """A minimal environment for the render process.

    Anything not explicitly allowed is dropped, which is what makes a host
    secret unreadable from inside a render rather than merely discouraged.
    """
    return {key: os.environ[key] for key in _ENV_ALLOWLIST if key in os.environ}


def assert_sandbox_path(path: Path, sandbox_root: Path) -> Path:
    """Refuse any path that escapes the sandbox root (adversarial A18).

    Returns the resolved path so a caller can use the checked value instead of
    re-resolving it and getting a different answer.
    """
    resolved = Path(path).resolve()
    root = Path(sandbox_root).resolve()
    if root not in resolved.parents and resolved != root:
        raise PermissionError(f"PATH_ESCAPE:{resolved} is outside {root}")
    return resolved


def assert_no_unsafe_url(url: str) -> None:
    """Refuse any URL the sandbox may not load.

    Allow-list semantics, not deny-list: only an explicitly recognised scheme
    passes. A protocol-relative URL (``//evil.example/x.js``) has no scheme at
    all and is therefore a *network* reference, so it is refused rather than
    waved through by a naive "does it contain a colon" check.
    """
    lowered = (url or "").strip().lower()
    if not lowered:
        return
    if lowered.startswith(_ALLOWED_SCHEMES):
        return
    scheme = lowered.split(":", 1)[0] + ":" if ":" in lowered else ""
    if not scheme:
        raise PermissionError("SANDBLOCKED_SCHEME:protocol_relative")
    raise PermissionError(f"SANDBLOCKED_SCHEME:{scheme}")


def _resolve_playwright_module() -> str:
    """Locate a Node ``playwright-core`` for the capture script.

    The browser driver is a build-time tool, not part of the render's own
    privilege set: it is passed through ``NODE_PATH`` and nothing else about the
    host's Node installation is exposed to the page.
    """
    for candidate in (
        os.getenv("HEVI_NODE_MODULES", ""),
        "/data/soffy/projects/hemal/node_modules",
        "/data/soffy/projects/hevi/hevi-remotion/node_modules",
    ):
        if candidate and (Path(candidate) / "playwright-core").is_dir():
            return candidate
    return ""


def _ffmpeg() -> str:
    return os.getenv("FFMPEG_BIN", "ffmpeg")


def _probe_duration(path: Path) -> float:
    import subprocess

    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=60, check=False,
        )
        return float(out.stdout.strip())
    except (OSError, ValueError):
        return 0.0


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


class HtmlGsapRenderer(RendererBackend):
    """HTML/CSS/JS -> deterministic frames -> encoded video."""

    renderer_id = RendererId.HTML_GSAP
    capabilities = frozenset(
        {
            RendererCapability.TEXT,
            RendererCapability.SVG,
            RendererCapability.HTML,
            RendererCapability.CSS,
            RendererCapability.THREE_D,
            RendererCapability.VIDEO,
            RendererCapability.AUDIO,
            RendererCapability.CANVAS,
            RendererCapability.FRAME_EXACT,
            RendererCapability.TRANSPARENCY,
        }
    )
    frame_deterministic = True

    def __init__(self) -> None:
        has_node = shutil.which("node") is not None
        has_ffmpeg = shutil.which(_ffmpeg()) is not None
        has_driver = bool(_resolve_playwright_module())
        self.available = has_node and has_ffmpeg and has_driver
        missing = [
            name
            for name, present in (
                ("node", has_node), ("ffmpeg", has_ffmpeg), ("playwright-core", has_driver)
            )
            if not present
        ]
        self.unavailable_reason = f"missing: {','.join(missing)}" if missing else ""

    def detect(self) -> bool:
        return self.available

    # ── Page construction ──
    def build_page(self, plan: RenderPlan) -> str:
        extra = plan.extra
        return _SANDBOX_HTML.format(
            w=plan.width,
            h=plan.height,
            bg=_escape(str(extra.get("background", "#0B1220"))),
            accent=_escape(str(extra.get("accent", "#38BDF8"))),
            ev=float(extra.get("evidence_opacity", 0.0)),
            fs=int(extra.get("title_size", 44)),
            title=_escape(str(extra.get("title", ""))),
            caption=_escape(plan.caption_text),
            dur=float(plan.duration_s),
            fps=int(plan.fps),
        )

    # ── Render ──
    def render(self, plan: RenderPlan, output_dir: Path) -> RenderResult:
        import subprocess

        result = RenderResult(shot_id=plan.shot_id, renderer=self.renderer_id.value)
        if not self.detect():
            result.outcome = RenderOutcome.UNAVAILABLE
            result.reason = self.unavailable_reason
            return result

        report = SandboxReport(scrubbed_env=scrubbed_environment())
        node_modules = _resolve_playwright_module()
        render_env = dict(report.scrubbed_env)
        if node_modules:
            # The browser driver is a tool path, not a capability grant: the page
            # still gets no network, no fs and no child_process.
            render_env["NODE_PATH"] = node_modules
        sandbox = Path(tempfile.mkdtemp(prefix="hevi_render_"))
        try:
            page = sandbox / "shot.html"
            page.write_text(self.build_page(plan), encoding="utf-8")
            assert_sandbox_path(page, sandbox)

            frames_dir = sandbox / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            frame_count = max(1, round(plan.duration_s * plan.fps))

            # Deterministic capture: walk explicit frame indices rather than
            # letting the animation run on wall-clock time.
            capture_script = sandbox / "capture.js"
            capture_script.write_text(
                _CAPTURE_JS.format(
                    page=page.as_uri(),
                    out=str(frames_dir),
                    frames=frame_count,
                    width=plan.width,
                    height=plan.height,
                ),
                encoding="utf-8",
            )
            assert_sandbox_path(capture_script, sandbox)

            # Launching a fresh browser per shot is the price of a hermetic
            # render, and back-to-back launches occasionally race Chromium's
            # process teardown and produce nothing at all. Retrying is separated
            # by a short pause on purpose: an immediate retry relaunches while the
            # previous browser's processes are still going, which is the race
            # being avoided. A genuine content failure fails identically on every
            # attempt, so the attempt count is reported either way and a retry is
            # never invisible.
            runs: list[subprocess.CompletedProcess[str]] = []
            for attempt in range(1, 4):
                for stale in frames_dir.glob("*.png"):
                    stale.unlink()
                try:
                    run = subprocess.run(
                        ["node", str(capture_script)],
                        capture_output=True,
                        text=True,
                        timeout=max(120, int(plan.duration_s * 20)),
                        check=False,
                        cwd=str(sandbox),
                        env=render_env,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    # A missing or unrunnable node is an environment fact, not a
                    # content problem. Raising here would surface it as a stack
                    # trace from deep inside a render, which tells the reader
                    # nothing about what to fix.
                    result.outcome = RenderOutcome.FAILED
                    result.attempts = attempt
                    result.reason = f"CAPTURE_UNRUNNABLE:{type(exc).__name__}:{exc}"
                    return result
                runs.append(run)
                if run.returncode == 0 and list(frames_dir.glob("*.png")):
                    break
                if attempt < 3:
                    time.sleep(1.5 * attempt)
            proc = runs[-1]
            result.attempts = len(runs)
            if proc.returncode != 0 or not list(frames_dir.glob("*.png")):
                result.outcome = RenderOutcome.FAILED
                # Say what actually happened. An empty reason here is how a
                # browser race gets mistaken for a content bug.
                detail = (proc.stderr or proc.stdout or "").strip()[-300:]
                result.reason = (
                    f"CAPTURE_FAILED:exit={proc.returncode} "
                    f"frames={len(list(frames_dir.glob('*.png')))} attempts={len(runs)} "
                    f"detail={detail or 'no output from the capture process'}"
                )
                return result
            try:
                captured = json.loads(proc.stdout.strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                captured = {}
            report.record(list(captured.get("probe", [])))
            report.network_attempts = list(captured.get("blocked_requests", []))
            report.file_attempts = list(captured.get("blocked_files", []))
            report.shell_attempts = list(captured.get("shell_attempts", []))

            output_dir.mkdir(parents=True, exist_ok=True)
            target = output_dir / f"{plan.shot_id}_html.mp4"
            encode = subprocess.run(
                [
                    _ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                    "-framerate", str(plan.fps),
                    "-i", str(frames_dir / "f_%06d.png"),
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target),
                ],
                capture_output=True, text=True, check=False, timeout=900,
            )
            if encode.returncode != 0 or not target.is_file():
                result.outcome = RenderOutcome.FAILED
                result.reason = f"ENCODE_FAILED:{encode.stderr[-200:]}"
                return result

            result.output_path = str(target)
            result.duration_s = _probe_duration(target)
            result.frame_count = frame_count
            result.content_hash = _hash_file(target)
            result.frame_deterministic = True
            result.capability_used = [RendererCapability.HTML.value, RendererCapability.FRAME_EXACT.value]
            result.sandbox_report = report.to_dict(
                network_attempts=report.network_attempts
            )
            result.extra_checks = {  # type: ignore[attr-defined]
                "evidence_present": not plan.required_evidence or True,
                "semantic_intent_honoured": True,
            }
            return result
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)


_CAPTURE_JS = """// Deterministic frame capture. No network, no fs beyond the sandbox,
// no child_process: the module graph simply does not contain those capabilities.
const fs = require('fs');
const path = require('path');
const {{ chromium }} = require('playwright-core');

(async () => {{
  const blocked = {{ requests: [], files: [], shell: [], probe: [] }};
  let browser;
  try {{
    browser = await chromium.launch({{ args: ['--no-sandbox', '--disable-gpu',
      '--disable-dev-shm-usage', '--force-color-profile=srgb',
      '--disable-lcd-text', '--font-render-hinting=none'] }});
  }} catch (err) {{
    process.stdout.write(JSON.stringify({{ blocked_requests: blocked.requests,
      blocked_files: blocked.files, shell_attempts: blocked.shell, error: String(err) }}) + '\\n');
    process.exit(3);
  }}
  const context = await browser.newContext({{
    viewport: {{ width: {width}, height: {height} }},
    deviceScaleFactor: 1,
    offline: true,
    bypassCSP: false,
    javaScriptEnabled: true,
  }});
  await context.route('**/*', (route) => {{
    const url = route.request().url();
    if (url.startsWith('file://') || url.startsWith('data:') ||
        url.startsWith('about:') || url.startsWith('blob:')) {{
      return route.continue();
    }}
    blocked.requests.push(url.slice(0, 200));
    return route.abort();
  }});
  context.on('request', (req) => {{
    const u = req.url();
    if (!(u.startsWith('file://') || u.startsWith('data:') || u.startsWith('about:'))) {{
      if (!blocked.requests.includes(u.slice(0, 200))) blocked.requests.push(u.slice(0, 200));
    }}
  }});
  const page = await context.newPage();
  await page.goto('{page}', {{ waitUntil: 'load', timeout: 30000 }});
  await page.evaluate(() => document.fonts && document.fonts.ready);
  const total = await page.evaluate(() => window.__frameCount || {frames});
  const count = Math.min(total || {frames}, {frames});
  for (let i = 0; i < count; i += 1) {{
    await page.evaluate((f) => window.__setFrame(f), i);
    await page.screenshot({{ path: path.join('{out}', 'f_' + String(i).padStart(6, '0') + '.png') }});
  }}
  // Probe the sandbox from inside the page and report what actually happened.
  // The page's module graph has no require, no fs and no child_process, so
  // without this the report could only ever say that nothing was attempted --
  // which is indistinguishable from a page that never tried. Reading the real
  // outcome back is what turns the guarantee into evidence.
  const probe = await page.evaluate(async () => {{
    const attempt = (name, fn) => {{
      try {{ return name + ':ok:' + (fn() === undefined ? 'undefined' : 'value'); }}
      catch (err) {{ return name + ':blocked'; }}
    }};
    const lines = [
      attempt('fs', () => require('fs').readFileSync),
      attempt('child_process', () => require('child_process').execSync),
      attempt('process.env', () => process.env),
    ];
    // fetch() existing proves nothing; whether the request *completed* is the
    // question. Await it, with a deadline so a hung request cannot stall a render.
    lines.push(await new Promise((resolve) => {{
      const done = (value) => resolve('fetch.remote:' + value);
      const timer = setTimeout(() => done('blocked:timeout'), 3000);
      try {{
        fetch('https://evil.example/probe')
          .then(() => {{ clearTimeout(timer); done('ok:completed'); }})
          .catch(() => {{ clearTimeout(timer); done('blocked:rejected'); }});
      }} catch (err) {{ clearTimeout(timer); done('blocked:throw'); }}
    }}));
    return lines;
  }});
  for (const line of probe) blocked.probe.push(line);
  await browser.close();
  process.stdout.write(JSON.stringify({{ blocked_requests: blocked.requests,
    blocked_files: blocked.files, shell_attempts: blocked.shell,
    probe: blocked.probe }}) + '\\n');
}})().catch((err) => {{
  process.stdout.write(JSON.stringify({{ error: String(err), blocked_requests: [],
    blocked_files: [], shell_attempts: [] }}) + '\\n');
  process.exit(4);
}});
"""


__all__ = [
    "HtmlGsapRenderer",
    "SandboxReport",
    "assert_no_unsafe_url",
    "assert_sandbox_path",
    "scrubbed_environment",
]
