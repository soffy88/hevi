"""Model directory discipline (``model.model_directory``).

A model appearing in a directory is not a verified, generatable
model. This module enforces the discipline around that distinction:

* Registration is not verification. ``register_model`` records a
  model id and its configuration with ``status: unverified``,
  ``verified_at: null``. Presence in the directory never implies a
  passing test.
* Configuration changes invalidate verification. Every record
  carries ``config_hash`` (sha256 of the canonical JSON of the
  config). ``call_model`` compares the hash of the config it is
  asked to use against the stored verified hash: a changed config
  that has not been retested is refused, naming the model and the
  hash mismatch.
* Retesting records time and result. ``run_model_test`` stores
  ``tested_at``, ``verified_at`` (set only on a passing result),
  ``result`` (``pass`` / ``fail``) and ``config_hash`` for the exact
  config tested. A failed test leaves the model unverified.
* Testing prompts the supplier fee first. ``fee_notice`` is built
  before any test result is recorded, and it is returned with every
  test outcome. The fee itself always comes from the caller
  (``unit_price_caller``): when supplied, the notice says the fee
  was provided by the caller; when not supplied, the notice says
  the fee was not provided. This module contains no price table,
  no default price and no estimated rate, and it never invents a
  fee figure.
* Unverified models are refused at call time. ``call_model`` raises
  for an unknown model, an unverified model, a failed last test, or
  a config that changed since the last passing test. It performs
  no generation itself -- it is a gate, so a refusal can never be
  mistaken for a generation result.

Records live in a JSON file (default ``model_directory.json`` next
to the caller-chosen path, or any explicit path). The caller owns
the test itself: ``run_model_test`` takes either a ``test_fn`` callable
returning a pass/fail result or an explicit ``result`` supplied by
the caller (for example a human-observed test outcome). With
neither, the test is ``pending`` and records nothing as verified.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False


def _fail(message: str) -> None:
    raise CapabilityError(f"model.model_directory: {message}")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def config_hash(config: Any) -> str:
    """Canonical hash of a config: sorted keys, no whitespace drift."""
    blob = json.dumps(config, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fee_notice(unit_price_caller: Any = None,
               currency: str = "") -> str:
    """Fee prompt text for a model test, before the test runs.

    The fee is always the caller's figure. When the caller supplies
    one, the notice says so; when they do not, the notice says the
    fee was not provided. No figure is ever invented here.
    """
    if unit_price_caller is None:
        return (
            "供应商费用提示：费用未提供。"
            "费用由调用方提供；本次测试未收到调用方提供的费用，"
            "故不标注任何价格、不按任何价格表计费。"
        )
    suffix = f" {currency}" if currency else ""
    return (
        "供应商费用提示：费用由调用方提供，"
        f"调用方提供的单价为 {unit_price_caller}{suffix}。"
        "本模块不内置任何价格表，该数字仅为调用方提供的值，"
        "测试前请确认该费用由你承担。"
    )


def _load(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            _fail(f"model directory is not valid JSON: {path}")
        if not isinstance(data, dict) or "models" not in data:
            _fail(f"model directory has no models block: {path}")
        return data
    return {"capability": "model.model_directory", "models": {}}


def _save(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def register_model(
    directory_path: Path, *, model_id: str, config: Any
) -> dict[str, Any]:
    """Record a model as present-but-unverified. Never verified here."""
    if not model_id or not isinstance(model_id, str):
        _fail("register_model: model_id must be a non-empty string")
    path = Path(directory_path)
    data = _load(path)
    record = {
        "model_id": model_id,
        "config": config,
        "config_hash": config_hash(config),
        "status": "unverified",
        "verified_at": None,
        "tested_at": None,
        "result": None,
    }
    data["models"][model_id] = record
    _save(path, data)
    return dict(record)


def record_in_directory(
    directory_path: Path, records: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Write several (model_id -> config) records via ``register_model``.

    Single write path for all model/pricing registrations (SPEC 1.4
    single source): Floyo, Modal, Seedance and VidoGrid registrations
    only supply record constructors; the directory write and the
    ``status: unverified`` discipline live here and in
    ``register_model`` alone. Every record lands unverified.
    """
    path = Path(directory_path)
    return {
        model_id: register_model(path, model_id=model_id, config=config)
        for model_id, config in records.items()
    }


def get_record(directory_path: Path, model_id: str) -> dict[str, Any]:
    data = _load(Path(directory_path))
    record = data["models"].get(model_id)
    if record is None:
        _fail(
            f"model not in directory: {model_id!r}; known: "
            f"{sorted(data['models'])}"
        )
    return dict(record)


