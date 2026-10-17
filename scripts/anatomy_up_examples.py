#!/usr/bin/env python
"""Rebuild the three vendored Anatomy examples and record regression baselines.

The examples are the upstream figures that pin the vendored kit:

=================================  =====================================
``examples/dial-indicator``        a 2D figure with a live carriage tour
``examples/ripple-tank``           a shader figure (WebGL, CPU fallback)
``examples/turning-dial``          the 3D reference scene (turning groups)
=================================  =====================================

Each one is rebuilt with its own ``build.mjs`` and then shot with the vendored
``capture.mjs``.  A build is *byte-stable* (the page must hash to the recorded
baseline) and a shot is *comparable* (the PNG must hash to the recorded
baseline; ``--reduced`` holds the page's own loop still, so the shot is
deterministic).  Nothing is mocked: a mismatch is a real regression in the
vendored kit or in the kit usage.

Usage
-----
    python scripts/anatomy_up_examples.py                # verify against baselines
    python scripts/anatomy_up_examples.py --update       # re-record the baselines
    python scripts/anatomy_up_examples.py --update --shots-only
    python scripts/anatomy_up_examples.py --only turning-dial

Artifacts land in ``audit/anatomy_up/baselines/`` (pages, shots and the
manifest); the manifest is committed, the generated pages and PNGs are
regenerated on demand.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hevi.capabilities.anatomy_explainer import verify  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ANATOMY = REPO / "third_party" / "anatomy"
EXAMPLES = ANATOMY / "examples"
OUT = REPO / "audit" / "anatomy_up" / "baselines"
MANIFEST = OUT / "examples.json"

#: name -> (page filename, shot width, shot height)
EXAMPLES_RUN: dict[str, dict[str, object]] = {
    "dial-indicator": {"page": "dial-indicator-light.html", "width": 900, "height": 700, "wait": 2500},
    "ripple-tank": {"page": "ripple-tank-light.html", "width": 900, "height": 950, "wait": 2500},
    "turning-dial": {"page": "turning-dial-light.html", "width": 900, "height": 700, "wait": 1500},
}


class ExampleMismatch(RuntimeError):
    """A rebuilt page or shot does not match its recorded baseline."""


@dataclass
class Result:
    name: str
    page: str
    page_sha: str
    shot: str
    shot_sha: str
    page_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "page": self.page,
            "page_bytes": self.page_bytes,
            "page_sha256": self.page_sha,
            "shot": self.shot,
            "shot_sha256": self.shot_sha,
        }

    @classmethod
    def from_dict(cls, name: str, entry: dict[str, object]) -> "Result":
        return cls(
            name=name,
            page=str(entry.get("page", "")),
            page_sha=str(entry.get("page_sha256", entry.get("page_sha", ""))),
            shot=str(entry.get("shot", "")),
            shot_sha=str(entry.get("shot_sha256", entry.get("shot_sha", ""))),
            page_bytes=int(entry.get("page_bytes", 0)),
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(cmd: list[str], *, label: str, timeout: float = 900.0) -> str:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ExampleMismatch(f"{label} timed out: {' '.join(cmd)}") from exc
    out = (res.stdout or "") + (res.stderr or "")
    if res.returncode != 0:
        raise ExampleMismatch(f"{label} failed (exit {res.returncode}):\n{out[-3000:]}")
    return res.stdout


def build(name: str) -> Path:
    """Rebuild ``examples/<name>/build.mjs`` and return the page it wrote."""
    spec = EXAMPLES_RUN[name]
    source = EXAMPLES / name
    before = {path.name: path.stat().st_mtime_ns for path in source.iterdir()}
    run(["node", str(source / "build.mjs"), "--light"], label=f"build {name}", timeout=1200)
    page = source / str(spec["page"])
    if not page.is_file():
        raise ExampleMismatch(f"build {name} wrote no page at {page}")
    if page.name not in before:
        # Keep the vendored tree clean: a page the build wrote where none was
        # committed is still tracked by git, so this is a real change.
        pass
    return page


def shot(name: str, page: Path, out_dir: Path) -> Path:
    """Shoot the page with the vendored capture.mjs, deterministically."""
    spec = EXAMPLES_RUN[name]
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{name}-light.png"
    args = [
        "node",
        str(verify.scripts_dir() / "capture.mjs"),
        str(page),
        "--out",
        str(target),
        "--width",
        str(int(spec["width"])),
        "--height",
        str(int(spec["height"])),
        "--scale",
        "1",
        "--wait",
        str(int(spec["wait"])),
        "--reduced",
    ]
    stdout = run(args, label=f"capture {name}", timeout=600)
    if "saved " not in stdout:
        raise ExampleMismatch(f"capture {name} saved nothing:\n{stdout[-2000:]}")
    return target


def read_manifest() -> dict[str, Result]:
    if not MANIFEST.is_file():
        return {}
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {name: Result.from_dict(name, entry) for name, entry in raw.items()}


def write_manifest(results: dict[str, Result]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps({name: item.as_dict() for name, item in sorted(results.items())}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="re-record the baselines instead of verifying")
    parser.add_argument("--shots-only", action="store_true", help="skip the rebuild, only the shots")
    parser.add_argument("--only", choices=sorted(EXAMPLES_RUN), default=None)
    args = parser.parse_args(argv)

    if not EXAMPLES.is_dir():
        print(f"examples missing: {EXAMPLES}", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    known = read_manifest()
    results: dict[str, Result] = {}
    problems: list[str] = []

    for name in sorted(EXAMPLES_RUN):
        if args.only and name != args.only:
            continue
        if args.shots_only:
            page = EXAMPLES / name / str(EXAMPLES_RUN[name]["page"])
            if not page.is_file():
                problems.append(f"{name}: no built page to shoot ({page})")
                continue
        else:
            page = build(name)
        target = shot(name, page, OUT)
        item = Result(
            name=name,
            page=page.name,
            page_sha=sha256(page),
            shot=target.name,
            shot_sha=sha256(target),
            page_bytes=page.stat().st_size,
        )
        if name in known and not args.update:
            base = known[name]
            if base.page_sha != item.page_sha:
                problems.append(
                    f"{name}: page is not byte-stable\n"
                    f"  baseline {base.page_sha[:16]} ({base.page_bytes} B)\n"
                    f"  rebuilt  {item.page_sha[:16]} ({item.page_bytes} B)"
                )
                continue
            if base.shot_sha != item.shot_sha:
                problems.append(
                    f"{name}: shot is not byte-stable\n"
                    f"  baseline {base.shot_sha[:16]}\n"
                    f"  rebuilt  {item.shot_sha[:16]}"
                )
                continue
            print(f"ok    {name}: page {item.page_sha[:12]} · shot {item.shot_sha[:12]}")
        else:
            print(f"rec   {name}: page {item.page_sha[:12]} ({item.page_bytes} B) · shot {item.shot_sha[:12]}")
        results[name] = item

    if args.update:
        keep = {name: item for name, item in known.items() if name not in results}
        write_manifest({**keep, **results})
        print(f"recorded {len(results)} baseline(s) in {MANIFEST}")
        return 0

    if problems:
        print("\n".join(problems), file=sys.stderr)
        print(f"\nexamples check failed: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"examples check passed: {len(results)} example(s) byte-stable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
