"""Style catalog schema (``video.style_catalog_schema``).

Clean-room rewrite of a *schema* only: a style catalog is an index
of visual styles grouped into families, where every style declares
its family, its fits, its templates, and whether it has been
verified by rendering. The field names and the validation rules
below are this repository's own restatement; no catalog text, no
style description, no still image, and no audio asset from any
outside repository is copied or referenced here. See
VIBE_KNOWLEDGE_ATTRIBUTION.md.

The catalog is an index, never a bundle: asset fields may only
carry external references (a locator string plus
``location: "external"``). Inline media — data URIs, base64 blobs,
embedded binaries — is refused outright.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_REQUIRED_STYLE_FIELDS = ("id", "family", "fit", "templates", "verified")


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _looks_inline(value: Any) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        return lowered.startswith("data:") or len(value) > 4096
    if isinstance(value, (dict, list)):
        return True
    return False


def validate_style_catalog(catalog: Any) -> dict[str, Any]:
    """Validate one style catalog index. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    styles_out: list[dict[str, Any]] = []
    if not isinstance(catalog, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("catalog_not_object", "style catalog must be a JSON object")
            ],
            "styles": [],
            "family_count": 0,
        }
    families = catalog.get("families")
    if not isinstance(families, list) or not families:
        issues.append(
            _issue(
                "families_missing",
                "catalog must declare a non-empty families list",
            )
        )
        families = families if isinstance(families, list) else []
    family_names = set()
    for family in families:
        if not isinstance(family, dict) or not _is_nonempty_str(family.get("name")):
            issues.append(
                _issue(
                    "family_invalid",
                    "each family must be an object with a non-empty name",
                )
            )
            continue
        family_names.add(str(family["name"]).strip())
    styles = catalog.get("styles")
    if not isinstance(styles, list) or not styles:
        issues.append(
            _issue("styles_missing", "catalog must declare a non-empty styles list")
        )
        styles = styles if isinstance(styles, list) else []
    seen_ids: set[str] = set()
    for index, style in enumerate(styles):
        label = f"styles[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(style, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each style must be an object")
            )
            styles_out.append(entry)
            continue
        for field in _REQUIRED_STYLE_FIELDS:
            if field not in style:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:field_missing:{field}",
                        f"style is missing required field {field!r}",
                    )
                )
        style_id = style.get("id")
        if _is_nonempty_str(style_id):
            if style_id in seen_ids:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:id_duplicate",
                        f"style id {style_id!r} appears more than once",
                    )
                )
            seen_ids.add(style_id)
        family = style.get("family")
        if _is_nonempty_str(family) and family not in family_names:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:family_undeclared",
                    f"style family {family!r} is not declared in families",
                )
            )
        fit = style.get("fit")
        if fit is not None and (
            not isinstance(fit, list)
            or not fit
            or not all(_is_nonempty_str(item) for item in fit)
        ):
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:fit_invalid",
                    "fit must be a non-empty list of non-empty strings",
                )
            )
        templates = style.get("templates")
        if templates is not None and (
            not isinstance(templates, list)
            or not all(_is_nonempty_str(item) for item in templates)
        ):
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:templates_invalid",
                    "templates must be a list of non-empty strings",
                )
            )
        if "verified" in style and not isinstance(style["verified"], bool):
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:verified_not_bool",
                    "verified must be a boolean, never a bare claim",
                )
            )
        assets = style.get("assets")
        if assets is not None:
            if not isinstance(assets, dict):
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{label}:assets_invalid",
                        "assets must be an object of external references",
                    )
                )
            else:
                for key, asset in assets.items():
                    if not isinstance(asset, dict):
                        entry["ok"] = False
                        entry["issues"].append(
                            _issue(
                                f"{label}:asset_not_reference:{key}",
                                "each asset must be an external reference object",
                            )
                        )
                        continue
                    if asset.get("location") != "external":
                        entry["ok"] = False
                        entry["issues"].append(
                            _issue(
                                f"{label}:asset_not_external:{key}",
                                "assets may only be external references; "
                                "the catalog never bundles media",
                            )
                        )
                    locator = asset.get("locator")
                    if _looks_inline(locator):
                        entry["ok"] = False
                        entry["issues"].append(
                            _issue(
                                f"{label}:asset_inline:{key}",
                                "asset locators must be reference strings, "
                                "never inline media",
                            )
                        )
                    if not _is_nonempty_str(locator):
                        entry["ok"] = False
                        entry["issues"].append(
                            _issue(
                                f"{label}:asset_locator_missing:{key}",
                                "each asset reference needs a locator",
                            )
                        )
        if entry["issues"]:
            entry["ok"] = False
            issues.extend(entry["issues"])
        styles_out.append(entry)
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "styles": styles_out,
        "family_count": len(family_names),
        "style_count": len(styles_out),
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = validate_style_catalog(params.get("catalog"))
    report_path = out_dir / "style_catalog.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_style_catalog_schema_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.style_catalog_schema",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "catalog": {"type": "object"},
                },
                "required": ["catalog"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Style catalog schema: an index of visual styles in "
                "declared families, each with fits, templates, and a "
                "boolean verified flag; assets are external "
                "references only, never bundled media."
            ),
        )
    )
    return ["video.style_catalog_schema"]


__all__ = [
    "validate_style_catalog",
    "register_style_catalog_schema_capabilities_once",
]
