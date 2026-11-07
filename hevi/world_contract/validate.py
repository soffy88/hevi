"""Validator for spatial world contracts and world manifests.

Inputs
------
* a *contract* JSON (see ``docs/rules/world_contract.md`` / ``schema.json``);
* a *manifest* JSON in which every zone builder declares the objects it
  placed: name, zone, category, position [x, y, z] in metres, height
  (vertical extent in metres) and a mandatory ``source`` provenance record.

Checks (rule names are stable strings used in reports and tests)
----------------------------------------------------------------
Contract level:
* ``contract_fields``   — required top-level blocks present; units == "m";
  ground provider kind is one of formula|grid|external; time convention is
  ``shot_local``.
* ``lighting_fields``   — lighting timeline present, >= 2 keyframes, every
  keyframe carries t / sun_azimuth_deg / sun_elevation_deg / night_factor,
  night_factor within 0..1, keyframe t non-decreasing.  All effects read
  this one timeline; a contract without it is invalid, full stop.
* ``anchor_in_bounds``  — every published anchor lies inside world bounds.
* ``formula_wellformed``— every interface formula is evaluable (>= 2 points
  with strictly increasing x for piecewise_linear, non-empty coeffs for
  polynomial) and declares a positive tolerance.

Manifest level:
* ``zone_exists``       — the object's zone is declared in the contract.
* ``provenance``        — the object's position is traceable to the contract
  (see ``_check_provenance`` for the exact decision rules).  Free-floating
  hand-written coordinates are rejected.
* ``zone_rule_no_place``— no object of a banned category inside a no_place
  region.
* ``zone_rule_max_height`` — object top (position.y + height) does not
  exceed the limit inside a max_height region.
* ``formula_interface`` — for each declared interface sample, both sides'
  stated values agree with the contract formula at that point within the
  formula tolerance.

The result is a plain dict: ``{"pass": bool, "violations": [...],
"checked": {...}}`` where each violation is
``{"rule": str, "object": str, "reason": str}``.
"""

from __future__ import annotations

from typing import Any

from .model import ContractError, evaluate_formula, point_in_bounds, point_in_region

__all__ = ["validate", "validate_contract", "validate_manifest"]

_POS_TOL = 0.05  # metres; provenance position agreement tolerance
_GROUND_KINDS = ("formula", "grid", "external")
_LIGHTING_FIELDS = ("t", "sun_azimuth_deg", "sun_elevation_deg", "night_factor")


def _violation(rule: str, obj: str, reason: str) -> dict[str, str]:
    return {"rule": rule, "object": obj, "reason": reason}


def _by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(it.get("id")): it for it in items if isinstance(it, dict)}


# ---------------------------------------------------------------------------
# Contract level
# ---------------------------------------------------------------------------

def validate_contract(contract: dict[str, Any]) -> list[dict[str, str]]:
    v: list[dict[str, str]] = []

    world = contract.get("world")
    if not isinstance(world, dict):
        return [_violation("contract_fields", "<contract>", "missing 'world' block")]
    if world.get("units") != "m":
        v.append(_violation(
            "contract_fields", "<contract>",
            f"world.units must be 'm', got {world.get('units')!r}"))
    bounds = world.get("bounds")
    if not isinstance(bounds, dict) or not all(
        k in bounds for k in ("x_min", "x_max", "z_min", "z_max")
    ):
        v.append(_violation(
            "contract_fields", "<contract>",
            "world.bounds must define x_min/x_max/z_min/z_max"))
        bounds = None

    ground = contract.get("ground")
    if not isinstance(ground, dict) or ground.get("kind") not in _GROUND_KINDS:
        v.append(_violation(
            "contract_fields", "<contract>",
            "ground.kind must be one of formula|grid|external "
            "(the single agreed groundAt data source)"))

    time_block = contract.get("time")
    if not isinstance(time_block, dict) or time_block.get("convention") != "shot_local":
        v.append(_violation(
            "contract_fields", "<contract>",
            "time.convention must be 'shot_local' (action time is relative "
            "to the shot, never to the whole film)"))

    # Lighting: one global timeline, all fields mandatory.
    lighting = contract.get("lighting")
    timeline = lighting.get("timeline") if isinstance(lighting, dict) else None
    if not isinstance(timeline, list) or len(timeline) < 2:
        v.append(_violation(
            "lighting_fields", "<contract>",
            "lighting.timeline must contain at least 2 keyframes"))
    else:
        prev_t = None
        for i, kf in enumerate(timeline):
            name = f"lighting.timeline[{i}]"
            if not isinstance(kf, dict):
                v.append(_violation("lighting_fields", name, "keyframe must be an object"))
                continue
            missing = [f for f in _LIGHTING_FIELDS if f not in kf]
            if missing:
                v.append(_violation(
                    "lighting_fields", name,
                    f"missing required field(s): {', '.join(missing)}"))
                continue
            nf = float(kf["night_factor"])
            if not 0.0 <= nf <= 1.0:
                v.append(_violation(
                    "lighting_fields", name,
                    f"night_factor must be within 0..1, got {nf}"))
            t = float(kf["t"])
            if prev_t is not None and t < prev_t:
                v.append(_violation(
                    "lighting_fields", name,
                    f"keyframe t must be non-decreasing ({t} < {prev_t})"))
            prev_t = t

    # Anchors must be publishable: inside the world.
    if bounds is not None:
        for anchor in contract.get("anchors") or []:
            pos = anchor.get("position") or []
            if len(pos) != 3:
                v.append(_violation(
                    "anchor_in_bounds", str(anchor.get("id")),
                    "anchor position must be [x, y, z]"))
                continue
            if not point_in_bounds(float(pos[0]), float(pos[2]), bounds):
                v.append(_violation(
                    "anchor_in_bounds", str(anchor.get("id")),
                    f"anchor at x={pos[0]}, z={pos[2]} is outside world bounds "
                    f"x[{bounds['x_min']}, {bounds['x_max']}] "
                    f"z[{bounds['z_min']}, {bounds['z_max']}]"))

    # Interface formulas must be evaluable and carry a tolerance.
    for formula in contract.get("formulas") or []:
        fid = str(formula.get("id"))
        tol = formula.get("tolerance")
        if tol is None or float(tol) <= 0:
            v.append(_violation(
                "formula_wellformed", fid,
                "formula must declare a positive tolerance"))
        try:
            evaluate_formula(formula, 0.0)
        except (ContractError, TypeError, ValueError) as exc:
            v.append(_violation("formula_wellformed", fid, str(exc)))
        if formula.get("kind") == "piecewise_linear":
            xs = [float(p[0]) for p in formula.get("points") or []]
            if any(b <= a for a, b in zip(xs, xs[1:])):
                v.append(_violation(
                    "formula_wellformed", fid,
                    "piecewise_linear points must have strictly increasing x"))
    return v


