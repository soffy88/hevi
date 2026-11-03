"""Two-image alignment gate (``qa.two_image_alignment_gate``).

Clean-room rewrite of the *method* in ``hevi-vs-rain-before-stops.md``
item B3 (from the ``<雨停之前>`` field notes): a hard change was
split into a before picture and an after picture, and the two
pictures had to agree on the key structure -- in the field case,
the window frame and the number of window panes. When they did
not agree, generation drifted. This gate judges that agreement
before money is spent.

Inputs are caller-supplied annotations plus the two picture
files: for each picture, a list of named structure points
(``id``, ``x``, ``y`` in that picture's own pixel coordinates)
and a count of the repeated structure (``window_panes`` in the
field case, named generically ``repeated_count`` here so the
gate is not tied to one prop). The gate itself measures:

1. Both pictures open and have the same pixel size; a size
   mismatch fails, because pixel displacements across different
   sizes are not comparable.
2. Every point id declared on one side is present on the other;
   a missing id fails and is named.
3. The displacement of each corresponding point (Euclidean
   distance in pixels) is at most the caller-supplied
   ``tolerance_px``. The tolerance has no default: no
   author-reported number is used, and a missing or
   non-positive tolerance raises instead of passing.
4. The repeated-structure counts agree; a mismatch fails.

As pixel evidence, the gate also records the mean absolute
pixel difference over the declared frame region (or the whole
picture when no region is declared). That measurement is
evidence only: it never passes or fails the gate on its own,
because a legitimate lighting or colour change moves pixels
without moving structure.

This gate does not see pictures the way a person does: the
structure points are caller-supplied annotations, and a caller
who annotates a point that is not on the structure has lied to
the gate. What it does catch, mechanically, is the record-level
disagreement between the two annotated pictures -- a moved
frame, a lost pane -- before generation. It calls no model,
holds no key, and touches no budget. No price and no Seedance
route is involved.
"""

from __future__ import annotations

import json
import math
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


def _fail(message: str) -> CapabilityError:
    return CapabilityError(f"qa.two_image_alignment_gate: {message}")


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "detail": detail}
    issue.update(extra)
    return issue


def _load_image(path: Any, side: str) -> Any:
    if not isinstance(path, (str, Path)) or not str(path).strip():
        raise _fail(f"{side} image_path must be a non-empty path string")
    file_path = Path(str(path))
    if not file_path.is_file():
        raise _fail(f"{side} image not found: {file_path}")
    try:
        from PIL import Image
    except Exception as exc:
        raise _fail(f"Pillow is required to read pictures: {exc}") from exc
    try:
        image = Image.open(file_path)
        image.load()
    except Exception as exc:
        raise _fail(f"{side} image could not be opened: {exc}") from exc
    return image.convert("RGB")


def _parse_points(record: Any, side: str, size: tuple[int, int]) -> dict[str, tuple[float, float]]:
    if not isinstance(record, dict):
        raise _fail(f"{side} record must be a JSON object")
    points = record.get("structures")
    if not isinstance(points, list) or not points:
        raise _fail(f"{side} record must declare a non-empty 'structures' list")
    out: dict[str, tuple[float, float]] = {}
    width, height = size
    for entry in points:
        if not isinstance(entry, dict):
            raise _fail(f"{side} structure entries must be JSON objects")
        point_id = entry.get("id")
        if not isinstance(point_id, str) or not point_id.strip():
            raise _fail(f"{side} structure entries must name an 'id'")
        point_id = point_id.strip()
        if point_id in out:
            raise _fail(f"{side} structure id {point_id!r} is declared twice")
        x, y = entry.get("x"), entry.get("y")
        if not isinstance(x, (int, float)) or isinstance(x, bool):
            raise _fail(f"{side} structure {point_id!r} 'x' must be a number")
        if not isinstance(y, (int, float)) or isinstance(y, bool):
            raise _fail(f"{side} structure {point_id!r} 'y' must be a number")
        if not (0 <= float(x) < width and 0 <= float(y) < height):
            raise _fail(
                f"{side} structure {point_id!r} ({x}, {y}) lies outside "
                f"the picture ({width}x{height})"
            )
        out[point_id] = (float(x), float(y))
    return out


def _parse_count(record: Any, side: str) -> int:
    count = record.get("repeated_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise _fail(
            f"{side} record must declare 'repeated_count' as a non-negative integer"
        )
    return count