def run_model_test(
    directory_path: Path,
    *,
    model_id: str,
    config: Any,
    unit_price_caller: Any = None,
    currency: str = "",
    test_fn: Callable[[], Any] | None = None,
    result: Any = None,
) -> dict[str, Any]:
    """Test a model (fee notice first) and record time + result + hash.

    ``test_fn`` (if callable) decides pass/fail; otherwise the
    caller-supplied ``result`` (``pass``/``fail``/True/False) is used;
    with neither, the outcome is ``pending`` and nothing is verified.
    The fee notice is always built first and always returned.
    """
    notice = fee_notice(unit_price_caller, currency=currency)
    path = Path(directory_path)
    data = _load(path)
    if model_id not in data["models"]:
        # Testing an unregistered model registers it first, still
        # unverified until this test passes.
        register_model(path, model_id=model_id, config=config)
        data = _load(path)
    outcome: str
    if callable(test_fn):
        try:
            raw = test_fn()
        except Exception:
            raw = False
        outcome = "pass" if raw in (True, "pass") else "fail"
    elif result in (True, "pass"):
        outcome = "pass"
    elif result in (False, "fail"):
        outcome = "fail"
    else:
        outcome = "pending"
    tested_at = _now_iso()
    digest = config_hash(config)
    record = data["models"][model_id]
    record.update({
        "config": config,
        "config_hash": digest,
        "tested_at": tested_at,
        "result": outcome,
    })
    if outcome == "pass":
        record["status"] = "verified"
        record["verified_at"] = tested_at
    else:
        record["status"] = "unverified"
        record["verified_at"] = None
    _save(path, data)
    return {
        **dict(record),
        "fee_notice": notice,
        "fee_notice_shown_before_test": True,
    }


def call_model(
    directory_path: Path, *, model_id: str, config: Any
) -> dict[str, Any]:
    """Gate a model call: only a verified, unchanged config may pass.

    Raises for unknown, unverified, failed, or config-changed
    models. A passing gate returns ``allowed: True`` and performs
    no generation itself.
    """
    record = get_record(directory_path, model_id)
    if record.get("status") != "verified" or not record.get("verified_at"):
        _fail(
            f"model {model_id!r} is not verified (status: "
            f"{record.get('status')!r}, last result: "
            f"{record.get('result')!r}); directory presence is not "
            "verification -- test it first with run_model_test"
        )
    if record.get("result") != "pass":
        _fail(
            f"model {model_id!r} has no passing test on record "
            f"(last result: {record.get('result')!r}); call refused"
        )
    current = config_hash(config)
    if current != record.get("config_hash"):
        _fail(
            f"model {model_id!r} configuration changed since its last "
            f"passing test (stored config_hash "
            f"{record.get('config_hash')}, current config_hash "
            f"{current}); retest with run_model_test before calling"
        )
    return {
        "allowed": True,
        "model_id": model_id,
        "verified_at": record.get("verified_at"),
        "result": record.get("result"),
        "config_hash": current,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = params.get("action", "call")
    directory_path = Path(params["directory_path"])
    if action == "register":
        result: dict[str, Any] = {
            "capability": "model.model_directory",
            "record": register_model(
                directory_path, model_id=str(params["model_id"]),
                config=params.get("config"),
            ),
        }
    elif action == "test":
        result = {
            "capability": "model.model_directory",
            "record": run_model_test(
                directory_path, model_id=str(params["model_id"]),
                config=params.get("config"),
                unit_price_caller=params.get("unit_price_caller"),
                currency=str(params.get("currency", "")),
                result=params.get("result"),
            ),
        }
    elif action == "call":
        result = {
            "capability": "model.model_directory",
            **call_model(
                directory_path, model_id=str(params["model_id"]),
                config=params.get("config"),
            ),
        }
    elif action == "fee_notice":
        result = {
            "capability": "model.model_directory",
            "fee_notice": fee_notice(
                params.get("unit_price_caller"),
                currency=str(params.get("currency", "")),
            ),
        }
    else:
        _fail(
            "unknown action "
            f"{action!r}; known: register, test, call, fee_notice"
        )
    report_path = out_dir / "model_directory_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "result": result},
    )


def register_model_directory_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.model_directory",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "directory_path": {"type": "string"},
                    "action": {"type": "string", "enum": [
                        "register", "test", "call", "fee_notice"]},
                    "model_id": {"type": "string"},
                    "config": {},
                    "unit_price_caller": {"type": "number"},
                    "currency": {"type": "string"},
                    "result": {"type": "string"},
                },
                "required": ["directory_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Model directory discipline: a model listed in the "
                "directory is unverified until it passes a test; a "
                "config change invalidates verification until retested; "
                "every test records tested_at / verified_at / result / "
                "config_hash; the supplier fee is prompted before any "
                "test from a caller-supplied figure (or marked as not "
                "provided), never from a price table in this module; "
                "unverified or config-changed models are refused at "
                "call time. This gate performs no generation."
            ),
            line="model",
        )
    )
    return ["model.model_directory"]


register_model_directory_capabilities_once()
