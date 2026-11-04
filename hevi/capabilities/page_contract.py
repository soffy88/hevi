"""Page contract (``qa.page_contract``).

Clean-room rewrite of the *method* of the page-level checks in
``win4r/video-director`` (MIT; see VIDEO_DIRECTOR_ATTRIBUTION.md):
a rendered page is judged against a contract -- DUR/FPS/seek/
READY/TEXTS -- instead of trusting that a render which produced a
file produced the right page. No text, code or script from the
source repository is copied here.

What this module judges is a *record*, never a live page: it has
no browser, no renderer and no screenshot pipeline, and it never
claims to have rendered anything. Two kinds of record exist, and
the verdict keeps them apart:

* A measured record carries a deterministic reverse render: the
  same page rendered in reverse order, frame by frame, whose
  hashes must match the forward render exactly. Only then is the
  determinism check a pass.
* A planned record carries no reverse render. The determinism
  check is then ``planned_not_measured`` (pass=None), never a
  pass and never a fabricated diff. ``video.code_render`` can
  only produce this kind of record today: it renders forward
  only, so its contract input (see
  ``build_page_contract_input`` there) honestly marks the
  reverse diff as planned, not measured.

The other checks are the same discipline: page errors are
zero-tolerance when a page-error list is supplied and
``planned_not_measured`` when no list is supplied (absence of
evidence is not evidence of no errors); fonts must be declared
ready; every TEXTS(t) entry must be held long enough to read
(the same hold formula as ``qa.timeline_gate``); every text box
must sit inside the frame; anchors must be identical across the
two renders that claim to show them, or the check is
undetermined on a single sample.

Verdict: ``"fail"`` when any check fails, ``"pass"`` only when
every check was measured and passed, ``"undetermined"``
otherwise. A record that *claims* a measured reverse diff but
supplies no reverse frame hashes fails outright: a claimed
measurement with no evidence is fabrication, not a gap.
"""

from __future__ import annotations

import json
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

CONTRACT_FIELDS = ("dur", "fps", "seek", "ready", "texts")
_CJK_RE = re.compile(r"[\u2e80-\u9fff\uf900-\ufaff]")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _read_time_required_sec(text: str) -> float:
    """Hold a text must get, in seconds (timeline-gate formula).

    Delegates to ``qa.timeline_gate`` so the two gates can never
    disagree about the same wording; falls back to the same
    formula locally only if that import fails.
    Composes (3O SPEC 1.2): read_time_required_sec.
    """
    try:
        from hevi.capabilities.timeline_gate import read_time_required_sec

        return read_time_required_sec(text)
    except Exception:
        words = len(str(text or "").strip().split()) or 0
        cjk = len(_CJK_RE.findall(str(text or "")))
        if cjk:
            words = max(words, len(str(text or "").strip()))
        return max(1.5, 1.0 + 0.3 * words)


def verify_reverse_render(
    forward_frames: Any, reverse_frames: Any
) -> dict[str, Any]:
    """Compare a forward frame-hash list with a reverse-render one.

    Each list holds ``{"t": ..., "sha256": ...}`` (``"hash"`` is
    accepted as an alias). The reverse render must cover exactly
    the same timestamps, in reverse order, with identical hashes.
    Returns ``{"status": "pass"|"fail"|"planned_not_measured", ...}``
    and never invents a diff: with no reverse list at all the
    result is planned, not measured.
    """
    if reverse_frames is None:
        return {
            "status": "planned_not_measured",
            "pass": None,
            "detail": "no reverse render supplied: determinism was not measured",
            "compared": 0,
            "mismatches": [],
        }
    if not isinstance(forward_frames, list) or not isinstance(reverse_frames, list):
        raise CapabilityError(
            "qa.page_contract: forward_frames and reverse_frames must be lists"
        )

    def _norm(frames: Any) -> list[tuple[Any, Any]]:
        out = []
        for entry in frames:
            if not isinstance(entry, dict):
                raise CapabilityError(
                    f"qa.page_contract: frame entry must be an object, got {entry!r}"
                )
            stamp = entry.get("t", entry.get("t_sec", entry.get("time")))
            digest = entry.get("sha256", entry.get("hash"))
            if stamp is None or digest is None:
                raise CapabilityError(
                    f"qa.page_contract: frame entry needs a time and a sha256: {entry!r}"
                )
            out.append((stamp, str(digest)))
        return out

    forward = _norm(forward_frames)
    reverse = _norm(reverse_frames)
    if not forward:
        return {"status": "planned_not_measured", "pass": None,
                "detail": "no forward frames supplied", "compared": 0,
                "mismatches": []}
    mismatches: list[dict[str, Any]] = []
    if len(reverse) != len(forward):
        mismatches.append({
            "reason": "frame count differs",
            "forward_count": len(forward),
            "reverse_count": len(reverse),
        })
    forward_by_t = dict(forward)
    if [t for t, _ in reverse] != [t for t, _ in reversed(forward)]:
        mismatches.append({"reason": "reverse render is not the forward times in reverse order"})
    for stamp, digest in reverse:
        if stamp in forward_by_t and forward_by_t[stamp] != digest:
            mismatches.append({"t": stamp, "reason": "hash differs between forward and reverse render"})
    if mismatches:
        return {"status": "fail", "pass": False,
                "detail": f"{len(mismatches)} reverse-render mismatch(es)",
                "compared": len(forward), "mismatches": mismatches}
    return {"status": "pass", "pass": True,
            "detail": f"{len(forward)} frames identical forward and in reverse order",
            "compared": len(forward), "mismatches": []}