def _parse_region(record: Any, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    region = record.get("frame_region")
    if region is None:
        return None
    if not isinstance(region, dict):
        raise _fail("frame_region must be a JSON object when supplied")
    width, height = size
    try:
        x = int(region["x"])
        y = int(region["y"])
        w = int(region["w"])
        h = int(region["h"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _fail("frame_region needs integer x, y, w, h") from exc
    if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise _fail(
            f"frame_region {(x, y, w, h)} lies outside the picture ({width}x{height})"
        )
    return (x, y, w, h)


def _mean_pixel_difference(
    before: Any, after: Any, region: tuple[int, int, int, int] | None
) -> float:
    try:
        import numpy as np
    except Exception as exc:
        raise _fail(f"numpy is required for the pixel-difference measurement: {exc}") from exc
    box = region if region is not None else (0, 0, before.width, before.height)
    x, y, w, h = box
    a = np.asarray(before.crop((x, y, x + w, y + h)), dtype=np.float32)
    b = np.asarray(after.crop((x, y, x + w, y + h)), dtype=np.float32)
    return float(np.mean(np.abs(a - b)))


def check_two_image_alignment(
    before: Any, after: Any, *, tolerance_px: Any
) -> dict[str, Any]:
    """Judge two annotated pictures for structure alignment.

    Returns a report with verdict ``pass`` / ``fail``; never raises
    for a well-formed pair that disagrees (only malformed input
    raises). ``tolerance_px`` is caller-supplied and required.
    """
    if not isinstance(tolerance_px, (int, float)) or isinstance(tolerance_px, bool):
        raise _fail("tolerance_px must be a number supplied by the caller")
    if float(tolerance_px) <= 0:
        raise _fail("tolerance_px must be positive; no default tolerance is assumed")
    tolerance = float(tolerance_px)

    before_image = _load_image(
        before.get("image_path") if isinstance(before, dict) else None, "before"
    )
    after_image = _load_image(
        after.get("image_path") if isinstance(after, dict) else None, "after"
    )
    issues: list[dict[str, Any]] = []
    displacements: dict[str, float] = {}
    before_points: dict[str, tuple[float, float]] = {}
    after_points: dict[str, tuple[float, float]] = {}
    before_count = after_count = None
    region = None
    mean_diff: float | None = None

    if before_image.size != after_image.size:
        issues.append(
            _issue(
                "size_mismatch",
                f"pictures differ in size: before {before_image.size}, "
                f"after {after_image.size}; pixel displacements are not "
                "comparable across sizes",
                before_size=list(before_image.size),
                after_size=list(after_image.size),
            )
        )
    else:
        before_points = _parse_points(before, "before", before_image.size)
        after_points = _parse_points(after, "after", after_image.size)
        before_count = _parse_count(before, "before")
        after_count = _parse_count(after, "after")
        region = _parse_region(before, before_image.size)
        after_region = _parse_region(after, after_image.size)
        if region is not None and after_region is not None and region != after_region:
            issues.append(
                _issue(
                    "frame_region_mismatch",
                    "the two records declare different frame_region values; "
                    "the pixel-difference region must be the same region",
                    before_region=list(region),
                    after_region=list(after_region),
                )
            )
        effective_region = region if region is not None else after_region
        mean_diff = _mean_pixel_difference(before_image, after_image, effective_region)
        for point_id in sorted(set(before_points) | set(after_points)):
            if point_id not in before_points:
                issues.append(
                    _issue(
                        "point_missing_before",
                        f"structure point {point_id!r} is declared on the "
                        "after picture but missing on the before picture",
                        point_id=point_id,
                    )
                )
            elif point_id not in after_points:
                issues.append(
                    _issue(
                        "point_missing_after",
                        f"structure point {point_id!r} is declared on the "
                        "before picture but missing on the after picture",
                        point_id=point_id,
                    )
                )
            else:
                bx, by = before_points[point_id]
                ax, ay = after_points[point_id]
                displacement = math.hypot(ax - bx, ay - by)
                displacements[point_id] = displacement
                if displacement > tolerance:
                    issues.append(
                        _issue(
                            "displacement_over_tolerance",
                            f"structure point {point_id!r} moved "
                            f"{displacement:.2f}px, over the caller-supplied "
                            f"tolerance of {tolerance:g}px",
                            point_id=point_id,
                            displacement_px=displacement,
                            tolerance_px=tolerance,
                        )
                    )
        if before_count != after_count:
            issues.append(
                _issue(
                    "repeated_count_mismatch",
                    f"repeated-structure count differs: before "
                    f"{before_count}, after {after_count}; the field case "
                    "is a window-pane count that must not change "
                    "between the two pictures",
                    before_count=before_count,
                    after_count=after_count,
                )
            )

    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "before_size": list(before_image.size),
        "after_size": list(after_image.size),
        "tolerance_px": tolerance,
        "displacements_px": displacements,
        "max_displacement_px": max(displacements.values()) if displacements else None,
        "repeated_count": {"before": before_count, "after": after_count},
        "mean_pixel_difference": mean_diff,
        "pixel_difference_note": (
            "Mean absolute pixel difference over the declared frame "
            "region (or the whole picture). Evidence only; it never "
            "passes or fails this gate."
        ),
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_two_image_alignment(
        params.get("before"),
        params.get("after"),
        tolerance_px=params.get("tolerance_px"),
    )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "two_image_alignment.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "ok": report["ok"],
        },
    )


def register_two_image_alignment_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.two_image_alignment_gate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "before": {"type": "object"},
                    "after": {"type": "object"},
                    "tolerance_px": {"type": "number"},
                },
                "required": ["before", "after", "tolerance_px"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Two-image alignment gate (rain-before-stops B3, "
                "clean-room): judges whether two annotated pictures "
                "agree on named structure points within a "
                "caller-supplied pixel tolerance and on the "
                "repeated-structure count, with a pixel-difference "
                "measurement recorded as evidence only. See "
                "RAIN_BEFORE_STOPS_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.two_image_alignment_gate"]


register_two_image_alignment_gate_capabilities_once()
