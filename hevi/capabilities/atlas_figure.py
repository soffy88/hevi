"""Interactive physics-figure specs (Atlas of Physics idiom, clean rewrite).

Method lineage: an interactive 3D physics textbook draws one figure per
chapter from a single truth model (pure functions, SI units), checks every
number by recomputing it another way, and lets the reader hover (one thing
lights up), click (the thing breaks down into components / slope / area) and
scroll (the camera travels a per-page path).  This module re-implements that
*discipline* for hevi in Python: a declarative ``PhysicsFigureSpec`` is
verified fail-closed, its invariant checks are executed by independent
recomputation, and :func:`generate_scene` emits a deterministic Three.js
scene JSON a host player can consume.  No code, text, question or number is
copied from the reference work; the two bundled reference figures use
self-chosen parameters, and every model formula is stated from the public
physics law it encodes.

Division of labour: :mod:`hevi.creative.layer4.blender_workflow` owns
*offline precision rendering* (deterministic bpy script generation, Blender
binary execution, ffmpeg assembly).  This capability owns *interactive Web
3D scene specifications* (paper/ink figure idiom, breakdowns, scroll-driven
cameras, executable checks).  It produces no pixels: rendering, scroll
driving, picking and label overlay are host-player work, listed as pending
items in ``atlas_figure.md`` next to this module.

Determinism: everything here is pure stdlib.  The check executor never uses
``eval``/``exec``; model expressions run through a whitelisted AST evaluator
(numbers, parameter names, ``+ - * / ** %``, unary minus, and a fixed list of
``math`` functions).  The same spec always yields byte-identical scene JSON.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import CapabilityError
from .registry import Capability, contains, get, register

__all__ = [
    "CAPABILITY_NAME",
    "PALETTE",
    "REFERENCE_PENDULUM",
    "REFERENCE_PROJECTILE",
    "TONES",
    "FigureSpecError",
    "generate_scene",
    "reference_figures",
    "register_atlas_figure_capabilities_once",
    "run_checks",
    "scene_to_json",
    "verify_figure_spec",
]

CAPABILITY_NAME = "physics.atlas_figure"
SCHEMA_VERSION = 1

# Paper/ink material idiom, restated as spec fields: each palette is a
# (top, light, dark) triple of facing tones; each tone is a line/shade weight.
# Values are this module's own; the *idea* (three facing tones + five line
# weights, arrows drawn over solids, one lit thing) is the borrowed method.
PALETTE: dict[str, tuple[str, str, str]] = {
    "paper": ("#fffdf6", "#f3efe4", "#ddd8ca"),
    "base": ("#f7f5ef", "#e9e6db", "#cfccc0"),
    "dark": ("#a3a3ab", "#8b8b93", "#6f6f77"),
    "ink": ("#55555c", "#333338", "#1d1d20"),
    "red": ("#f28b8f", "#e05257", "#b23a3f"),
    "blue": ("#9db8f2", "#6489d8", "#43619f"),
    "board": ("#fffefb", "#f8f7f1", "#edece4"),
}
TONES: dict[str, float] = {"faint": 0.15, "lo": 0.35, "mid": 0.55, "hi": 0.8, "lit": 1.0}

_PART_KINDS = ("paper_solid", "arrow", "axis", "graph", "strobe", "polyline")
_SOLID_SHAPES = ("box", "cylinder", "sphere", "cone")
_BREAKDOWN_KINDS = ("vector_components", "graph_slope_area", "explode", "assembly")
_CHECK_METHODS = ("sample", "closed_form", "integrate", "finite_diff", "root")
_LANGUAGES = ("zh", "en")

_MATH_FUNCS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "hypot": math.hypot,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "abs": abs,
    "min": min,
    "max": max,
}
_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Name,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Load,
)


class FigureSpecError(ValueError):
    """A figure spec failed verification, or a check failed execution."""


@dataclass
class FigureVerification:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class CheckOutcome:
    id: str
    quantity: str
    value_a: float
    value_b: float
    abs_diff: float
    tolerance: float
    passed: bool
    error: str = ""


@dataclass
class CheckReport:
    figure_id: str
    outcomes: list[CheckOutcome] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return bool(self.outcomes) and all(o.passed for o in self.outcomes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "figure_id": self.figure_id,
            "all_passed": self.all_passed,
            "checks": [
                {
                    "id": o.id,
                    "quantity": o.quantity,
                    "value_a": round(o.value_a, 6),
                    "value_b": round(o.value_b, 6),
                    "abs_diff": round(o.abs_diff, 6),
                    "tolerance": o.tolerance,
                    "passed": o.passed,
                    "error": o.error,
                }
                for o in self.outcomes
            ],
        }


# ---------------------------------------------------------------------------
# Safe expression evaluation (whitelisted AST; never eval/exec).
# ---------------------------------------------------------------------------


def _eval_expr(expr: str, env: dict[str, float]) -> float:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise FigureSpecError(f"expression does not parse: {expr!r} ({exc})") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise FigureSpecError(
                f"expression uses a forbidden construct ({type(node).__name__}): {expr!r}"
            )
    return _eval_node(tree.body, env, expr)


def _eval_node(node: ast.AST, env: dict[str, float], expr: str) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and math.isfinite(node.value):
            return float(node.value)
        raise FigureSpecError(f"constant not allowed in expression: {expr!r}")
    if isinstance(node, ast.Name):
        if node.id in env:
            return float(env[node.id])
        raise FigureSpecError(f"unknown name {node.id!r} in expression: {expr!r}")
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, env, expr)
        right = _eval_node(node.right, env, expr)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
        if isinstance(node.op, ast.Mod):
            return left % right
        raise FigureSpecError(f"operator not allowed in expression: {expr!r}")
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand, env, expr)
        if isinstance(node.op, ast.USub):
            return -value
        if isinstance(node.op, ast.UAdd):
            return value
        raise FigureSpecError(f"unary operator not allowed in expression: {expr!r}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _MATH_FUNCS:
            raise FigureSpecError(f"call not allowed in expression: {expr!r}")
        if node.keywords:
            raise FigureSpecError(f"keyword arguments not allowed in expression: {expr!r}")
        args = [_eval_node(a, env, expr) for a in node.args]
        try:
            return float(_MATH_FUNCS[node.func.id](*args))
        except (ValueError, ZeroDivisionError, OverflowError) as exc:
            raise FigureSpecError(f"math error in expression {expr!r}: {exc}") from exc
    raise FigureSpecError(f"expression form not allowed: {expr!r}")


def _base_env(spec: dict[str, Any]) -> dict[str, float]:
    env: dict[str, float] = {"pi": math.pi, "e": math.e}
    for param in spec["model"]["parameters"]:
        env[param["name"]] = float(param["value"])
    return env


def _resolve_bound(value: Any, env: dict[str, float], what: str) -> float:
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise FigureSpecError(f"{what} must be finite, got {value!r}")
        return float(value)
    if isinstance(value, dict) and set(value) == {"expr"}:
        return _eval_expr(str(value["expr"]), env)
    raise FigureSpecError(f"{what} must be a number or {{'expr': ...}}, got {value!r}")


def _is_vec3(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 3
        and all(isinstance(v, (int, float)) and math.isfinite(v) for v in value)
    )


def _is_ident(value: Any) -> bool:
    return isinstance(value, str) and value.isidentifier()


# ---------------------------------------------------------------------------
# Verification gate (fail-closed: every failure is listed, nothing passes
# by default).
# ---------------------------------------------------------------------------


def verify_figure_spec(spec: Any) -> FigureVerification:
    reasons: list[str] = []
    warnings: list[str] = []

    def fail(msg: str) -> None:
        reasons.append(msg)

    if not isinstance(spec, dict):
        return FigureVerification(ok=False, reasons=["spec must be a JSON object"])
    for key in ("id", "title"):
        if not isinstance(spec.get(key), str) or not spec[key].strip():
            fail(f"{key} must be a non-empty string")
    if spec.get("language") not in _LANGUAGES:
        fail(f"language must be one of {_LANGUAGES}")
    prov = spec.get("provenance")
    if not isinstance(prov, dict) or not prov.get("source") or not prov.get("license"):
        fail("provenance must carry non-empty 'source' and 'license' labels")
    caveat = spec.get("model", {}).get("caveat") if isinstance(spec.get("model"), dict) else None
    if not isinstance(caveat, str) or len(caveat.strip()) < 10:
        fail("model.caveat must be a non-empty statement of assumptions (min 10 chars)")

    model = spec.get("model")
    if not isinstance(model, dict):
        fail("model must be an object")
        return FigureVerification(ok=False, reasons=reasons, warnings=warnings)
    quantity_names: set[str] = set()
    env = {"pi": math.pi, "e": math.e}
    params = model.get("parameters")
    if not isinstance(params, list) or not params:
        fail("model.parameters must be a non-empty list")
        params = []
    for i, param in enumerate(params):
        where = f"model.parameters[{i}]"
        if not isinstance(param, dict):
            fail(f"{where} must be an object")
            continue
        name = param.get("name")
        if not _is_ident(name):
            fail(f"{where}.name must be a valid identifier")
            continue
        if name in quantity_names:
            fail(f"duplicate model quantity name: {name!r}")
        quantity_names.add(name)
        if not isinstance(param.get("value"), (int, float)) or not math.isfinite(param["value"]):
            fail(f"{where}.value must be a finite number")
        else:
            env[name] = float(param["value"])
        if not isinstance(param.get("unit"), str) or not param["unit"].strip():
            fail(f"{where}.unit must be a non-empty string")
    derived = model.get("derived", [])
    if not isinstance(derived, list):
        fail("model.derived must be a list")
        derived = []
    for i, item in enumerate(derived):
        where = f"model.derived[{i}]"
        if not isinstance(item, dict):
            fail(f"{where} must be an object")
            continue
        name = item.get("name")
        if not _is_ident(name):
            fail(f"{where}.name must be a valid identifier")
            continue
        if name in quantity_names:
            fail(f"duplicate model quantity name: {name!r}")
        quantity_names.add(name)
        formula = item.get("formula")
        if not isinstance(formula, str) or not formula.strip():
            fail(f"{where}.formula must be a non-empty expression")
            continue
        if not isinstance(item.get("value"), (int, float)) or not math.isfinite(item["value"]):
            fail(f"{where}.value must be a finite number")
            continue
        try:
            recomputed = _eval_expr(formula, env)
        except FigureSpecError as exc:
            fail(f"{where}.formula failed: {exc}")
            continue
        if abs(recomputed - float(item["value"])) > 1e-9 + 1e-9 * abs(recomputed):
            fail(
                f"{where}.value {item['value']!r} does not match formula "
                f"recomputation {recomputed!r}"
            )
        else:
            env[name] = float(item["value"])
        if not isinstance(item.get("unit"), str) or not item["unit"].strip():
            fail(f"{where}.unit must be a non-empty string")
    functions = model.get("functions", [])
    if not isinstance(functions, list):
        fail("model.functions must be a list")
        functions = []
    function_names: set[str] = set()
    for i, fn in enumerate(functions):
        where = f"model.functions[{i}]"
        if not isinstance(fn, dict):
            fail(f"{where} must be an object")
            continue
        name = fn.get("name")
        if not _is_ident(name):
            fail(f"{where}.name must be a valid identifier")
            continue
        if name in quantity_names:
            fail(f"duplicate model quantity name: {name!r}")
        quantity_names.add(name)
        function_names.add(name)
        variables = fn.get("variables", ["t"])
        if (
            not isinstance(variables, list)
            or not variables
            or not all(_is_ident(v) for v in variables)
        ):
            fail(f"{where}.variables must be a non-empty list of identifiers")
            continue
        expr = fn.get("expression")
        if not isinstance(expr, str) or not expr.strip():
            fail(f"{where}.expression must be a non-empty expression")
            continue
        trial = dict(env)
        for var in variables:
            trial[var] = 0.0
        try:
            _eval_expr(expr, trial)
            trial[variables[0]] = 1.0
            _eval_expr(expr, trial)
        except FigureSpecError as exc:
            fail(f"{where}.expression failed: {exc}")
        if not isinstance(fn.get("unit"), str) or not fn["unit"].strip():
            fail(f"{where}.unit must be a non-empty string")

    def _check_quantity_ref(name: Any, where: str) -> None:
        if not isinstance(name, str) or name not in quantity_names:
            fail(f"{where} references undeclared model quantity {name!r}")

    scene = spec.get("scene")
    if not isinstance(scene, dict):
        fail("scene must be an object")
        return FigureVerification(ok=False, reasons=reasons, warnings=warnings)
    assemblies = scene.get("assemblies")
    assembly_ids: set[str] = set()
    if not isinstance(assemblies, list) or not assemblies:
        fail("scene.assemblies must be a non-empty list")
        assemblies = []
    for i, asm in enumerate(assemblies):
        where = f"scene.assemblies[{i}]"
        if not isinstance(asm, dict):
            fail(f"{where} must be an object")
            continue
        asm_id = asm.get("id")
        if not isinstance(asm_id, str) or not asm_id.strip():
            fail(f"{where}.id must be a non-empty string")
            continue
        if asm_id in assembly_ids:
            fail(f"duplicate assembly id: {asm_id!r}")
        assembly_ids.add(asm_id)
        if not isinstance(asm.get("title"), str) or not asm["title"].strip():
            fail(f"{where}.title must be a non-empty string")
    parts = scene.get("parts")
    part_ids: set[str] = set()
    parts_by_assembly: dict[str, list[dict[str, Any]]] = {a: [] for a in assembly_ids}
    if not isinstance(parts, list) or not parts:
        fail("scene.parts must be a non-empty list")
        parts = []
    for i, part in enumerate(parts):
        where = f"scene.parts[{i}]"
        if not isinstance(part, dict):
            fail(f"{where} must be an object")
            continue
        part_id = part.get("id")
        if not isinstance(part_id, str) or not part_id.strip():
            fail(f"{where}.id must be a non-empty string")
            continue
        if part_id in part_ids:
            fail(f"duplicate part id: {part_id!r}")
        part_ids.add(part_id)
        kind = part.get("kind")
        if kind not in _PART_KINDS:
            fail(f"{where}.kind must be one of {_PART_KINDS}")
        asm_id = part.get("assembly")
        if asm_id not in assembly_ids:
            fail(f"{where}.assembly references unknown assembly {asm_id!r}")
        else:
            parts_by_assembly[asm_id].append(part)
        if not _is_vec3(part.get("position")):
            fail(f"{where}.position must be [x, y, z] finite numbers")
        explode = part.get("explode", [0, 0, 0])
        if not _is_vec3(explode):
            fail(f"{where}.explode must be [x, y, z] finite numbers")
        rotation = part.get("rotation", [0, 0, 0])
        if not _is_vec3(rotation):
            fail(f"{where}.rotation must be [x, y, z] finite numbers")
        material = part.get("material")
        if not isinstance(material, dict):
            fail(f"{where}.material must be an object")
        else:
            if material.get("palette") not in PALETTE:
                fail(f"{where}.material.palette must be one of {sorted(PALETTE)}")
            if material.get("tone") not in TONES:
                fail(f"{where}.material.tone must be one of {sorted(TONES)}")
            opacity = material.get("opacity", 1.0)
            if not isinstance(opacity, (int, float)) or not 0.0 < opacity <= 1.0:
                fail(f"{where}.material.opacity must be in (0, 1]")
        _verify_part_geometry(
            env, part, kind, where, fail, _check_quantity_ref, quantity_names, function_names
        )
    for asm_id, members in parts_by_assembly.items():
        if not members:
            warnings.append(f"assembly {asm_id!r} has no parts")

    breakdowns = spec.get("breakdowns")
    if not isinstance(breakdowns, list) or not breakdowns:
        fail("breakdowns must be a non-empty list")
        breakdowns = []
    breakdown_ids: set[str] = set()
    for i, bd in enumerate(breakdowns):
        where = f"breakdowns[{i}]"
        if not isinstance(bd, dict):
            fail(f"{where} must be an object")
            continue
        bd_id = bd.get("id")
        if not isinstance(bd_id, str) or not bd_id.strip():
            fail(f"{where}.id must be a non-empty string")
            continue
        if bd_id in breakdown_ids:
            fail(f"duplicate breakdown id: {bd_id!r}")
        breakdown_ids.add(bd_id)
        target = bd.get("target")
        if target not in assembly_ids:
            fail(f"{where}.target references unknown assembly {target!r}")
            continue
        kind = bd.get("kind")
        if kind not in _BREAKDOWN_KINDS:
            fail(f"{where}.kind must be one of {_BREAKDOWN_KINDS}")
            continue
        members = parts_by_assembly.get(target, [])
        if kind == "vector_components" and not any(p.get("kind") == "arrow" for p in members):
            fail(f"{where} (vector_components) needs an arrow part in assembly {target!r}")
        if kind == "graph_slope_area" and not any(p.get("kind") == "graph" for p in members):
            fail(f"{where} (graph_slope_area) needs a graph part in assembly {target!r}")
        if kind == "explode" and not any(p.get("explode", [0, 0, 0]) != [0, 0, 0] for p in members):
            fail(f"{where} (explode) needs a part with a non-zero explode vector in {target!r}")
        if not isinstance(bd.get("title"), str) or not bd["title"].strip():
            fail(f"{where}.title must be a non-empty string")
        facts = bd.get("facts", [])
        if not isinstance(facts, list):
            fail(f"{where}.facts must be a list")
            continue
        for j, fact in enumerate(facts):
            if not isinstance(fact, dict) or not isinstance(fact.get("label"), str):
                fail(f"{where}.facts[{j}] must carry a string label")
                continue
            if "quantity" in fact:
                _check_quantity_ref(fact["quantity"], f"{where}.facts[{j}].quantity")
                if fact["quantity"] in function_names:
                    fail(f"{where}.facts[{j}].quantity must be a parameter/derived, not a function")

    cameras = spec.get("cameras")
    if not isinstance(cameras, list) or not cameras:
        fail("cameras must be a non-empty list (one per page, starting at page 0)")
        cameras = []
    prev_page = -1
    for i, cam in enumerate(cameras):
        where = f"cameras[{i}]"
        if not isinstance(cam, dict):
            fail(f"{where} must be an object")
            continue
        page = cam.get("page")
        if not isinstance(page, int) or isinstance(page, bool):
            fail(f"{where}.page must be an integer")
            continue
        if page != prev_page + 1:
            fail(f"{where}.page must continue the sequence (expected {prev_page + 1}, got {page})")
        prev_page = page
        if not _is_vec3(cam.get("target")):
            fail(f"{where}.target must be [x, y, z] finite numbers")
        az = cam.get("az")
        if not isinstance(az, (int, float)) or not -180.0 <= az <= 180.0:
            fail(f"{where}.az must be in [-180, 180] degrees")
        el = cam.get("el")
        if not isinstance(el, (int, float)) or not -4.0 <= el <= 85.0:
            fail(f"{where}.el must be in [-4, 85] degrees")
        dist = cam.get("dist")
        if not isinstance(dist, (int, float)) or not math.isfinite(dist) or dist <= 0:
            fail(f"{where}.dist must be a positive finite number")
        focus = cam.get("focus_assembly")
        if focus is not None and focus not in assembly_ids:
            fail(f"{where}.focus_assembly references unknown assembly {focus!r}")

    checks = spec.get("checks")
    if not isinstance(checks, list) or len(checks) < 2:
        fail("checks must be a list of at least 2 invariant checks")
        checks = []
    check_ids: set[str] = set()
    independent = 0
    for i, check in enumerate(checks):
        where = f"checks[{i}]"
        if not isinstance(check, dict):
            fail(f"{where} must be an object")
            continue
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id.strip():
            fail(f"{where}.id must be a non-empty string")
            continue
        if check_id in check_ids:
            fail(f"duplicate check id: {check_id!r}")
        check_ids.add(check_id)
        if not isinstance(check.get("quantity"), str) or not check["quantity"].strip():
            fail(f"{where}.quantity must be a non-empty string")
        tolerance = check.get("tolerance")
        if (
            not isinstance(tolerance, (int, float))
            or not math.isfinite(tolerance)
            or tolerance <= 0
        ):
            fail(f"{where}.tolerance must be a positive finite number")
        for side in ("path_a", "path_b"):
            _verify_check_path(check.get(side), f"{where}.{side}", fail, env, function_names)
        if isinstance(check.get("path_a"), dict) and isinstance(check.get("path_b"), dict):
            method_a = check["path_a"].get("method")
            method_b = check["path_b"].get("method")
            if method_a in _CHECK_METHODS and method_b in _CHECK_METHODS:
                if method_a == method_b:
                    fail(f"{where} must recompute by two different methods (got {method_a} twice)")
                if method_b != "closed_form":
                    independent += 1
        if check.get("compare", "value") not in ("value", "abs"):
            fail(f"{where}.compare must be 'value' or 'abs'")
    if checks and independent < 1:
        fail("at least one check must recompute by an independent method (not closed_form)")

    return FigureVerification(ok=not reasons, reasons=reasons, warnings=warnings)


def _verify_part_geometry(
    env: dict[str, float],
    part: dict[str, Any],
    kind: Any,
    where: str,
    fail: Any,
    _check_quantity_ref: Any,
    quantity_names: set[str],
    function_names: set[str],
) -> None:
    if kind == "paper_solid":
        shape = part.get("shape")
        if shape not in _SOLID_SHAPES:
            fail(f"{where}.shape must be one of {_SOLID_SHAPES}")
            return
        dims = part.get("dims")
        needed = {
            "box": ("w", "h", "d"),
            "cylinder": ("r", "h"),
            "sphere": ("r",),
            "cone": ("r", "h"),
        }[shape]
        if not isinstance(dims, dict):
            fail(f"{where}.dims must be an object with {needed}")
            return
        for key in needed:
            value = dims.get(key)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                fail(f"{where}.dims.{key} must be a positive finite number")
    elif kind == "arrow":
        vector = part.get("vector")
        if not isinstance(vector, dict):
            fail(f"{where}.vector must be an object")
            return
        if not _is_vec3(vector.get("tail")):
            fail(f"{where}.vector.tail must be [x, y, z] finite numbers")
        components = vector.get("components")
        if not isinstance(components, list) or len(components) != 3:
            fail(f"{where}.vector.components must be a list of 3 expressions")
        sample_t = vector.get("sample_t", 0.0)
        if not isinstance(sample_t, (int, float)) or not math.isfinite(sample_t):
            fail(f"{where}.vector.sample_t must be a finite number")
        if (
            isinstance(components, list)
            and len(components) == 3
            and isinstance(sample_t, (int, float))
        ):
            trial = dict(env)
            trial["t"] = float(sample_t)
            for component in components:
                if not isinstance(component, str):
                    fail(f"{where}.vector.components entries must be expressions")
                    continue
                try:
                    _eval_expr(component, trial)
                except FigureSpecError as exc:
                    fail(f"{where}.vector.components entry failed: {exc}")
    elif kind == "axis":
        if not _is_vec3(part.get("direction")):
            fail(f"{where}.direction must be [x, y, z] finite numbers")
        length = part.get("length")
        if not isinstance(length, (int, float)) or not math.isfinite(length) or length <= 0:
            fail(f"{where}.length must be a positive finite number")
        ticks = part.get("ticks", 0)
        if not isinstance(ticks, int) or isinstance(ticks, bool) or ticks < 0:
            fail(f"{where}.ticks must be a non-negative integer")
    elif kind == "graph":
        fn = part.get("function")
        if fn not in function_names:
            fail(f"{where}.function references unknown model function {fn!r}")
        t_range = part.get("t_range")
        if (
            not isinstance(t_range, list)
            or len(t_range) != 2
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in t_range)
            or not t_range[0] < t_range[1]
        ):
            fail(f"{where}.t_range must be [t0, t1] with t0 < t1")
        samples = part.get("samples", 50)
        if not isinstance(samples, int) or isinstance(samples, bool) or not 2 <= samples <= 2000:
            fail(f"{where}.samples must be an integer in [2, 2000]")
    elif kind == "strobe":
        for key in ("function_x", "function_y"):
            if part.get(key) not in function_names:
                fail(f"{where}.{key} references unknown model function {part.get(key)!r}")
        fn_z = part.get("function_z")
        if fn_z is not None and fn_z not in function_names:
            fail(f"{where}.function_z references unknown model function {fn_z!r}")
        times = part.get("times")
        if (
            not isinstance(times, list)
            or not times
            or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in times)
        ):
            fail(f"{where}.times must be a non-empty list of finite numbers")
    elif kind == "polyline":
        points = part.get("points")
        if not isinstance(points, list) or len(points) < 2 or not all(_is_vec3(p) for p in points):
            fail(f"{where}.points must be a list of at least 2 [x, y, z] points")


def _verify_bound_value(value: Any, where: str, fail: Any, env: dict[str, float]) -> None:
    if isinstance(value, dict):
        if set(value) != {"expr"} or not isinstance(value.get("expr"), str):
            fail(f"{where} must be a number or {{'expr': ...}}")
            return
        try:
            _eval_expr(str(value["expr"]), env)
        except FigureSpecError as exc:
            fail(f"{where} expression failed: {exc}")
    elif not isinstance(value, (int, float)) or not math.isfinite(value):
        fail(f"{where} must be a finite number or {{'expr': ...}}")


def _verify_check_path(
    path: Any,
    where: str,
    fail: Any,
    env: dict[str, float],
    function_names: set[str],
) -> None:
    if not isinstance(path, dict):
        fail(f"{where} must be an object")
        return
    method = path.get("method")
    if method not in _CHECK_METHODS:
        fail(f"{where}.method must be one of {_CHECK_METHODS}")
        return
    if method in ("sample", "closed_form", "integrate", "finite_diff", "root"):
        expr = path.get("expression")
        if not isinstance(expr, str) or not expr.strip():
            fail(f"{where}.expression must be a non-empty expression")
            return
        trial = dict(env)
        trial["t"] = 0.0
        try:
            _eval_expr(expr, trial)
        except FigureSpecError as exc:
            fail(f"{where}.expression failed: {exc}")
    if method == "sample":
        at = path.get("at")
        if not isinstance(at, dict):
            fail(f"{where}.at must be an object with 't' or 't_expr'")
    if method == "integrate":
        for bound in ("from", "to"):
            if bound not in path:
                fail(f"{where}.{bound} is required")
            else:
                _verify_bound_value(path[bound], f"{where}.{bound}", fail, env)
        if "offset" in path:
            _verify_bound_value(path["offset"], f"{where}.offset", fail, env)
    if "scale" in path:
        _verify_bound_value(path["scale"], f"{where}.scale", fail, env)
        steps = path.get("steps", 200)
        if not isinstance(steps, int) or isinstance(steps, bool) or not 10 <= steps <= 20000:
            fail(f"{where}.steps must be an integer in [10, 20000]")
    if method == "finite_diff":
        at = path.get("at")
        if not isinstance(at, dict):
            fail(f"{where}.at must be an object with 't' or 't_expr'")
        h = path.get("h", 1e-4)
        if not isinstance(h, (int, float)) or not 0 < h < 1:
            fail(f"{where}.h must be in (0, 1)")
    if method == "root":
        expr = path.get("expression")
        if not isinstance(expr, str) or not expr.strip():
            fail(f"{where}.expression must be a non-empty expression")
            return
        for key in ("target", "lo", "hi"):
            if key not in path:
                fail(f"{where}.{key} is required")
        iterations = path.get("iterations", 50)
        if (
            not isinstance(iterations, int)
            or isinstance(iterations, bool)
            or not 10 <= iterations <= 200
        ):
            fail(f"{where}.iterations must be an integer in [10, 200]")


# ---------------------------------------------------------------------------
# Check execution: each quantity is computed two ways and compared.
# ---------------------------------------------------------------------------


def _eval_at(path: dict[str, Any], env: dict[str, float]) -> float:
    at = path.get("at", {})
    if "t" in at:
        t = at["t"]
        if not isinstance(t, (int, float)) or not math.isfinite(t):
            raise FigureSpecError("check path 'at.t' must be a finite number")
        return float(t)
    if "t_expr" in at:
        return _eval_expr(str(at["t_expr"]), env)
    raise FigureSpecError("check path 'at' must carry 't' or 't_expr'")


def _run_path(path: dict[str, Any], env: dict[str, float]) -> float:
    value = _run_path_inner(path, env)
    if "scale" in path:
        value *= _resolve_bound(path["scale"], env, "check scale")
    return value


def _run_path_inner(path: dict[str, Any], env: dict[str, float]) -> float:
    method = path["method"]
    if method == "sample":
        trial = dict(env)
        trial["t"] = _eval_at(path, env)
        return _eval_expr(str(path["expression"]), trial)
    if method == "closed_form":
        return _eval_expr(str(path["expression"]), env)
    if method == "integrate":
        a = _resolve_bound(path["from"], env, "integrate.from")
        b = _resolve_bound(path["to"], env, "integrate.to")
        steps = int(path.get("steps", 200))
        if steps % 2 == 1:
            steps += 1
        h = (b - a) / steps
        total = 0.0
        for i in range(steps + 1):
            trial = dict(env)
            trial["t"] = a + i * h
            value = _eval_expr(str(path["expression"]), trial)
            weight = 4 if i % 2 == 1 else 2
            if i in (0, steps):
                weight = 1
            total += weight * value
        return total * h / 3.0 + _resolve_bound(path.get("offset", 0), env, "integrate.offset")
    if method == "finite_diff":
        t0 = _eval_at(path, env)
        h = float(path.get("h", 1e-4))

        def _f(t: float) -> float:
            trial = dict(env)
            trial["t"] = t
            return _eval_expr(str(path["expression"]), trial)

        return (_f(t0 + h) - _f(t0 - h)) / (2 * h)
    if method == "root":
        target = float(path["target"])
        lo = float(path["lo"])
        hi = float(path["hi"])

        def _g(t: float) -> float:
            trial = dict(env)
            trial["t"] = t
            return _eval_expr(str(path["expression"]), trial) - target

        flo, fhi = _g(lo), _g(hi)
        if flo == 0.0:
            return lo
        if fhi == 0.0:
            return hi
        if (flo < 0) == (fhi < 0):
            raise FigureSpecError(
                f"root bracket [{lo}, {hi}] shows no sign change ({flo!r} vs {fhi!r})"
            )
        for _ in range(int(path.get("iterations", 50))):
            mid = (lo + hi) / 2.0
            if (_g(mid) < 0) == (flo < 0):
                lo, flo = mid, _g(mid)
            else:
                hi = mid
        return (lo + hi) / 2.0
    raise FigureSpecError(f"unknown check method: {method!r}")


def run_checks(spec: dict[str, Any]) -> CheckReport:
    verification = verify_figure_spec(spec)
    if not verification.ok:
        raise FigureSpecError("spec failed verification: " + "; ".join(verification.reasons))
    env = _base_env(spec)
    for item in spec["model"].get("derived", []):
        env[item["name"]] = float(item["value"])
    report = CheckReport(figure_id=str(spec["id"]))
    for check in spec["checks"]:
        try:
            value_a = _run_path(check["path_a"], env)
            value_b = _run_path(check["path_b"], env)
            if check.get("compare", "value") == "abs":
                value_a, value_b = abs(value_a), abs(value_b)
            diff = abs(value_a - value_b)
            passed = diff <= float(check["tolerance"])
            error = ""
        except FigureSpecError as exc:
            value_a = value_b = diff = 0.0
            passed = False
            error = str(exc)
        report.outcomes.append(
            CheckOutcome(
                id=str(check["id"]),
                quantity=str(check["quantity"]),
                value_a=value_a,
                value_b=value_b,
                abs_diff=diff,
                tolerance=float(check["tolerance"]),
                passed=passed,
                error=error,
            )
        )
    return report


# ---------------------------------------------------------------------------
# Deterministic scene generation (spec -> Three.js scene JSON).
# ---------------------------------------------------------------------------


def _round(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round(v) for v in value]
    return value


def _model_env(spec: dict[str, Any]) -> dict[str, float]:
    env = _base_env(spec)
    for item in spec["model"].get("derived", []):
        env[item["name"]] = float(item["value"])
    return env


def _sample_function(spec: dict[str, Any], name: str, t_values: list[float]) -> list[float]:
    fn = next(f for f in spec["model"].get("functions", []) if f["name"] == name)
    variables = fn.get("variables", ["t"])
    env = _model_env(spec)
    out = []
    for t in t_values:
        trial = dict(env)
        trial[variables[0]] = t
        out.append(_eval_expr(str(fn["expression"]), trial))
    return out


def _resolve_part(spec: dict[str, Any], part: dict[str, Any]) -> dict[str, Any]:
    env = _model_env(spec)
    material = part["material"]
    palette = PALETTE[str(material["palette"])]
    resolved: dict[str, Any] = {
        "id": part["id"],
        "kind": part["kind"],
        "assembly": part["assembly"],
        "position": [float(v) for v in part["position"]],
        "rotation": [float(v) for v in part.get("rotation", [0, 0, 0])],
        "explode": [float(v) for v in part.get("explode", [0, 0, 0])],
        "material": {
            "palette": material["palette"],
            "tones": list(palette),
            "tone": material["tone"],
            "tone_weight": TONES[str(material["tone"])],
            "opacity": float(material.get("opacity", 1.0)),
        },
    }
    if part.get("label"):
        resolved["label"] = str(part["label"])
    kind = part["kind"]
    if kind == "paper_solid":
        resolved["shape"] = part["shape"]
        resolved["dims"] = {k: float(v) for k, v in part["dims"].items()}
    elif kind == "arrow":
        vector = part["vector"]
        trial = dict(env)
        trial["t"] = float(vector.get("sample_t", 0.0))
        components = [_eval_expr(str(c), trial) for c in vector["components"]]
        resolved["vector"] = {
            "tail": [float(v) for v in vector["tail"]],
            "components": [round(c, 6) for c in components],
            "sample_t": trial["t"],
        }
    elif kind == "axis":
        resolved["direction"] = [float(v) for v in part["direction"]]
        resolved["length"] = float(part["length"])
        resolved["ticks"] = int(part.get("ticks", 0))
    elif kind == "graph":
        t0, t1 = float(part["t_range"][0]), float(part["t_range"][1])
        samples = int(part.get("samples", 50))
        times = [t0 + (t1 - t0) * i / (samples - 1) for i in range(samples)]
        values = _sample_function(spec, str(part["function"]), times)
        mid = (t0 + t1) / 2.0
        slope = _run_path(
            {
                "method": "finite_diff",
                "expression": _graph_expression(spec, str(part["function"])),
                "at": {"t": mid},
            },
            env,
        )
        area = _run_path(
            {
                "method": "integrate",
                "expression": _graph_expression(spec, str(part["function"])),
                "from": t0,
                "to": t1,
                "steps": 200,
            },
            env,
        )
        resolved["graph"] = {
            "function": part["function"],
            "t_range": [t0, t1],
            "points": [[round(t, 6), round(v, 6)] for t, v in zip(times, values, strict=True)],
            "slope_at_mid": round(slope, 6),
            "area_under_curve": round(area, 6),
        }
    elif kind == "strobe":
        points = []
        xs = _sample_function(spec, str(part["function_x"]), [float(t) for t in part["times"]])
        ys = _sample_function(spec, str(part["function_y"]), [float(t) for t in part["times"]])
        if part.get("function_z"):
            zs = _sample_function(spec, str(part["function_z"]), [float(t) for t in part["times"]])
        else:
            zs = [0.0] * len(part["times"])
        for t, x, y, z in zip(part["times"], xs, ys, zs, strict=True):
            points.append({"t": float(t), "position": [round(x, 6), round(y, 6), round(z, 6)]})
        resolved["strobe"] = {"points": points}
    elif kind == "polyline":
        resolved["points"] = [[float(v) for v in p] for p in part["points"]]
    return resolved


def _graph_expression(spec: dict[str, Any], name: str) -> str:
    fn = next(f for f in spec["model"].get("functions", []) if f["name"] == name)
    return str(fn["expression"])


def generate_scene(spec: dict[str, Any], *, seed: int = 0) -> dict[str, Any]:
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise FigureSpecError("seed must be an integer")
    verification = verify_figure_spec(spec)
    if not verification.ok:
        raise FigureSpecError("spec failed verification: " + "; ".join(verification.reasons))
    report = run_checks(spec)
    if not report.all_passed:
        failed = [o.id for o in report.outcomes if not o.passed]
        raise FigureSpecError(f"invariant checks failed: {failed}")
    env = _model_env(spec)
    breakdowns = []
    for bd in spec["breakdowns"]:
        facts = []
        for fact in bd.get("facts", []):
            quantity = fact["quantity"]
            facts.append(
                {"label": fact["label"], "quantity": quantity, "value": round(env[quantity], 6)}
            )
        breakdowns.append(
            {
                "id": bd["id"],
                "target": bd["target"],
                "kind": bd["kind"],
                "title": bd["title"],
                "text": bd.get("text", ""),
                "facts": facts,
            }
        )
    scene = {
        "schema_version": SCHEMA_VERSION,
        "id": spec["id"],
        "title": spec["title"],
        "language": spec["language"],
        "provenance": dict(spec["provenance"]),
        "model": {
            "parameters": [
                {"name": p["name"], "value": float(p["value"]), "unit": p["unit"]}
                for p in spec["model"]["parameters"]
            ],
            "derived": [
                {
                    "name": d["name"],
                    "value": float(d["value"]),
                    "unit": d["unit"],
                    "formula": d["formula"],
                }
                for d in spec["model"].get("derived", [])
            ],
            "functions": [
                {"name": f["name"], "expression": f["expression"], "unit": f["unit"]}
                for f in spec["model"].get("functions", [])
            ],
            "caveat": spec["model"]["caveat"],
        },
        "assemblies": [
            {"id": a["id"], "title": a["title"], "sub": a.get("sub", "")}
            for a in spec["scene"]["assemblies"]
        ],
        "parts": [_resolve_part(spec, p) for p in spec["scene"]["parts"]],
        "cameras": [
            {
                "page": c["page"],
                "title": c.get("title", ""),
                "target": [float(v) for v in c["target"]],
                "az": float(c["az"]),
                "el": float(c["el"]),
                "dist": float(c["dist"]),
                "focus_assembly": c.get("focus_assembly"),
            }
            for c in spec["cameras"]
        ],
        "breakdowns": breakdowns,
        "checks": report.as_dict(),
        "meta": {
            "generator": "hevi.capabilities.atlas_figure",
            "seed": seed,
            "deterministic": True,
            "note": "Scene specification only: no pixels are rendered here. "
            "Consume with a Three.js host player (see atlas_figure.md).",
        },
    }
    return _round(scene)


def scene_to_json(scene: dict[str, Any]) -> str:
    return json.dumps(scene, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Reference figures (self-written; self-chosen parameters, stated from the
# public laws: projectile motion under constant gravity; small-angle pendulum).
# ---------------------------------------------------------------------------

REFERENCE_PROJECTILE: dict[str, Any] = {
    "id": "reference-projectile",
    "title": "平抛运动：从高处水平抛出",
    "language": "zh",
    "provenance": {
        "source": "hevi self-written reference (clean rewrite)",
        "license": "hevi-internal",
    },
    "model": {
        "parameters": [
            {"name": "g", "value": 9.8, "unit": "m/s^2"},
            {"name": "v0", "value": 8.0, "unit": "m/s"},
            {"name": "h", "value": 5.0, "unit": "m"},
        ],
        "derived": [
            {"name": "T", "formula": "sqrt(2*h/g)", "value": 1.0101525445522108, "unit": "s"},
            {"name": "R", "formula": "v0*T", "value": 8.081220356417687, "unit": "m"},
        ],
        "functions": [
            {"name": "x", "expression": "v0*t", "variables": ["t"], "unit": "m"},
            {"name": "y", "expression": "h - 0.5*g*t*t", "variables": ["t"], "unit": "m"},
            {"name": "vx", "expression": "v0", "variables": ["t"], "unit": "m/s"},
            {"name": "vy", "expression": "-g*t", "variables": ["t"], "unit": "m/s"},
            {
                "name": "speed",
                "expression": "sqrt(v0*v0 + (g*t)*(g*t))",
                "variables": ["t"],
                "unit": "m/s",
            },
        ],
        "caveat": "Assume constant gravity, no air resistance, flat ground at y=0; "
        "All quantities use SI units.",
    },
    "scene": {
        "assemblies": [
            {"id": "projectile", "title": "抛体", "sub": "小球、速度箭头与重力箭头"},
            {"id": "frame", "title": "参考系", "sub": "坐标轴与地面"},
            {"id": "graph", "title": "图像", "sub": "高度随时间变化"},
        ],
        "parts": [
            {
                "id": "ball",
                "kind": "paper_solid",
                "assembly": "projectile",
                "shape": "sphere",
                "dims": {"r": 0.25},
                "position": [0.0, 5.0, 0.0],
                "material": {"palette": "red", "tone": "hi"},
                "label": "小球",
            },
            {
                "id": "vel",
                "kind": "arrow",
                "assembly": "projectile",
                "position": [0.0, 5.0, 0.0],
                "vector": {
                    "tail": [0.0, 5.0, 0.0],
                    "components": ["v0", "-g*t", "0"],
                    "sample_t": 0.5,
                },
                "material": {"palette": "blue", "tone": "hi"},
                "label": "速度",
            },
            {
                "id": "grav",
                "kind": "arrow",
                "assembly": "projectile",
                "position": [0.0, 5.0, 0.0],
                "vector": {
                    "tail": [0.0, 5.0, 0.0],
                    "components": ["0", "-g", "0"],
                    "sample_t": 0.0,
                },
                "material": {"palette": "ink", "tone": "mid"},
                "label": "重力",
            },
            {
                "id": "axes",
                "kind": "axis",
                "assembly": "frame",
                "position": [0.0, 0.0, 0.0],
                "direction": [1, 0, 0],
                "length": 9.0,
                "ticks": 9,
                "material": {"palette": "ink", "tone": "lo"},
            },
            {
                "id": "ground",
                "kind": "polyline",
                "assembly": "frame",
                "position": [0.0, 0.0, 0.0],
                "points": [[-1.0, 0.0, 0.0], [9.0, 0.0, 0.0]],
                "material": {"palette": "dark", "tone": "mid"},
            },
            {
                "id": "strobe",
                "kind": "strobe",
                "assembly": "projectile",
                "position": [0.0, 0.0, 0.0],
                "function_x": "x",
                "function_y": "y",
                "times": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
                "material": {"palette": "paper", "tone": "mid"},
            },
            {
                "id": "yt-graph",
                "kind": "graph",
                "assembly": "graph",
                "position": [0.0, 0.0, 0.0],
                "function": "y",
                "t_range": [0.0, 1.01],
                "samples": 50,
                "material": {"palette": "blue", "tone": "hi"},
            },
        ],
    },
    "breakdowns": [
        {
            "id": "bd-velocity",
            "target": "projectile",
            "kind": "vector_components",
            "title": "速度分解",
            "text": "水平分量不变，竖直分量随时间线性增大（向下）。",
            "facts": [
                {"label": "水平初速 v0", "quantity": "v0"},
                {"label": "重力加速度 g", "quantity": "g"},
            ],
        },
        {
            "id": "bd-graph",
            "target": "graph",
            "kind": "graph_slope_area",
            "title": "图像的斜率与面积",
            "text": "y-t 图像的斜率是竖直速度；v-t 图像下的面积是位移。",
            "facts": [
                {"label": "飞行时间 T", "quantity": "T"},
                {"label": "水平射程 R", "quantity": "R"},
            ],
        },
    ],
    "cameras": [
        {
            "page": 0,
            "title": "全景",
            "target": [4.0, 2.5, 0.0],
            "az": -25.0,
            "el": 12.0,
            "dist": 14.0,
        },
        {
            "page": 1,
            "title": "抛体特写",
            "target": [4.0, 3.0, 0.0],
            "az": -15.0,
            "el": 8.0,
            "dist": 7.0,
            "focus_assembly": "projectile",
        },
        {
            "page": 2,
            "title": "图像页",
            "target": [0.0, 2.5, 0.0],
            "az": 0.0,
            "el": 6.0,
            "dist": 8.0,
            "focus_assembly": "graph",
        },
    ],
    "checks": [
        {
            "id": "ck-landing",
            "quantity": "landing height y(T) == 0",
            "tolerance": 1e-6,
            "path_a": {
                "method": "sample",
                "expression": "h - 0.5*g*t*t",
                "at": {"t_expr": "sqrt(2*h/g)"},
            },
            "path_b": {
                "method": "integrate",
                "expression": "-g*t",
                "from": 0,
                "to": {"expr": "sqrt(2*h/g)"},
                "steps": 200,
                "offset": {"expr": "h"},
            },
        },
        {
            "id": "ck-range",
            "quantity": "range R",
            "tolerance": 1e-6,
            "path_a": {"method": "sample", "expression": "v0*t", "at": {"t_expr": "sqrt(2*h/g)"}},
            "path_b": {
                "method": "integrate",
                "expression": "v0",
                "from": 0,
                "to": {"expr": "sqrt(2*h/g)"},
                "steps": 200,
            },
        },
        {
            "id": "ck-impact-speed",
            "quantity": "impact speed",
            "tolerance": 1e-6,
            "path_a": {
                "method": "sample",
                "expression": "sqrt(v0*v0 + (g*t)*(g*t))",
                "at": {"t_expr": "sqrt(2*h/g)"},
            },
            "path_b": {"method": "closed_form", "expression": "sqrt(v0*v0 + 2*g*h)"},
        },
    ],
}

REFERENCE_PENDULUM: dict[str, Any] = {
    "id": "reference-pendulum",
    "title": "单摆小角度振动",
    "language": "zh",
    "provenance": {
        "source": "hevi self-written reference (clean rewrite)",
        "license": "hevi-internal",
    },
    "model": {
        "parameters": [
            {"name": "g", "value": 9.8, "unit": "m/s^2"},
            {"name": "L", "value": 1.2, "unit": "m"},
            {"name": "theta0", "value": 0.12, "unit": "rad"},
        ],
        "derived": [
            {"name": "omega", "formula": "sqrt(g/L)", "value": 2.8577380332472737, "unit": "rad/s"},
            {"name": "T", "formula": "2*pi*sqrt(L/g)", "value": 2.1986568517060525, "unit": "s"},
        ],
        "functions": [
            {
                "name": "theta",
                "expression": "theta0*cos(sqrt(g/L)*t)",
                "variables": ["t"],
                "unit": "rad",
            },
            {
                "name": "omega_t",
                "expression": "-theta0*sqrt(g/L)*sin(sqrt(g/L)*t)",
                "variables": ["t"],
                "unit": "rad/s",
            },
        ],
        "caveat": "Small-angle approximation (sin(theta) ~ theta); massless string, "
        "point bob, no damping; pivot fixed at (0, 3, 0).",
    },
    "scene": {
        "assemblies": [
            {"id": "pendulum", "title": "单摆", "sub": "支点、摆线与摆球"},
            {"id": "graph", "title": "图像", "sub": "角位移随时间变化"},
        ],
        "parts": [
            {
                "id": "pivot",
                "kind": "paper_solid",
                "assembly": "pendulum",
                "shape": "box",
                "dims": {"w": 0.4, "h": 0.15, "d": 0.4},
                "position": [0.0, 3.0, 0.0],
                "material": {"palette": "dark", "tone": "mid"},
            },
            {
                "id": "string",
                "kind": "polyline",
                "assembly": "pendulum",
                "position": [0.0, 0.0, 0.0],
                "points": [[0.0, 3.0, 0.0], [0.0, 1.8, 0.0]],
                "material": {"palette": "ink", "tone": "hi"},
            },
            {
                "id": "bob",
                "kind": "paper_solid",
                "assembly": "pendulum",
                "shape": "sphere",
                "dims": {"r": 0.3},
                "position": [0.0, 1.8, 0.0],
                "explode": [0.0, -0.6, 0.0],
                "material": {"palette": "red", "tone": "hi"},
                "label": "摆球",
            },
            {
                "id": "theta-graph",
                "kind": "graph",
                "assembly": "graph",
                "position": [0.0, 0.0, 0.0],
                "function": "theta",
                "t_range": [0.0, 2.2],
                "samples": 50,
                "material": {"palette": "blue", "tone": "hi"},
            },
        ],
    },
    "breakdowns": [
        {
            "id": "bd-explode",
            "target": "pendulum",
            "kind": "explode",
            "title": "分解",
            "text": "摆球沿摆线方向拉开，露出支点与摆线。",
            "facts": [
                {"label": "摆长 L", "quantity": "L"},
                {"label": "角频率", "quantity": "omega"},
            ],
        },
        {
            "id": "bd-graph",
            "target": "graph",
            "kind": "graph_slope_area",
            "title": "图像的斜率",
            "text": "theta-t 图像的斜率是角速度；过零点处斜率最大。",
            "facts": [
                {"label": "周期 T", "quantity": "T"},
                {"label": "振幅", "quantity": "theta0"},
            ],
        },
    ],
    "cameras": [
        {
            "page": 0,
            "title": "全景",
            "target": [0.0, 2.2, 0.0],
            "az": -20.0,
            "el": 10.0,
            "dist": 7.0,
        },
        {
            "page": 1,
            "title": "摆球特写",
            "target": [0.0, 1.8, 0.0],
            "az": -10.0,
            "el": 6.0,
            "dist": 4.0,
            "focus_assembly": "pendulum",
        },
        {
            "page": 2,
            "title": "图像页",
            "target": [0.0, 1.1, 0.0],
            "az": 0.0,
            "el": 6.0,
            "dist": 5.0,
            "focus_assembly": "graph",
        },
    ],
    "checks": [
        {
            "id": "ck-period",
            "quantity": "period T",
            "tolerance": 1e-6,
            "path_a": {"method": "closed_form", "expression": "2*pi*sqrt(L/g)"},
            "path_b": {
                "method": "root",
                "expression": "theta0*cos(sqrt(g/L)*t)",
                "target": 0,
                "lo": 0.1,
                "hi": 1.0,
                "iterations": 60,
                "scale": {"expr": "4"},
            },
        },
        {
            "id": "ck-max-omega",
            "quantity": "max angular speed",
            "tolerance": 1e-4,
            "compare": "abs",
            "path_a": {"method": "closed_form", "expression": "theta0*sqrt(g/L)"},
            "path_b": {
                "method": "finite_diff",
                "expression": "theta0*cos(sqrt(g/L)*t)",
                "at": {"t_expr": "pi/(2*sqrt(g/L))"},
                "h": 0.0001,
            },
        },
    ],
}


def reference_figures() -> dict[str, dict[str, Any]]:
    return {"projectile": REFERENCE_PROJECTILE, "pendulum": REFERENCE_PENDULUM}


# ---------------------------------------------------------------------------
# Registry wiring (same shape as the sibling capability modules).
# ---------------------------------------------------------------------------

_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "spec": {"type": "object"},
        "seed": {"type": "integer"},
    },
    "required": ["spec"],
}


def _render_atlas_figure(
    params: dict[str, Any],
    out_dir: str,
    *,
    duration: float,
    aspect: str,
    seed: int,
) -> Any:
    from .result import CapabilityResult

    spec = params.get("spec")
    if not isinstance(spec, dict):
        raise CapabilityError("atlas_figure render requires params.spec to be an object")
    try:
        scene = generate_scene(spec, seed=int(params.get("seed", seed)))
    except FigureSpecError as exc:
        raise CapabilityError(f"atlas_figure spec rejected: {exc}") from exc
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    scene_path = out / "atlas_figure_scene.json"
    scene_path.write_text(scene_to_json(scene), encoding="utf-8")
    checks_path = out / "atlas_figure_checks.json"
    checks_path.write_text(
        json.dumps(scene["checks"], ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
    sha256 = hashlib.sha256(scene_path.read_bytes()).hexdigest()
    return CapabilityResult(
        sha256=sha256,
        duration_s=float(duration),
        qa={
            "figure_id": scene["id"],
            "checks_passed": sum(1 for c in scene["checks"]["checks"] if c["passed"]),
            "checks_total": len(scene["checks"]["checks"]),
            "scene_json": str(scene_path),
            "aspect": aspect,
            "media": None,
            "note": "Spec-only capability: no pixels rendered. "
            "The scene JSON is consumed by a Three.js host player.",
        },
    )


def register_atlas_figure_capabilities_once() -> list[Capability]:
    """Register ``physics.atlas_figure`` (idempotent)."""
    if contains(CAPABILITY_NAME):
        return [get(CAPABILITY_NAME)]
    register(
        Capability(
            name=CAPABILITY_NAME,
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.05,
            render=lambda params, out_dir, *, duration, aspect, seed: _render_atlas_figure(
                params, out_dir, duration=duration, aspect=aspect, seed=seed
            ),
            description="交互式物理图场景规约：验证物理模型＋不变量检查，生成确定性 Three.js 场景 JSON（只出规约、不渲染像素）。",
            line="physics",
        )
    )
    return [get(CAPABILITY_NAME)]