def check_page_contract(
    record: dict[str, Any],
    *,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_fps: float | None = None,
    expected_dur: float | None = None,
) -> dict[str, Any]:
    """Judge one page record against the DUR/FPS/seek/READY/TEXTS contract."""
    if not isinstance(record, dict):
        raise CapabilityError("qa.page_contract: record must be an object (dict)")
    checks: dict[str, dict[str, Any]] = {}

    def _set(name: str, ok: bool | None, detail: str, extra: dict[str, Any] | None = None) -> None:
        entry: dict[str, Any] = {"pass": ok, "detail": detail}
        if extra:
            entry.update(extra)
        checks[name] = entry

    # Contract fields: DUR/FPS/seek/READY/TEXTS must be present.
    missing = [f for f in CONTRACT_FIELDS if f not in record]
    if missing:
        _set("contract_fields", False,
             f"missing contract fields: {', '.join(missing)} (need DUR/FPS/seek/READY/TEXTS)")
    else:
        _set("contract_fields", True, "DUR/FPS/seek/READY/TEXTS all present")

    width = record.get("w", record.get("width"))
    height = record.get("h", record.get("height"))
    fps = record.get("fps")
    dur = record.get("dur", record.get("duration_sec"))
    if expected_width is not None or expected_height is not None:
        ok = True
        bits = []
        if expected_width is not None:
            ok = ok and width == expected_width
            bits.append(f"width {width} vs {expected_width}")
        if expected_height is not None:
            ok = ok and height == expected_height
            bits.append(f"height {height} vs {expected_height}")
        _set("resolution", bool(ok), "; ".join(bits))
    elif _is_num(width) and _is_num(height) and float(width) > 0 and float(height) > 0:
        _set("resolution", True, f"frame {float(width):.0f}x{float(height):.0f} declared")
    else:
        _set("resolution", None, "no usable frame size in the record")
    if expected_fps is not None:
        _set("fps", bool(_is_num(fps) and float(fps) == float(expected_fps)),
             f"fps {fps} vs expected {expected_fps}")
    elif _is_num(fps) and float(fps) > 0:
        _set("fps", True, f"fps {float(fps)} declared")
    else:
        _set("fps", None, "no usable fps in the record")
    if expected_dur is not None:
        _set("duration", bool(_is_num(dur) and abs(float(dur) - float(expected_dur)) <= 0.25),
             f"dur {dur} vs expected {expected_dur} (tolerance 0.25s)")
    elif _is_num(dur) and float(dur) > 0:
        _set("duration", True, f"dur {float(dur)}s declared")
    else:
        _set("duration", None, "no usable duration in the record")

    # Seek: a declared seek list must exist and stay inside the film.
    seek = record.get("seek")
    if seek is None:
        _set("seek", None, "no seek list declared: seekability was not measured")
    elif not isinstance(seek, list):
        _set("seek", False, f"seek must be a list of times, got {seek!r}")
    elif not seek:
        _set("seek", None, "seek list is empty: seekability was not measured")
    elif _is_num(dur) and any(not _is_num(t) or float(t) < 0 or float(t) > float(dur) for t in seek):
        _set("seek", False, f"seek time outside duration {dur}: {seek!r}")
    else:
        _set("seek", True, f"{len(seek)} seek time(s) inside the film")

    # READY: fonts ready is a hard requirement when declared.
    ready = record.get("ready")
    if ready is None:
        _set("fonts_ready", None, "no READY declaration: font readiness was not measured")
    elif isinstance(ready, dict):
        fonts_ready = ready.get("fonts_ready", ready.get("fontsReady"))
        if fonts_ready is True:
            _set("fonts_ready", True, "fonts declared ready")
        elif fonts_ready is False:
            _set("fonts_ready", False, "fonts declared NOT ready: fallback text may render")
        else:
            _set("fonts_ready", None, "READY declares no fonts_ready flag")
    elif ready is True:
        _set("fonts_ready", True, "page declared ready")
    elif ready is False:
        _set("fonts_ready", False, "page declared NOT ready")
    else:
        _set("fonts_ready", None, f"READY value not understood: {ready!r}")

    # Page errors: zero tolerance when a list is supplied.
    page_errors = record.get("page_errors", record.get("errors"))
    if page_errors is None:
        _set("page_errors", None,
             "no page-error list supplied: page errors were not measured")
    elif not isinstance(page_errors, list):
        _set("page_errors", False, f"page_errors must be a list, got {page_errors!r}")
    elif page_errors:
        _set("page_errors", False,
             f"{len(page_errors)} page error(s): {page_errors}",
             {"errors": page_errors})
    else:
        _set("page_errors", True, "page-error list is empty (zero tolerance met)")

    # TEXTS(t): every entry read-time, in-bounds, with a text.
    texts = record.get("texts")
    if texts is None:
        _set("texts_read_time", None, "no TEXTS entries: read-time was not measured")
        _set("text_bounds", None, "no TEXTS entries: text bounds were not measured")
    elif not isinstance(texts, list):
        _set("texts_read_time", False, f"texts must be a list, got {texts!r}")
        _set("text_bounds", False, f"texts must be a list, got {texts!r}")
    else:
        read_problems: list[str] = []
        bound_problems: list[str] = []
        for idx, entry in enumerate(texts):
            if not isinstance(entry, dict):
                read_problems.append(f"TEXTS[{idx}] is not an object")
                continue
            text = entry.get("text", entry.get("content", ""))
            start, end = entry.get("start"), entry.get("end")
            if _is_num(start) and _is_num(end):
                hold = float(end) - float(start)
                required = _read_time_required_sec(str(text))
                if hold < required:
                    read_problems.append(
                        f"TEXTS[{idx}] held {hold:.2f}s, below read-time "
                        f"{required:.2f}s for {text!r:.40}"
                    )
            else:
                read_problems.append(f"TEXTS[{idx}] has no numeric start/end")
            box = entry.get("box")
            if box is not None and _is_num(width) and _is_num(height):
                coords = None
                if isinstance(box, dict):
                    if {"x", "y", "w", "h"} <= set(box):
                        coords = (box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])
                    elif {"x0", "y0", "x1", "y1"} <= set(box):
                        coords = (box["x0"], box["y0"], box["x1"], box["y1"])
                elif isinstance(box, (list, tuple)) and len(box) == 4:
                    coords = tuple(box)
                if coords is None or not all(_is_num(v) for v in coords):
                    bound_problems.append(f"TEXTS[{idx}] box not understood: {box!r}")
                else:
                    x0, y0, x1, y1 = (float(v) for v in coords)
                    if all(0 < v <= 1.0 for v in (x0, y0, x1, y1)):
                        x0, y0, x1, y1 = x0 * float(width), y0 * float(height), x1 * float(width), y1 * float(height)
                    if x0 < 0 or y0 < 0 or x1 > float(width) or y1 > float(height):
                        bound_problems.append(
                            f"TEXTS[{idx}] box {coords} exceeds frame "
                            f"{float(width):.0f}x{float(height):.0f}"
                        )
            elif box is None:
                bound_problems.append(f"TEXTS[{idx}] declares no box")
        if read_problems:
            _set("texts_read_time", False, "; ".join(read_problems))
        else:
            _set("texts_read_time", True,
                 f"{len(texts)} TEXTS entr(ies) held long enough to read")
        if bound_problems:
            _set("text_bounds", False, "; ".join(bound_problems))
        else:
            _set("text_bounds", True, f"{len(texts)} TEXTS box(es) inside the frame")

    # Anchors: identical across two samples, or undetermined.
    anchors = record.get("anchors")
    if anchors is None:
        _set("anchor_stability", None, "no anchors declared: stability was not measured")
    elif not isinstance(anchors, list):
        _set("anchor_stability", False, f"anchors must be a list, got {anchors!r}")
    else:
        drifts: list[str] = []
        for idx, entry in enumerate(anchors):
            if not isinstance(entry, dict):
                drifts.append(f"anchor[{idx}] is not an object")
                continue
            positions = entry.get("positions", entry.get("samples"))
            if positions is None:
                drifts.append(f"anchor[{idx}] has a single position sample: stability undetermined")
            elif isinstance(positions, list) and len(positions) >= 2:
                if any(p != positions[0] for p in positions[1:]):
                    drifts.append(f"anchor[{idx}] moved between samples: {positions!r}")
            else:
                drifts.append(f"anchor[{idx}] has a single position sample: stability undetermined")
        single_sample = any("single position sample" in d for d in drifts)
        moved = [d for d in drifts if "moved between" in d]
        if moved:
            _set("anchor_stability", False, "; ".join(moved))
        elif single_sample:
            _set("anchor_stability", None, "; ".join(drifts))
        elif drifts:
            _set("anchor_stability", False, "; ".join(drifts))
        else:
            _set("anchor_stability", True, f"{len(anchors)} anchor(s) stable across samples")

    # Deterministic reverse-render diff.
    reverse = record.get("reverse_render", record.get("reverse_diff"))
    if reverse is None:
        _set("reverse_render_diff", None,
             "no reverse render: determinism is planned_not_measured, never a pass",
             {"status": "planned_not_measured"})
    elif isinstance(reverse, dict) and reverse.get("status") == "planned_not_measured":
        _set("reverse_render_diff", None,
             str(reverse.get("detail") or "reverse render planned, not measured"),
             {"status": "planned_not_measured"})
    elif isinstance(reverse, dict) and "frames" in reverse:
        result = verify_reverse_render(
            record.get("forward_frames", record.get("frames")), reverse.get("frames"))
        _set("reverse_render_diff", result["pass"], result["detail"],
             {"status": result["status"], "mismatches": result["mismatches"]})
    elif isinstance(reverse, dict) and reverse.get("claimed_measured") is True:
        _set("reverse_render_diff", False,
             "record claims a measured reverse diff but supplies no reverse frame hashes",
             {"status": "fabrication_guard"})
    elif isinstance(reverse, list):
        result = verify_reverse_render(
            record.get("forward_frames", record.get("frames")), reverse)
        _set("reverse_render_diff", result["pass"], result["detail"],
             {"status": result["status"], "mismatches": result["mismatches"]})
    else:
        _set("reverse_render_diff", None,
             "reverse_render present but not understood: determinism was not measured",
             {"status": "planned_not_measured"})

    failed = [n for n, c in checks.items() if c["pass"] is False]
    undetermined = [n for n, c in checks.items() if c["pass"] is None]
    verdict = "fail" if failed else ("pass" if not undetermined else "undetermined")
    return {
        "capability": "qa.page_contract",
        "verdict": verdict,
        "checks": checks,
        "failed_checks": failed,
        "undetermined_checks": undetermined,
        "verdict_note": (
            "Fail: at least one contract check failed."
            if verdict == "fail" else
            "Pass: every contract check was measured and passed."
            if verdict == "pass" else
            "Undetermined: some checks had no evidence; they were "
            "not counted as passes. A reverse diff without a reverse "
            "render stays planned_not_measured."
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {}
    for key, conv in (("expected_width", int), ("expected_height", int)):
        if params.get(key) is not None:
            kwargs[key] = conv(params[key])
    for key in ("expected_fps", "expected_dur"):
        if params.get(key) is not None:
            kwargs[key] = float(params[key])
    report = check_page_contract(params.get("record", {}), **kwargs)
    report_path = out_dir / "page_contract_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": report["verdict"],
            "pass": report["verdict"] == "pass",
            "failed_checks": report["failed_checks"],
            "undetermined_checks": report["undetermined_checks"],
        },
    )


def register_page_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.page_contract",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "record": {"type": "object"},
                    "expected_width": {"type": "integer", "exclusiveMinimum": 0},
                    "expected_height": {"type": "integer", "exclusiveMinimum": 0},
                    "expected_fps": {"type": "number", "exclusiveMinimum": 0},
                    "expected_dur": {"type": "number", "exclusiveMinimum": 0},
                },
                "required": ["record"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Page contract: judges a plan/render record against "
                "DUR/FPS/seek/READY/TEXTS, with zero tolerance for "
                "supplied page errors, font-readiness, TEXTS(t) "
                "read-time and bounds, anchor stability, resolution, "
                "and a deterministic reverse-render diff. No reverse "
                "render means planned_not_measured, never a pass; a "
                "claimed diff with no hashes fails. Judges records "
                "only; no browser or renderer is driven."
            ),
            line="qa",
        )
    )
    return ["qa.page_contract"]


register_page_contract_capabilities_once()
