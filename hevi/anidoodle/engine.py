"""Locate and run the vendored anidoodle engine.

The engine is a Node project: every render is a subprocess run in the engine
folder, because its tools resolve ``src/canvas-core/<film>.ts`` against the
working directory.  Playwright is the only backend we use; the optional Remotion
adapter is deliberately not installed (S26 licence decision) and the 373 MB
optional sound pack is never fetched (brief rule).
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class AnidoodleError(RuntimeError):
    """A precondition or a render failed; the message names the cause."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def engine_dir() -> Path:
    override = os.environ.get("HEVI_ANIDOODLE_ENGINE")
    if override:
        return Path(override).expanduser().resolve()
    return _repo_root() / "third_party" / "anidoodle" / "engine"


def output_root() -> Path:
    override = os.environ.get("HEVI_ANIDOODLE_OUT")
    root = Path(override).expanduser() if override else _repo_root() / "data" / "anidoodle"
    root.mkdir(parents=True, exist_ok=True)
    return root


def node_binary() -> str:
    """Return a Node >= 20 binary.

    The host PATH does not always carry Node; a per-user nvm install is the
    usual reason.  An explicit ``HEVI_ANIDOODLE_NODE`` wins so tests and the
    container can pin one interpreter.
    """

    override = os.environ.get("HEVI_ANIDOODLE_NODE")
    if override:
        return override
    found = shutil.which("node")
    if found:
        return found
    for pattern in (
        str(Path.home() / ".nvm" / "versions" / "node" / "*" / "bin" / "node"),
        "/usr/local/bin/node",
        "/usr/bin/node",
    ):
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return matches[0]
    raise AnidoodleError("node not found; install Node >= 20 or set HEVI_ANIDOODLE_NODE")


def _node_major(node: str) -> int:
    try:
        raw = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=10
        ).stdout.strip()
        return int(raw.lstrip("v").split(".")[0])
    except Exception as exc:
        raise AnidoodleError(f"cannot run {node}: {exc}") from exc


@dataclass(frozen=True)
class EngineInfo:
    engine: str
    node: str
    node_major: int
    npm_deps: bool
    browser: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "node": self.node,
            "node_major": self.node_major,
            "npm_deps": self.npm_deps,
            "browser": self.browser,
        }


def engine_info() -> EngineInfo:
    engine = engine_dir()
    if not (engine / "tools" / "still.mjs").is_file():
        raise AnidoodleError(f"anidoodle engine not found at {engine}")
    node = node_binary()
    major = _node_major(node)
    if major < 20:
        raise AnidoodleError(f"anidoodle needs Node >= 20, found {major}")
    deps = (engine / "node_modules" / "esbuild").is_dir() and (
        engine / "node_modules" / "playwright-core"
    ).is_dir()
    browser = "not probed"
    if deps:
        report = node_eval(
            "import('./tools/detect.mjs').then(m => console.log(JSON.stringify(m.detect().report)))",
            cwd=engine,
            timeout=120,
        )
        browser = str(report.get("browser", "unknown"))
    return EngineInfo(str(engine), node, major, deps, browser)


def _env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("ANIDOODLE_THREADS", "4")
    env.pop("NODE_OPTIONS", None)
    if extra:
        env.update(extra)
    return env


def run_node(
    args: Iterable[str],
    *,
    cwd: Path | None = None,
    timeout: int = 900,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a Node tool and return the completed process.

    Tools print a human-readable verdict; callers parse the lines they need.
    A non-zero exit is returned to the caller (gates legitimately fail), so this
    helper only raises when the process cannot start or times out.
    """

    node = node_binary()
    command = [node, *args]
    try:
        return subprocess.run(
            command,
            cwd=str(cwd or engine_dir()),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_env(env),
        )
    except subprocess.TimeoutExpired as exc:
        raise AnidoodleError(f"node timed out after {timeout}s: {' '.join(command)}") from exc


def node_eval(script: str, *, cwd: Path | None = None, timeout: int = 120) -> Any:
    result = run_node(["--input-type=module", "-e", script], cwd=cwd, timeout=timeout)
    if result.returncode != 0:
        raise AnidoodleError((result.stderr or result.stdout)[-1200:])
    text = (result.stdout or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AnidoodleError(f"node returned non-JSON: {text[:400]}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def engine_version() -> str:
    package = engine_dir() / "package.json"
    try:
        return str(json.loads(package.read_text(encoding="utf-8")).get("version", "0"))
    except Exception:
        return "0"


def timed(label: str, fn: Any) -> tuple[Any, float]:
    started = time.monotonic()
    value = fn()
    return value, round(time.monotonic() - started, 2)


def film_meta(film: str, *, timeout: int = 120) -> dict[str, Any]:
    """Read a film's ``meta`` without launching a browser.

    The engine's tools resolve films from the working directory, so this bundles
    ``src/canvas-core/<film>.ts`` in memory exactly as the still/render tools do.
    """

    engine = engine_dir()
    script = f"""
import {{ build }} from "esbuild";
const r = await build({{ entryPoints: ["src/canvas-core/{film}.ts"], bundle: true, write: false, format: "esm", platform: "neutral", target: "es2022", logLevel: "error" }});
const url = "data:text/javascript;base64," + Buffer.from(r.outputFiles[0].text).toString("base64");
const m = await import(url);
const f = Object.values(m).find((x) => x && x.meta);
console.log(JSON.stringify(f ? f.meta : {{}}));
"""
    meta = node_eval(script, cwd=engine, timeout=timeout)
    if not isinstance(meta, dict) or not meta.get("durationFrames"):
        raise AnidoodleError(f"film {film} has no readable meta")
    return meta
