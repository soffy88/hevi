"""Lemo-opuscar style catalogue (``image.lemo_styles``).

Method intake from lemomo-ai/lemo-opuscar (MIT, attribution in
``OPUS5_COLLECTION_ATTRIBUTION.md``). The checkout is read live on
every render -- like ``video.hyperframes_styles`` reads the
creator-style-kit checkout -- so the catalogue never goes stale and
no upstream text is vendored into hevi: only each style's slug,
bilingual name, category, generic use cases and the one-paragraph
essence blockquote from its STYLE.md are surfaced. Demo stories,
shots, timings and demo assets are deliberately NOT surfaced (the
demo docs themselves say not to reuse their story, arc, shots,
props or timings).

Dedupe against hevi's existing style registries, checked
2026-10-28: handraw styles live under FA-xxx codes (a disjoint
namespace, no slug collision); the creator-style-kit catalogue
shares exactly three slugs -- blueprint, dark-keynote, ink-wash.
Those three are flagged ``hevi_overlap: video.hyperframes_styles``
and are NOT registered as new lemo style ids; every other lemo slug
is new to hevi. The catalogue capability itself is a single entry
(``image.lemo_styles``), the same shape as ``image.handraw_styles``,
so a shared slug can never become a duplicate capability.

``build_code_prompt`` assembles a code-animation brief from the
style essence plus the caller's own brief slots. It does not copy
the full STYLE.md, does not generate an image, and does not touch
the demo film.

Failure contract: a missing lemo checkout, a missing style.json or
STYLE.md for a slug, or an unknown slug all raise CapabilityError
instead of returning a guessed style. Set HEVI_LEMO_HOME to point at
a lemo-opuscar checkout; the default is ~/projects/_refs/lemo-opuscar.
"""

from __future__ import annotations

import json
import os
import re
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
_CSK_OVERLAP = {"blueprint", "dark-keynote", "ink-wash"}


def _lemo_home() -> Path:
    home = os.environ.get("HEVI_LEMO_HOME", "~/projects/_refs/lemo-opuscar")
    path = Path(home).expanduser()
    if not (path / "styles").is_dir():
        raise CapabilityError(
            "image.lemo_styles: lemo-opuscar checkout not found at "
            f"{path} (set HEVI_LEMO_HOME); catalogue is read live, never faked"
        )
    return path


def _essence(style_md: str) -> str:
    # STYLE.md opens with "# <Name> -- Style Prompt" then a blockquote
    # essence paragraph. Take only that blockquote, joined, without the
    # ">" markers and without the rest of the document.
    lines = []
    in_quote = False
    for line in style_md.splitlines():
        if line.startswith(">"):
            in_quote = True
            lines.append(line.lstrip("> ").rstrip())
        elif in_quote:
            break
    text = " ".join(x for x in lines if x).strip()
    if not text:
        raise CapabilityError("image.lemo_styles: STYLE.md has no essence blockquote")
    return text


def list_lemo_styles(category: str | None = None, query: str | None = None) -> list[dict[str, Any]]:
    styles_dir = _lemo_home() / "styles"
    out: list[dict[str, Any]] = []
    for d in sorted(styles_dir.iterdir()):
        if not d.is_dir() or d.name.startswith(("_", ".")) or d.name in ("README",):
            continue
        meta_path = d / "style.json"
        md_path = d / "STYLE.md"
        if not meta_path.exists() or not md_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            essence = _essence(md_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise CapabilityError(
                f"image.lemo_styles: unreadable style {d.name}: {exc}"
            ) from exc
        if category is not None and meta.get("category_en") != category and meta.get("category_cn") != category:
            continue
        if query is not None:
            hay = " ".join(str(meta.get(k) or "") for k in ("slug", "en", "cn", "category_en", "category_cn")).lower()
            if query.strip().lower() not in hay and query.strip().lower() not in essence.lower():
                continue
        out.append({
            "slug": meta.get("slug", d.name), "en": meta.get("en"), "cn": meta.get("cn"),
            "category_en": meta.get("category_en"), "category_cn": meta.get("category_cn"),
            "uses": meta.get("uses") or [], "essence": essence,
            "hevi_overlap": "video.hyperframes_styles" if d.name in _CSK_OVERLAP else None,
            "hevi_new": d.name not in _CSK_OVERLAP,
        })
    return out


def get_lemo_style(slug: str) -> dict[str, Any]:
    if not isinstance(slug, str) or not slug.strip():
        raise CapabilityError("image.lemo_styles: slug must be a non-empty string")
    for style in list_lemo_styles():
        if style["slug"] == slug.strip():
            return style
    raise CapabilityError(f"image.lemo_styles: unknown lemo style {slug!r}")


def build_lemo_code_prompt(slug: str, subject: str, duration_sec: float | None = None) -> dict[str, Any]:
    style = get_lemo_style(slug)
    if not isinstance(subject, str) or not subject.strip():
        raise CapabilityError("image.lemo_styles: subject must be a non-empty string")
    if duration_sec is not None and (not isinstance(duration_sec, (int, float)) or duration_sec <= 0):
        raise CapabilityError("image.lemo_styles: duration_sec must be > 0")
    brief = (
        f"Code-animation brief in the {style['en']} ({style['cn']}) style. "
        f"Style essence: {style['essence']} "
        f"Subject (caller-supplied, not from any lemo demo): {subject.strip()}. "
        f"Render as deterministic code (Canvas/Three.js/GSAP), frame = f(time) only. "
        f"Do not reuse any lemo demo story, shot, prop or timing."
    )
    if duration_sec is not None:
        brief += f" Target duration: {duration_sec:g}s."
    return {
        "capability": "image.lemo_styles", "slug": style["slug"],
        "style": style, "subject": subject.strip(),
        "duration_sec": duration_sec, "code_prompt": brief,
        "image_generation": "not_performed_here",
        "note": "Prompt text only; rendering goes through video.code_render or an existing hevi render path.",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    action = params.get("action", "list")
    if action == "list":
        result: dict[str, Any] = {
            "capability": "image.lemo_styles",
            "styles": list_lemo_styles(category=params.get("category"), query=params.get("query")),
        }
        result["style_count"] = len(result["styles"])
        result["new_to_hevi"] = sum(1 for s in result["styles"] if s["hevi_new"])
    elif action == "get":
        result = {"capability": "image.lemo_styles", "style": get_lemo_style(params["slug"])}
    elif action == "code_prompt":
        result = build_lemo_code_prompt(params["slug"], params["subject"], params.get("duration_sec"))
    else:
        raise CapabilityError("image.lemo_styles: action must be 'list', 'get' or 'code_prompt'")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "lemo_styles.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report)},
    )


def register_lemo_styles_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="image.lemo_styles",
        kind="line",
        aspects=["16:9", "9:16", "1:1"],
        params_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string"},
                "category": {"type": "string"},
                "query": {"type": "string"},
                "slug": {"type": "string"},
                "subject": {"type": "string"},
                "duration_sec": {"type": "number"},
            },
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Lemo-opuscar style catalogue (MIT, live-read from the checkout): "
            "59 code-animation styles by slug/category/essence, with the 3 "
            "slugs already in hevi's creator-style-kit flagged, plus a "
            "code-animation brief builder. Prompt text only; no demo story "
            "is reused and no image is generated here."
        ),
        line="image",
    ))
    return ["image.lemo_styles"]


register_lemo_styles_capabilities_once()