# ---------------------------------------------------------------------------
# Manifest level
# ---------------------------------------------------------------------------

def _check_provenance(
    contract: dict[str, Any], obj: dict[str, Any]
) -> list[dict[str, str]]:
    """Coordinate provenance decision rules (normative; mirrored in the doc).

    Every manifest object must declare ``source`` as one of:

    * ``{"type": "anchor", "ref": <anchor id>}`` — the anchor exists and the
      object position equals the anchor position (within 0.05 m).
    * ``{"type": "landmark", "ref": <landmark id>}`` — the landmark exists
      and the object XZ lies inside the landmark footprint
      (centre +- size/2 on the ground plane).
    * ``{"type": "zone_offset", "ref": <zone id>, "offset": [dx, dz]}`` —
      ref must equal the object's own zone, and the object XZ must equal
      (zone.x_min + dx, zone.z_min + dz) within 0.05 m.  This is the only
      way to place a *new* object: as an offset from a contract zone corner,
      never as raw world coordinates.
    * ``{"type": "formula", "ref": <formula id>}`` — the formula exists and
      the object declares ``formula_at`` (the independent-variable value it
      was placed by); the position itself must still be in world bounds.
    * ``{"type": "contract_range"}`` — position inside world bounds; only
      for minor props whose exact placement the contract deliberately
      leaves free within the world.

    Anything else (missing source, unknown type, dangling ref, or a
    position that does not match the cited source) is a violation.
    """
    name = str(obj.get("name"))
    pos = obj.get("position") or []
    if len(pos) != 3:
        return [_violation("provenance", name, "position must be [x, y, z]")]
    x, _y, z = float(pos[0]), float(pos[1]), float(pos[2])
    src = obj.get("source")
    if not isinstance(src, dict) or "type" not in src:
        return [_violation(
            "provenance", name,
            "missing source: every position must cite the contract "
            "(anchor | landmark | zone_offset | formula | contract_range)")]
    stype = src.get("type")
    ref = src.get("ref")
    bounds = contract["world"]["bounds"]

    if stype == "anchor":
        anchor = _by_id(contract.get("anchors") or []).get(str(ref))
        if anchor is None:
            return [_violation("provenance", name, f"unknown anchor ref {ref!r}")]
        ap = anchor["position"]
        if max(abs(x - float(ap[0])), abs(z - float(ap[2]))) > _POS_TOL:
            return [_violation(
                "provenance", name,
                f"position ({x}, {z}) does not match anchor {ref!r} "
                f"at ({ap[0]}, {ap[2]})")]
        return []
    if stype == "landmark":
        lm = _by_id(contract.get("landmarks") or []).get(str(ref))
        if lm is None:
            return [_violation("provenance", name, f"unknown landmark ref {ref!r}")]
        cx, cz = float(lm["position"][0]), float(lm["position"][2])
        dx, dz = float(lm["size"][0]) / 2.0, float(lm["size"][2]) / 2.0
        if not (cx - dx <= x <= cx + dx and cz - dz <= z <= cz + dz):
            return [_violation(
                "provenance", name,
                f"position ({x}, {z}) is outside landmark {ref!r} footprint "
                f"x[{cx - dx}, {cx + dx}] z[{cz - dz}, {cz + dz}]")]
        return []
    if stype == "zone_offset":
        if str(ref) != str(obj.get("zone")):
            return [_violation(
                "provenance", name,
                f"zone_offset ref {ref!r} must equal the object's zone "
                f"{obj.get('zone')!r}")]
        zone = _by_id(contract.get("zones") or []).get(str(ref))
        if zone is None:
            return [_violation("provenance", name, f"unknown zone ref {ref!r}")]
        offset = src.get("offset")
        if not isinstance(offset, list) or len(offset) != 2:
            return [_violation(
                "provenance", name, "zone_offset source needs offset [dx, dz]")]
        ex = float(zone["bounds"]["x_min"]) + float(offset[0])
        ez = float(zone["bounds"]["z_min"]) + float(offset[1])
        if max(abs(x - ex), abs(z - ez)) > _POS_TOL:
            return [_violation(
                "provenance", name,
                f"position ({x}, {z}) != zone {ref!r} corner + offset "
                f"({ex}, {ez})")]
        return []
    if stype == "formula":
        formula = _by_id(contract.get("formulas") or []).get(str(ref))
        if formula is None:
            return [_violation("provenance", name, f"unknown formula ref {ref!r}")]
        if "formula_at" not in obj:
            return [_violation(
                "provenance", name,
                "formula-sourced object must declare formula_at")]
        if not point_in_bounds(x, z, bounds):
            return [_violation("provenance", name, "position outside world bounds")]
        return []
    if stype == "contract_range":
        if not point_in_bounds(x, z, bounds):
            return [_violation("provenance", name, "position outside world bounds")]
        return []
    return [_violation("provenance", name, f"unknown source type {stype!r}")]


