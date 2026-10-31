"""Pre-submit model-install check (``qa.model_install_gate``).

Clean-room rewrite of the install-check discipline from
``raph651/open-source-canvas`` (MIT; see
OPEN_SOURCE_CANVAS_ATTRIBUTION.md). No code, text or configuration
from that repository is copied here. This module complements
``model.model_directory`` (which records that a model is
registered, not that it is verified): it adds the one check the
directory does not have -- before a job is submitted, every file
a model needs must already be visible to the loader that will
read it, or the submission fails naming the file and its target
folder.

The visibility snapshot is supplied by the caller. This module
makes no network call and never fetches ``/object_info`` itself:
a missing snapshot fails outright, because guessing at file
presence would silently downgrade a submission that is about to
fail on the server. Where the snapshot came from is the caller's
business; an undeclared source is a warning, not a failure.

Failure contract: a malformed model record (not a JSON object,
missing model id, malformed install list) or a malformed
snapshot (not a JSON object) raises :class:`CapabilityError`.
Gate failures (missing snapshot, missing loader, missing file)
are reported in the result, never raised. Verdicts are ``pass`` /
``fail`` only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

__all__ = ["check_model_install"]


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _install_entries(model: dict[str, Any]) -> list[dict[str, Any]]:
    model_id = model.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        _fail("model record model_id must be a non-empty string")
    install = model.get("install", [])
    if not isinstance(install, list):
        _fail("model record install must be a list")
    entries: list[dict[str, Any]] = []
    for index, raw in enumerate(install):
        if not isinstance(raw, dict):
            _fail(f"install entry {index} must be a JSON object")
        loader = raw.get("loader")
        folder = raw.get("folder")
        files = raw.get("files")
        if not isinstance(loader, str) or not loader:
            _fail(f"install entry {index} loader must be a non-empty string")
        if not isinstance(folder, str) or not folder:
            _fail(f"install entry {index} folder must be a non-empty string")
        if not isinstance(files, list) or not files:
            _fail(f"install entry {index} files must be a non-empty list")
        for name in files:
            if not isinstance(name, str) or not name:
                _fail(f"install entry {index} file names must be non-empty strings")
        entries.append(
            {
                "loader": loader,
                "field": raw.get("field"),
                "folder": folder,
                "files": list(files),
            }
        )
    return entries


def _snapshot_loaders(snapshot: dict[str, Any]) -> dict[str, list[str]]:
    """Normalise a caller-supplied visibility snapshot.

    Accepted shapes: ``{loader: [file, ...]}`` or
    ``{"loaders": {loader: [file, ...]}}``. Anything else is a
    malformed snapshot.
    """
    raw = snapshot.get("loaders", snapshot)
    if not isinstance(raw, dict):
        _fail("model-install snapshot loaders must be an object")
    loaders: dict[str, list[str]] = {}
    for loader, visible in raw.items():
        if not isinstance(visible, list) or any(
            not isinstance(name, str) for name in visible
        ):
            _fail(f"snapshot visible files for loader {loader!r} must be strings")
        loaders[str(loader)] = list(visible)
    return loaders


def check_model_install(model: Any, snapshot: Any) -> dict[str, Any]:
    """Judge whether every required file is visible to its loader.

    ``model`` is ``{"model_id", "install": [{"loader", "field",
    "folder", "files": [...]}, ...]}``. ``snapshot`` is the
    caller-supplied loader-visibility snapshot described in
    :func:`_snapshot_loaders`; ``None`` means no snapshot was
    supplied and fails without guessing.
    """
    if not isinstance(model, dict):
        _fail("model record must be a JSON object")
    entries = _install_entries(model)
    failures: list[dict[str, str]] = []
    warnings: list[str] = []
    missing: list[dict[str, str]] = []

    if snapshot is None:
        failures.append(
            {
                "code": "snapshot_missing",
                "message": (
                    "no loader-visibility snapshot supplied; file "
                    "presence is never guessed, submission must wait "
                    "for a real snapshot"
                ),
            }
        )
        return {
            "verdict": "fail",
            "model_id": model.get("model_id"),
            "checked_files": 0,
            "missing": missing,
            "failures": failures,
            "warnings": warnings,
        }
    if not isinstance(snapshot, dict):
        _fail("model-install snapshot must be a JSON object")

    loaders = _snapshot_loaders(snapshot)
    if "source" not in snapshot and "loaders" not in snapshot:
        warnings.append("snapshot source is undeclared")
    elif isinstance(snapshot.get("source"), str) and not snapshot["source"]:
        warnings.append("snapshot source is undeclared")

    checked = 0
    for entry in entries:
        visible = loaders.get(entry["loader"])
        if visible is None:
            for name in entry["files"]:
                checked += 1
                missing.append(
                    {
                        "loader": entry["loader"],
                        "field": str(entry["field"]),
                        "folder": entry["folder"],
                        "file": name,
                    }
                )
                failures.append(
                    {
                        "code": "loader_not_in_snapshot",
                        "message": (
                            f"loader {entry['loader']!r} is absent from "
                            f"the snapshot; required file {name!r} in "
                            f"folder {entry['folder']!r} cannot be "
                            "confirmed present"
                        ),
                    }
                )
            continue
        visible_set = set(visible)
        for name in entry["files"]:
            checked += 1
            if name not in visible_set:
                missing.append(
                    {
                        "loader": entry["loader"],
                        "field": str(entry["field"]),
                        "folder": entry["folder"],
                        "file": name,
                    }
                )
                failures.append(
                    {
                        "code": "model_file_missing",
                        "message": (
                            f"required file {name!r} is not visible to "
                            f"loader {entry['loader']!r}; target folder "
                            f"{entry['folder']!r}"
                        ),
                    }
                )

    return {
        "verdict": "fail" if failures else "pass",
        "model_id": model.get("model_id"),
        "checked_files": checked,
        "missing": missing,
        "failures": failures,
        "warnings": warnings,
    }


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "model": {"type": "object"},
        "snapshot": {"type": "object"},
    },
    "required": ["model"],
    "additionalProperties": False,
}


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_model_install(params["model"], params.get("snapshot"))
    report_path = out_dir / "model_install_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "pass": report["verdict"] == "pass",
            "failures": report["failures"],
            "missing": report["missing"],
        },
    )


def register_model_install_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.model_install_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Pre-submit model-install check: every file a model "
                "needs must be visible to its loader in a "
                "caller-supplied snapshot, or the submission fails "
                "naming the file and target folder. No snapshot is "
                "ever guessed; no network call is made."
            ),
            line="qa",
        )
    )
    return ["qa.model_install_gate"]


register_model_install_capabilities_once()
