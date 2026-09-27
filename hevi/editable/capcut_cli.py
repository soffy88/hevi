"""HEVI P5.2 — CapCut CLI editable backend.

CapCut CLI is a *projection* of the manifest, never an authority. The manifest
describes the project; this module writes it in CapCut's format and reads it
back to prove the round trip.

Safety, because this shells out to a third-party tool on untrusted input:

* **Version pinned.** ``latest`` is not a pin. The expected version is recorded
  and a mismatch is reported, not ignored.
* **No shell.** Every invocation is an argument array with ``shell=False``. A
  filename like ``a;rm -rf /`` is a filename, never a command.
* **Path containment.** Paths are resolved and checked against the output root,
  so ``../../etc/passwd`` is refused before it reaches the tool.
* **No device identifiers.** Nothing that identifies the host or the user is
  written into the emitted project.
* **Temp hygiene.** Scratch files are validated, used and removed, so a partial
  run cannot leave project content behind.

Honest projection limits: CapCut's own track model is coarser than HEVI's eight
semantic layers. That is reported through ``editability`` rather than hidden —
an element CapCut cannot expose for editing is ``FLATTENED_MEDIA``, never
``NATIVE_EDITABLE``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hevi.editable.base import (
    PARAMETRIC_TEXT_KEY,
    BackendProjection,
    EditabilityLevel,
    EditableBackendId,
    EditableProjectBackend,
    EditableProjectManifest,
    ProjectOutcome,
    TrackElement,
    lint_manifest,
    parametric_text_declaration,
)

#: Pinned toolchain. A floating version is not a pin.
EXPECTED_VERSION = "0.26.0"
EXPECTED_REVISION = "c87d61dec9e2"

#: HEVI's eight semantic layers projected onto CapCut's three track types.
LAYER_TO_TRACK: dict[str, str] = {
    "BACKGROUND": "video",
    "SPEAKER": "video",
    "EVIDENCE": "video",
    "OVERLAY": "video",
    "VOICE": "audio",
    "BGM": "audio",
    "SFX": "audio",
    "CAPTIONS": "text",
}

#: Elements whose *content* is baked into a rendered file cannot be re-timed or
#: re-styled in CapCut, so they are honestly reported as flattened.
#:
#: Only baked-in text qualifies. A narration, music or effects clip is an
#: ordinary media file on an audio track: it can be moved, trimmed and replaced
#: like any other asset, and calling it flattened would tell an editor not to
#: look for controls that are in fact right there.
_FLATTENED_ROLES = frozenset({"CAPTION"})

#: Canonical parametric-text field -> the CapCut item key that carries it.
#:
#: This is CapCut's own capability statement, written in the manifest's
#: vocabulary so the two can be compared field for field. A field absent from
#: this map is not written and not hidden: it comes back from
#: :meth:`CapCutCliBackend.text_capability` as unsupported, and the differential
#: reports it. ``text`` is handled separately because it is also the fallback
#: when an element carries no wording of its own.
CAPCUT_TEXT_FIELD_MAP: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "font_size_px": ("fontSize", lambda v: int(v)),
    "color": ("color", str),
    "weight": ("weight", str),
    "align": ("align", str),
    "max_lines": ("maxLines", lambda v: int(v)),
    "x": ("x", lambda v: float(v)),
    "y": ("y", lambda v: float(v)),
    "scale": ("scale", lambda v: float(v)),
    "opacity": ("opacity", lambda v: float(v)),
}


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,80}$")
_TRAVERSAL = ("..", "~", "$", ";", "|", "&", "`", "\n", "\r", "\x00", "<", ">")


class CapCutSecurityError(RuntimeError):
    """A CapCut CLI invocation was refused before it ran."""


def assert_safe_name(name: str) -> str:
    """Validate a project name destined for the CLI (adversarial A20)."""
    if not name or not _SAFE_NAME.match(name):
        raise CapCutSecurityError(f"UNSAFE_FILENAME:{name[:60]!r}")
    lowered = name.lower()
    for marker in _TRAVERSAL:
        if marker in lowered:
            raise CapCutSecurityError(f"UNSAFE_FILENAME:{marker!r} in {name[:40]!r}")
    return name


def assert_contained(path: Path, root: Path) -> Path:
    """Refuse any path outside ``root`` (adversarial A21)."""
    resolved = Path(path).resolve()
    root_resolved = Path(root).resolve()
    if root_resolved not in resolved.parents and resolved != root_resolved:
        raise CapCutSecurityError(f"PATH_ESCAPE:{resolved}")
    return resolved


def scrub_device_identifiers(payload: Any) -> Any:
    """Strip anything that would leak a stable machine or user identity."""
    banned = (
        "device_id", "machine_id", "host_id", "hostname", "username", "user_name",
        "mac_address", "uuid", "install_id", "telemetry_id", "home_path", "abs_path",
    )
    if isinstance(payload, dict):
        cleaned: dict[str, Any] = {}
        for key, value in payload.items():
            if any(marker in str(key).lower() for marker in banned):
                continue
            cleaned[key] = scrub_device_identifiers(value)
        return cleaned
    if isinstance(payload, list):
        return [scrub_device_identifiers(item) for item in payload]
    if isinstance(payload, str):
        home = str(Path.home())
        return payload.replace(home, "~") if home and home != "/" else payload
    return payload


def classify_editability(element: TrackElement) -> EditabilityLevel:
    """Report what CapCut can honestly do with this element.

    A caption whose text is baked into a rendered frame is not editable in
    CapCut, and calling it ``NATIVE_EDITABLE`` would send an editor chasing a
    control that does not exist. Conversely an element whose text is a live
    parameter is not merely a media file either, and calling it native would
    overstate it: it is editable *as parameters*, which is a different promise.
    """
    if element.semantic_role in _FLATTENED_ROLES:
        return EditabilityLevel.FLATTENED_MEDIA
    if parametric_text_declaration(element) is not None:
        return EditabilityLevel.PARAMETRIC_EDITABLE
    if element.layer == "CAPTIONS":
        return EditabilityLevel.PARAMETRIC_EDITABLE
    return EditabilityLevel.NATIVE_EDITABLE


class CapCutCliBackend(EditableProjectBackend):
    """Projects the manifest into a CapCut draft through the pinned CLI."""

    backend_id = EditableBackendId.CAPCUT_CLI
    version = EXPECTED_VERSION
    revision = EXPECTED_REVISION

    def __init__(self, binary: str | None = None) -> None:
        self.binary = binary or os.getenv("CAPCUT_CLI_BIN", "capcut-cli")
        path = shutil.which(self.binary) if self.binary else None
        self.available = path is not None
        self.unavailable_reason = (
            "" if self.available else f"capcut-cli binary not found (looked for {self.binary})"
        )
        self._resolved = path

    def detect(self) -> bool:
        return self.available

    def installed_version(self) -> str:
        if not self._resolved:
            return ""
        try:
            proc = subprocess.run(
                [self._resolved, "-v"], capture_output=True, text=True,
                timeout=30, check=False, shell=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        return (proc.stdout or "").strip().splitlines()[0].strip() if (proc.stdout or "").strip() else ""

    def version_matches_pin(self) -> bool:
        found = self.installed_version()
        return found == EXPECTED_VERSION if found else False

    def _text_item(
        self, element: TrackElement, start: float, duration: float
    ) -> dict[str, Any]:
        """Build one CapCut text item from the manifest's canonical fields.

        Every field this backend can express is written; every field it cannot is
        returned alongside so the projection can report the gap. The previous
        version read three keys and ignored the rest, which meant a colour or an
        alignment set in the manifest simply never reached CapCut and nothing
        downstream could tell.
        """
        properties = element.editable_properties
        item: dict[str, Any] = {
            "text": str(properties.get("text") or element.semantic_role),
            "start": start,
            "duration": duration,
        }
        for canonical, (target, cast) in CAPCUT_TEXT_FIELD_MAP.items():
            value = properties.get(canonical)
            if value in (None, ""):
                continue
            item[target] = cast(value)
        return item

    def text_capability(self, element: TrackElement) -> tuple[list[str], list[str], list[str]]:
        """What this backend can express for one parametric text element.

        Returns ``(expressed, unsupported, undeclared)`` in the manifest's own
        vocabulary, so two backends can be compared field for field.
        """
        declared = parametric_text_declaration(element)
        if declared is None:
            return [], [], []
        asked, undeclared = declared
        # ``text`` is written as the item's own base key rather than through the
        # field map, so it is supported by construction. Leaving it out would make
        # the projection claim the one field it definitely carries is missing.
        expressed = [
            f for f in asked
            if f in CAPCUT_TEXT_FIELD_MAP or f == PARAMETRIC_TEXT_KEY
        ]
        unsupported = [
            f for f in asked
            if f not in CAPCUT_TEXT_FIELD_MAP and f != PARAMETRIC_TEXT_KEY
        ]
        return expressed, unsupported, undeclared

    # ── Spec projection ──
    def build_spec(self, manifest: EditableProjectManifest) -> dict[str, Any]:
        """Project the eight semantic layers onto CapCut's three track types."""
        grouped: dict[str, list[TrackElement]] = {}
        for element in manifest.elements:
            track_type = LAYER_TO_TRACK.get(element.layer)
            # A parametric element with real text is CapCut text, whatever layer
            # it was declared on. Putting it on the video track would drop it --
            # there is no media file to put there -- and the two backends would
            # then disagree about how many layers the cut has. Routing it to the
            # text track keeps the overlay editable instead of quietly losing it.
            if track_type == "video" and not element.source_artifact:
                if parametric_text_declaration(element) is not None:
                    track_type = "text"
                else:
                    # A media element whose file is simply absent has no
                    # representation here. It is recorded by the caller, not
                    # written as an item with an empty path.
                    continue
            if track_type is None:
                continue
            grouped.setdefault(track_type, []).append(element)

        tracks: list[dict[str, Any]] = []
        for track_type in ("video", "audio", "text"):
            elements = grouped.get(track_type, [])
            if not elements:
                continue
            items: list[dict[str, Any]] = []
            for element in elements:
                start = round(element.start_ms / 1000, 3)
                duration = round(element.duration_ms / 1000, 3)
                if track_type == "text":
                    items.append(self._text_item(element, start, duration))
                    continue
                source = element.source_artifact
                # An empty source is a real case, not a malformed one: a
                # parametric element has no media file. The existence check alone
                # does not catch it, because Path("") is the current directory
                # and the current directory always exists -- so an element with no
                # artifact was being emitted as path: "" and rejected downstream
                # by the CLI. It has to be an explicit test.
                if not source:
                    continue
                if not source.startswith("http") and not Path(source).exists():
                    continue
                item: dict[str, Any] = {
                    "path": source,
                    "start": start,
                    "duration": duration,
                }
                if element.semantic_role in _FLATTENED_ROLES and track_type == "video":
                    item["type"] = "photo"
                if element.opacity != 1.0:
                    item["opacity"] = element.opacity
                if "volume" in element.editable_properties:
                    item["volume"] = float(element.editable_properties["volume"])
                if element.transform.get("scale") and track_type == "video":
                    item["scale"] = float(element.transform["scale"])
                items.append(item)
            if items:
                tracks.append({"type": track_type, "items": items})

        spec: dict[str, Any] = {
            "name": manifest.project_id,
            "width": manifest.canvas_width,
            "height": manifest.canvas_height,
            "fps": manifest.fps,
            "tracks": tracks,
        }
        scrubbed = scrub_device_identifiers(spec)
        return scrubbed if isinstance(scrubbed, dict) else spec

    def project(self, manifest: EditableProjectManifest, output_dir: Path) -> BackendProjection:
        projection = BackendProjection(
            backend=self.backend_id.value, version=self.version, revision=self.revision
        )
        if not self.detect():
            projection.outcome = ProjectOutcome.UNAVAILABLE
            projection.reason = self.unavailable_reason
            return projection

        lint = lint_manifest(manifest, project_root=output_dir)
        if lint:
            projection.outcome = ProjectOutcome.LINT_FAILED
            projection.lint_errors = lint
            projection.reason = "MANIFEST_LINT_FAILED"
            return projection

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            project_name = assert_safe_name(manifest.project_id)
        except CapCutSecurityError as exc:
            projection.outcome = ProjectOutcome.FAILED
            projection.reason = str(exc)
            return projection

        scratch = Path(tempfile.mkdtemp(prefix="capcut_cli_"))
        try:
            spec = self.build_spec(manifest)
            spec_path = scratch / "spec.json"
            spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
            assert_contained(spec_path, scratch)

            draft_dir = output_dir / project_name
            assert_contained(draft_dir, output_dir)

            env = {"PATH": os.environ.get("PATH", ""), "HOME": str(scratch)}
            cli = self._resolved or str(self.binary)
            compile_proc = subprocess.run(
                [cli, "compile", str(spec_path),
                 "--out", str(draft_dir), "--quiet"],
                capture_output=True, text=True, timeout=900, check=False,
                shell=False, cwd=str(scratch), env=env,
            )
            if compile_proc.returncode != 0 or not draft_dir.is_dir():
                projection.outcome = ProjectOutcome.FAILED
                projection.reason = (
                    f"CAPCUT_CLI_COMPILE_FAILED:"
                    f"{(compile_proc.stderr or compile_proc.stdout or '')[-200:]}"
                )
                return projection

            # The CLI's own lint is the authority on whether CapCut can open this.
            lint_proc = subprocess.run(
                [cli, "lint", str(draft_dir), "-q"],
                capture_output=True, text=True, timeout=300, check=False,
                shell=False, cwd=str(scratch), env=env,
            )
            if lint_proc.returncode >= 2:
                projection.outcome = ProjectOutcome.LINT_FAILED
                projection.lint_errors = [
                    line for line in (lint_proc.stdout or "").splitlines() if line.strip()
                ][:20]
                projection.reason = f"CAPCUT_CLI_LINT_ERRORS:{lint_proc.returncode}"
                return projection

            info_proc = subprocess.run(
                [cli, "info", str(draft_dir)],
                capture_output=True, text=True, timeout=300, check=False,
                shell=False, cwd=str(scratch), env=env,
            )
            info: dict[str, Any] = {}
            for line in (info_proc.stdout or "").splitlines():
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    info = parsed
                    break

            # The draft itself is the authority on structure; the CLI summary is
            # a convenience, so the counts are read back from the emitted file.
            draft_path = draft_dir / "draft_content.json"
            if draft_path.is_file():
                try:
                    draft = json.loads(draft_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    draft = {}
                if isinstance(draft, dict):
                    info.setdefault("trackCount", len(draft.get("tracks", [])))
                    info.setdefault("materialCount", len(draft.get("materials", [])))
                    info.setdefault("durationUs", draft.get("duration", 0))

            timeline = draft_dir / "draft_content.json"
            projection.project_path = str(draft_dir)
            projection.timeline_path = str(timeline if timeline.is_file() else draft_dir)
            projection.track_count = int(info.get("trackCount", len(spec["tracks"])) or 0)
            projection.material_count = int(info.get("materialCount", 0) or 0)
            projection.duration_ms = manifest.duration_ms
            projection.layer_coverage = sorted({e.layer for e in manifest.elements})
            projection.semantic_roles = sorted({e.semantic_role for e in manifest.elements})
            projection.flattened = sorted(
                e.element_id
                for e in manifest.elements
                if classify_editability(e) is EditabilityLevel.FLATTENED_MEDIA
            )
            self._record_text_capability(projection, manifest, spec)
            return projection
        finally:
            # Scratch never outlives the call: a partial run must not leave
            # project content in a temp directory.
            shutil.rmtree(scratch, ignore_errors=True)

    def _record_text_capability(
        self, projection: BackendProjection, manifest: EditableProjectManifest, spec: dict[str, Any]
    ) -> None:
        """Fold this backend's text capability into the projection.

        The expressed set is read back from the spec this backend actually wrote,
        not echoed from the manifest, so a projection cannot claim a field the
        draft does not contain.
        """
        written = {
            target
            for track in spec.get("tracks", [])
            if isinstance(track, dict) and track.get("type") == "text"
            for item in track.get("items", [])
            for target in item
        }
        expressed: set[str] = set()
        unsupported: set[str] = set()
        undeclared: set[str] = set()
        for element in manifest.elements:
            if parametric_text_declaration(element) is None:
                continue
            ok, missing, unknown = self.text_capability(element)
            for field in ok:
                target = (
                    PARAMETRIC_TEXT_KEY
                    if field == PARAMETRIC_TEXT_KEY
                    else CAPCUT_TEXT_FIELD_MAP[field][0]
                )
                if target in written:
                    expressed.add(field)
                else:
                    unsupported.add(field)
            unsupported.update(missing)
            undeclared.update(unknown)
        projection.expressed_text_fields = sorted(expressed)
        projection.unsupported_text_fields = sorted(unsupported)
        projection.undeclared_text_fields = sorted(undeclared)
        projection.dropped_elements = sorted(
            e.element_id
            for e in manifest.elements
            if not e.source_artifact
            and parametric_text_declaration(e) is None
            and LAYER_TO_TRACK.get(e.layer) is not None
        )


__all__ = [
    "EXPECTED_REVISION",
    "EXPECTED_VERSION",
    "LAYER_TO_TRACK",
    "CapCutCliBackend",
    "CapCutSecurityError",
    "assert_contained",
    "assert_safe_name",
    "classify_editability",
    "scrub_device_identifiers",
]