def validate_manifest(
    contract: dict[str, Any], manifest: dict[str, Any]
) -> list[dict[str, str]]:
    v: list[dict[str, str]] = []
    zones = _by_id(contract.get("zones") or [])
    rules = contract.get("rules") or []
    formulas = _by_id(contract.get("formulas") or [])

    for obj in manifest.get("objects") or []:
        name = str(obj.get("name"))
        zone_id = str(obj.get("zone"))
        if zone_id not in zones:
            v.append(_violation(
                "zone_exists", name,
                f"zone {zone_id!r} is not declared in the contract"))
        v.extend(_check_provenance(contract, obj))

        pos = obj.get("position") or []
        if len(pos) != 3:
            continue
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
        height = float(obj.get("height") or 0.0)
        category = str(obj.get("category"))
        for rule in rules:
            applies = rule.get("applies_to") or ["*"]
            if "*" not in applies and category not in applies:
                continue
            if not point_in_region(x, z, rule.get("region") or {}):
                continue
            if rule.get("kind") == "no_place":
                v.append(_violation(
                    "zone_rule_no_place", name,
                    f"category {category!r} is banned in rule {rule.get('id')!r} "
                    f"region ({rule.get('reason', 'no reason given')})"))
            elif rule.get("kind") == "max_height":
                limit = float(rule.get("max_height"))
                top = y + height
                if top > limit:
                    v.append(_violation(
                        "zone_rule_max_height", name,
                        f"top {top} m exceeds limit {limit} m of rule "
                        f"{rule.get('id')!r}"))

    for sample in manifest.get("interface_samples") or []:
        fid = str(sample.get("formula"))
        formula = formulas.get(fid)
        label = f"interface_sample:{fid}@{sample.get('at')}"
        if formula is None:
            v.append(_violation(
                "formula_interface", label, f"unknown formula {fid!r}"))
            continue
        tol = float(formula.get("tolerance") or 0.0)
        try:
            expected = evaluate_formula(formula, float(sample.get("at")))
        except (ContractError, TypeError, ValueError) as exc:
            v.append(_violation("formula_interface", label, str(exc)))
            continue
        for side in ("side_a_value", "side_b_value"):
            if side not in sample:
                v.append(_violation(
                    "formula_interface", label, f"sample missing {side}"))
                continue
            actual = float(sample[side])
            if abs(actual - expected) > tol:
                v.append(_violation(
                    "formula_interface", label,
                    f"{side}={actual} differs from contract formula value "
                    f"{expected} by {abs(actual - expected):.4f} > tolerance {tol}"))
    return v


def validate(
    contract: dict[str, Any], manifest: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Validate a contract (and optionally a manifest) -> structured result."""
    violations = validate_contract(contract)
    checked = {
        "zones": len(contract.get("zones") or []),
        "landmarks": len(contract.get("landmarks") or []),
        "anchors": len(contract.get("anchors") or []),
        "rules": len(contract.get("rules") or []),
        "formulas": len(contract.get("formulas") or []),
        "objects": 0,
        "interface_samples": 0,
    }
    if manifest is not None:
        # Manifest checks assume the contract's own blocks exist; if the
        # contract is structurally broken, report that alone.
        if not any(vio["rule"] == "contract_fields" for vio in violations):
            violations = violations + validate_manifest(contract, manifest)
        checked["objects"] = len(manifest.get("objects") or [])
        checked["interface_samples"] = len(manifest.get("interface_samples") or [])
    return {"pass": not violations, "violations": violations, "checked": checked}
