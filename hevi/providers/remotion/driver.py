"""HEVI P9.1.c — the Remotion driver: execute a render, return a locator.

    input -> execute -> ArtifactLocator

That is the whole contract. This driver does not hash, probe, validate, qualify or
decide. Those belong to P8.2/P8.3/P8.4, and the audit's R1 finding was precisely that
the legacy ``hevi/renderers/remotion.py`` did all five inside one renderer. Rejecting a
composition id and returning a path is not validation, so that stays.

Phase 5 acceptance, as an AST property rather than a promise:

    subprocess / node / npx / filesystem locator   allowed
    hashlib, ffprobe, ValidationResult,
    ProductionReceipt, qualification               refused
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: Default project directory, matching the legacy renderer's resolution order so
#: existing deployments keep working: ``HEVI_REMOTION_PROJECT`` then the repo's
#: ``hevi-remotion/``.
_DEFAULT_PROJECT = Path(__file__).resolve().parents[3] / "hevi-remotion"


@dataclass(frozen=True)
class RenderLocator:
    """Where the render landed. A location, not a proof.

    Nothing here says the file is valid, playable or complete — that is what P8.4 is
    for. ``path`` is a claim; the checksum is computed later from the bytes.
    """

    composition: str
    path: str
    props_path: str = ""

    def exists(self) -> bool:
        return bool(self.path) and Path(self.path).is_file()

    def to_dict(self) -> dict[str, str]:
        return {
            "composition": self.composition,
            "path": self.path,
            "props_path": self.props_path,
        }


class RemotionUnavailable(Exception):
    """The runtime is absent. Not a render failure — a missing environment."""


def project_dir() -> Path:
    return Path(os.getenv("HEVI_REMOTION_PROJECT", str(_DEFAULT_PROJECT)))


def probe_runtime() -> str:
    """Return a reason string when the runtime cannot be used, else ``""``.

    Declared capability, not inference: the project must actually exist with a
    ``package.json`` and installed ``node_modules``, and ``npx`` must be on PATH.
    """
    if shutil.which("npx") is None:
        return "npx_not_found:the node package runner is not on PATH"
    project = project_dir()
    if not project.is_dir():
        return f"project_missing:{project} does not exist"
    if not (project / "package.json").is_file():
        return f"package_json_missing:{project}/package.json not found"
    if not (project / "node_modules").is_dir():
        return f"node_modules_missing:{project}/node_modules not found"
    return ""


def is_available() -> bool:
    return probe_runtime() == ""


def compositions(timeout_s: float = 600.0) -> tuple[tuple[str, ...], str]:
    """Enumerate compositions. Returns ``(names, reason)``; reason is empty on success.

    Parses Remotion's tabular output rather than its JSON, matching the legacy
    implementation's format tolerance.
    """
    reason = probe_runtime()
    if reason:
        return (), reason
    project = project_dir()
    try:
        proc = subprocess.run(
            ["npx", "--no-install", "remotion", "compositions", "src/index.ts"],
            capture_output=True, text=True, timeout=timeout_s, check=False,
            cwd=str(project),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (), f"{type(exc).__name__}:{exc}"
    if proc.returncode != 0:
        return (), f"exit_{proc.returncode}:{(proc.stderr or '')[:200]}"
    names: list[str] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1].isdigit() and "x" in parts[2]:
            names.append(parts[0])
    return tuple(names), ""


def render(
    composition: str,
    output_path: str | Path,
    *,
    props: dict[str, object] | None = None,
    timeout_s: float = 1800.0,
) -> RenderLocator:
    """Render one composition and return where it landed.

    Raises :class:`RemotionUnavailable` when the runtime is absent, and
    ``RuntimeError`` when Remotion itself fails. It does **not** inspect the result:
    no checksum, no ffprobe, no validation.
    """
    reason = probe_runtime()
    if reason:
        raise RemotionUnavailable(reason)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    props_path = ""
    if props:
        import json

        props_path = str(target.with_suffix(".props.json"))
        Path(props_path).write_text(
            json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    command = [
        "npx", "--no-install", "remotion", "render", composition, str(target),
        "--log=error", "--quiet",
    ]
    if props_path:
        command.append(f"--props={props_path}")

    proc = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout_s,
        check=False, cwd=str(project_dir()),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"REMOTION_RENDER_FAILED:{composition}:exit_{proc.returncode}:"
            f"{(proc.stderr or '')[:300]}"
        )
    return RenderLocator(composition=composition, path=str(target), props_path=props_path)


def render_remotion(
    composition: str,
    output_path: str | Path,
    *,
    props: dict[str, object] | None = None,
    timeout_s: float = 1800.0,
) -> RenderLocator:
    """Backwards-compatible entry point.

    The legacy API was ``RemotionRenderer.render(plan, output_dir)``. Callers keep
    working; internally the render now goes through the provider driver, which is the
    point of the migration. No legacy API is removed.
    """
    return render(composition, output_path, props=props, timeout_s=timeout_s)


__all__ = [
    "RemotionUnavailable",
    "RenderLocator",
    "compositions",
    "is_available",
    "probe_runtime",
    "project_dir",
    "render",
    "render_remotion",
]
