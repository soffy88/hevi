"""Creator Style Kit capabilities (HyperFrames line).

Registers two ``hevi.capabilities`` entries so every product line can pick
and apply one of the 18 creator-style-kit 9:16 styles by dotted name
(CAPABILITY_CONTRACT.md; precedent: ``motion.review``, ``audio.earshot_gate``):

* ``video.hyperframes_styles`` — the live style catalogue (18 styles).  Use to
  list what styles exist, which content type each is best for
  (``best_for``), its essence, palette, motion grammar and hard rules
  (``not``).  The catalogue is regenerated from the kit checkout on every
  render, so it never goes stale; the JSON artifact pins the kit commit.
* ``video.hyperframes_styled_render`` — beats JSON + style id -> a
  deterministic 1080x1920 styled vertical video.  The kit's
  scaffold.py builds the HyperFrames project (fonts subset, skin, CC0 cue
  kit baked in); rendering is seek-based in headless Chromium (see
  ``hevi/video/csk_styled_render.py``).

Source: threeaus/creator-style-kit (MIT).  The kit checkout lives outside the
repo (``HEVI_CSK_HOME``, default ``~/projects/_refs/creator-style-kit``);
fonts that are free for commercial use but not redistributable (MiSans,
优设标题黑) are fetched by the kit's own ``scripts/fetch_fonts.py`` — until
that has run, styles needing them raise ``CapabilityError``.

Sound note: a style's cue kit (Kenney/uisfx, CC0) is baked into the project
by the kit's build step; it is a different resource from
``audio.sfx_render`` (earshot's code-rendered bank) — use the earshot bank
for one-off SFX, the kit cues when a style's whole sound grammar should come
along.  The sound pass is wired in hevi (``hevi/video/csk_styled_render.py``:
collect scaffold cues, peak-align, mux, ffprobe-verify, measure alignment):
the kit's own ``sound_pass.py`` / sound-layer loudness-QA is NOT run and is
not claimed.  A render with ``sound`` enabled (default) that finds no cues
or no cue audio fails instead of delivering a silent MP4; ``sound=false``
delivers a silent draft explicitly labelled pending in ``qa["audio"]``.
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

_STYLE_IDS = [
    "dark-keynote",
    "swiss-grid",
    "editorial-paper",
    "warm-notebook",
    "poster-kinetic",
    "dev-console",
    "data-journal",
    "paper-figure",
    "manim-morph",
    "blueprint",
    "benchmark-hud",
    "particle-field",
    "frosted-aurora",
    "isometric-stack",
    "bauhaus-geometry",
    "ink-wash",
    "clay-serif",
    "instrument-panel",
]


def _csk():
    from hevi.video import csk_styled_render

    return csk_styled_render


def _render_styles_catalogue(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    csk = _csk()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        kit_home = csk.resolve_kit_home()
        specs = csk.load_style_specs(kit_home)
    except Exception as exc:  # noqa: BLE001 - contract wants CapabilityError
        raise CapabilityError(f"video.hyperframes_styles: {exc}") from exc
    if not specs:
        raise CapabilityError("video.hyperframes_styles: no styles found in kit")

    catalogue_path = out_dir / "styles_catalogue.json"
    payload = {
        "source": csk.CSK_SOURCE_URL,
        "license": "MIT (kit code/style configs); fonts OFL-1.1 unless noted; SFX CC0",
        "kit_home": str(kit_home),
        "kit_commit": csk.kit_commit(kit_home),
        "count": len(specs),
        "styles": specs,
    }
    catalogue_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        sha256=compute_sha256(catalogue_path),
        qa={
            "catalogue_json": str(catalogue_path),
            "count": len(specs),
            "style_ids": [s["id"] for s in specs],
            "kit_commit": payload["kit_commit"],
            "note": (
                "Catalogue regenerated from the kit checkout on every render; "
                "pick one main style + at most one accent style per video."
            ),
        },
    )


def _render_styled_render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    csk = _csk()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    style_id = str(params["style_id"])
    content = params["content"]
    fps = int(params.get("fps", 24))
    want_sound = bool(params.get("sound", True))
    capture_mode = str(params.get("capture", "screenshot"))
    if capture_mode not in ("screenshot", "beginframe"):
        raise CapabilityError(
            "video.hyperframes_styled_render: capture must be "
            "screenshot|beginframe"
        )

    # Beats schema gate (qa.beats_schema_gate, landed in 185f90db): fail
    # before scaffolding, naming beat index / type / field, instead of
    # dying inside the kit planner with KeyError: 'head'.
    from hevi.capabilities.beats_schema_gate import check_beats

    gate = check_beats(content)
    if gate["verdict"] == "fail":
        detail = "; ".join(i["message"] for i in gate["issues"])
        raise CapabilityError(
            f"video.hyperframes_styled_render: beats schema fail: {detail}"
        )
    beats_warnings = [w["message"] for w in gate.get("warnings", [])]

    try:
        kit_home = csk.resolve_kit_home()
        known = csk.style_ids(kit_home)
    except Exception as exc:  # noqa: BLE001
        raise CapabilityError(f"video.hyperframes_styled_render: {exc}") from exc
    if style_id not in known:
        raise CapabilityError(
            f"video.hyperframes_styled_render: unknown style '{style_id}'; "
            f"known: {', '.join(known)}"
        )

    project_dir = out_dir / "project"
    mp4_path = out_dir / "styled.mp4"
    try:
        total_s = csk.scaffold_project(kit_home, style_id, content, project_dir)
        csk.render_project_mp4(
            project_dir, mp4_path, fps=fps, duration_s=total_s,
            width=1080, height=1920, sound=want_sound,
            capture_mode=capture_mode,
        )
    except Exception as exc:  # noqa: BLE001 - contract wants CapabilityError
        raise CapabilityError(
            f"video.hyperframes_styled_render failed: {exc}"
        ) from exc
    if not mp4_path.exists():
        raise CapabilityError("video.hyperframes_styled_render: render produced no mp4")

    if want_sound:
        report_path = project_dir / "audio" / "hevi_sound_pass.json"
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - a sounded render must have its report
            raise CapabilityError(
                "video.hyperframes_styled_render: sound pass report missing "
                f"at {report_path}: {exc}"
            ) from exc
        audio_qa: dict[str, Any] = {
            "status": report.get("status"),
            "cue_count": report.get("cue_count"),
            "max_abs_alignment_error_s": report.get("max_abs_alignment_error_s"),
            "max_abs_alignment_error_frames": report.get(
                "max_abs_alignment_error_frames"
            ),
            "kit_sound_pass": report.get("kit_sound_pass"),
            "report_json": str(report_path),
            "mix_wav": report.get("mix_wav"),
        }
    else:
        audio_qa = {
            "status": "pending",
            "reason": (
                "sound pass explicitly disabled by the caller (sound=false); "
                "this silent mp4 is a draft, not a completed sounded delivery"
            ),
            "cue_count": None,
            "report_json": None,
        }

    return CapabilityResult(
        mp4=str(mp4_path),
        duration_s=total_s,
        sha256=compute_sha256(mp4_path),
        qa={
            "style_id": style_id,
            "project_dir": str(project_dir),
            "fps": fps,
            "size": "1080x1920",
            "capture": capture_mode,
            "source": csk.CSK_SOURCE_URL,
            "audio": audio_qa,
            "beats_warnings": beats_warnings,
            "note": (
                "Style cue kit (CC0) baked into the project by the kit build; "
                "sound pass is hevi's ffmpeg cue mix (see hevi/video/"
                "csk_styled_render.py), not the kit's sound_pass.py / "
                "sound-layer QA; sound=false means a silent pending draft."
            ),
        },
    )


def register_csk_capabilities_once() -> None:
    """Register the two creator-style-kit capabilities (idempotent)."""
    global _Registered
    if _Registered:
        return
    register(
        Capability(
            name="video.hyperframes_styles",
            kind="video",
            aspects=["9:16"],
            params_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_styles_catalogue,
            description=(
                "creator-style-kit style catalogue (18 styles): use to pick a "
                "9:16 HyperFrames style by content type (id, Chinese/English "
                "name, best_for, essence, palette, motion grammar, hard rules). "
                "Writes styles_catalogue.json regenerated from the kit checkout."
            ),
            line="hyperframes",
        )
    )
    register(
        Capability(
            name="video.hyperframes_styled_render",
            kind="video",
            aspects=["9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "style_id": {
                        "type": "string",
                        "enum": _STYLE_IDS,
                        "description": "One of the 18 creator-style-kit style ids",
                    },
                    "content": {
                        "type": "object",
                        "description": (
                            "beats JSON: {name, beats: [{type: chapter|list|stat, "
                            "...}], optional source/caption}; <em> marks the single "
                            "emphasised word per beat"
                        ),
                    },
                    "fps": {
                        "type": "number",
                        "minimum": 1,
                        "maximum": 30,
                        "default": 24,
                        "description": "Frame rate for the deterministic render",
                    },
                    "sound": {
                        "type": "boolean",
                        "default": True,
                        "description": (
                            "Run the hevi sound pass (scaffold cues mixed onto "
                            "the picture, audio stream verified). False "
                            "delivers a silent draft labelled pending in qa."
                        ),
                    },
                    "capture": {
                        "type": "string",
                        "enum": ["screenshot", "beginframe"],
                        "default": "screenshot",
                        "description": (
                            "screenshot: poll page.screenshot() until settled. "
                            "beginframe: atomic CDP HeadlessExperimental."
                            "beginFrame capture (see hevi/video/"
                            "beginframe_capture.py)."
                        ),
                    },
                },
                "required": ["style_id", "content"],
                "additionalProperties": False,
            },
            cpu_cost_hint=1.5,
            render=_render_styled_render,
            description=(
                "Apply a creator-style-kit style to a beats list and render a "
                "deterministic 1080x1920 HyperFrames video (fonts/palette/motion/"
                "CC0 cue kit from the style; seek-based Chromium capture; "
                "sound pass mixed and verified by default, sound=false is a "
                "silent pending draft). Beats are schema-checked before "
                "scaffolding. Use video.hyperframes_styles first when the "
                "style is undecided."
            ),
            line="hyperframes",
        )
    )
    _Registered = True
