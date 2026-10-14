"""Zero-cost line transaction (omodul): request -> producer -> measured QA ->
contact sheet -> ``record.json``.

Standard 3O triple signature ``(config, input_data, output_dir, *, on_step)``.
Fail-closed and never raises: invalid input -> ``status="blocked"``; producer
error or ANY failed measured gate -> ``status="failed"`` with the numbers.
"""

from __future__ import annotations

import json
import shutil
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.zerolines.omodul_impl._lines import PRODUCERS
from hevi.layer4_legacy.zerolines.omodul_impl._media import ZeroMediaError, contact_sheet, measure
from hevi.layer4_legacy.zerolines.oprim_impl.specs import ZeroLineRequest, spec_for

_enabled_pillars = {"report", "cost", "decision_trail"}

RECORD_SCHEMA = "hevi.zerolines.record/1"


def request_from_input(input_data: dict[str, Any]) -> ZeroLineRequest:
    def tup(key: str) -> tuple:
        raw = input_data.get(key) or ()
        if isinstance(raw, str):
            raw = [raw]
        return tuple(raw)

    return ZeroLineRequest(
        line_id=str(input_data.get("line_id") or ""),
        texts=tuple(str(t).strip() for t in tup("texts")),
        queries=tuple(str(q).strip() for q in tup("queries")),
        topic=str(input_data.get("topic") or ""),
        title=str(input_data.get("title") or ""),
        lang=str(input_data.get("lang") or "zh"),
        media_path=str(input_data.get("media_path") or ""),
        offsets=tuple(float(o) for o in tup("offsets")),
        labels=tuple(str(x) for x in tup("labels")),
        extras=dict(input_data.get("extras") or {}),
    )


def zero_line_workflow(
    config: dict[str, Any] | None,
    input_data: dict[str, Any],
    output_dir: str | Path,
    *,
    on_step: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    cfg = dict(config or {})
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    trail: list[dict[str, Any]] = []

    def step(name: str, **info: Any) -> None:
        trail.append({"step": name, "t": round(time.time(), 3), **info})
        if on_step:
            on_step(name, info)

    started = time.time()
    try:
        req = request_from_input(input_data)
    except (TypeError, ValueError) as exc:
        return _finish(out, status="blocked", reason=f"invalid zero-line input: {exc}", line_id=str(input_data.get("line_id")),
                       trail=trail, started=started)
    errors = req.validate()
    step("validate", errors=errors)
    if errors:
        return _finish(out, status="blocked", reason="; ".join(errors), line_id=req.line_id, trail=trail, started=started,
                       request=req.to_dict())
    spec = spec_for(req.line_id)
    work = out / "tmp"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        step("produce", line=req.line_id, engine="zero")
        produced = PRODUCERS[req.line_id](req, out)
    except (ZeroMediaError, ValueError, OSError) as exc:
        return _finish(out, status="failed", reason=f"{type(exc).__name__}: {exc}", line_id=req.line_id, trail=trail,
                       started=started, request=req.to_dict())
    except Exception as exc:  # unexpected: still fail closed, with the traceback
        return _finish(out, status="failed", reason=f"{type(exc).__name__}: {exc}", line_id=req.line_id, trail=trail,
                       started=started, request=req.to_dict(), tb=traceback.format_exc()[-3000:])
    finals = [Path(p) for p in produced["finals"]]
    qa = []
    for p in finals:
        if not p.is_file() or p.stat().st_size == 0:
            return _finish(out, status="failed", reason=f"producer reported a missing/empty final: {p}",
                           line_id=req.line_id, trail=trail, started=started, request=req.to_dict())
        m = measure(p, expect_size=(spec.width, spec.height), thresholds=spec.qa)
        sheet = contact_sheet(p, out / (f"contact_sheet_{p.stem}.jpg" if len(finals) > 1 else "contact_sheet.jpg"))
        m["contact_sheet"] = str(sheet)
        qa.append(m)
        step("qa", final=p.name, passed=m["pass"], failed=m["failed_checks"])
    if not cfg.get("keep_tmp"):
        shutil.rmtree(work, ignore_errors=True)
    passed = all(m["pass"] for m in qa)
    reason = "" if passed else "QUALITY_GATE_FAILED: " + "; ".join(
        f"{Path(m['path']).name}: {', '.join(m['failed_checks'])}" for m in qa if not m["pass"])
    return _finish(out, status="succeeded" if passed else "failed", reason=reason, line_id=req.line_id, trail=trail,
                   started=started, request=req.to_dict(), finals=[str(p) for p in finals], qa=qa,
                   provenance=produced.get("provenance", []), notes=produced.get("notes", ""),
                   artifacts=produced.get("artifacts", {}), spec=spec.description)


def _finish(out: Path, *, status: str, reason: str, line_id: str | None, trail: list, started: float,
            **extra: Any) -> dict[str, Any]:
    rec = {
        "schema": RECORD_SCHEMA,
        "status": status,
        "line_id": line_id,
        "engine": "zero",
        "reason": reason,
        "cost": {"usd": 0.0, "gpu": False, "paid_api": False},
        "elapsed_s": round(time.time() - started, 2),
        "decision_trail": trail,
        "produced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **extra,
    }
    record = out / "record.json"
    record.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": status, "reason": reason, "record_path": str(record), **rec}


__all__ = ["RECORD_SCHEMA", "request_from_input", "zero_line_workflow"]
