"""Colab hardware advisor (``model.colab_hardware_advisor``).

Clean-room rewrite of a method only: the idea of a hardware-selection
gatekeeper that classifies a job, checks it against caller-supplied
runtime measurements, blocks an expensive first download, warns when
a costly runtime is used for a small job, and suggests tuning for a
large-memory runtime. The method was described in the verification
report ``workspace/colab-ultra-workstation-check.md`` (2026-10-30),
which checked googlecolab/colab-mcp and googlecolab/google-colab-cli
(both Apache-2.0) and yuanyang749/colab-ultra-workstation (no
LICENSE file found, so no wording or code was copied from it).
Two items from that report are deliberately excluded here: the
third-party drive-mount extension (long-lived credential handling)
and any content about bypassing safety filtering. See
``COLAB_HARDWARE_ADVISOR_ATTRIBUTION.md``.

What this module is and is not:

* It is advice and gating only. It never switches a GPU, creates a
  runtime, or calls any Colab API. Switching a paid runtime must be
  done by a person (for example by saving a runtime-type change in
  the Colab web page) or by a CLI command the account owner
  explicitly authorises. Nothing here may silently spend the
  account owner's compute units.
* Every rate and balance figure comes from the caller, as a
  runtime-measured snapshot with a snapshot date. This module
  contains no price table, no default rate, and no estimated rate,
  and it never invents a fee figure. Published or third-party rate
  tables were found to contradict each other during verification,
  so a rate baked into this code would go stale and mislead.
* Memory estimates use caller-configurable coefficients and are
  labelled order-of-magnitude references only. The caller may
  override them; the defaults must not be treated as measured
  facts for any particular model.
* It does not freeze or settle money. That is
  ``pipeline.spend_ledger``'s job, and confirmation before a paid
  batch is ``pipeline.spend_brake``'s job. This module only
  produces the estimate the caller can feed into those gates.
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

# Task classes. Classification is by the task's nature and the
# model size the caller declares; an unrecognised task is reported
# as "unknown" and gets no card recommendation rather than a guess.
TASK_TYPES = (
    "download",
    "light_video",
    "heavy_video",
    "llm_small",
    "llm_medium",
    "llm_large",
)

# A runtime at or above this measured rate is treated as expensive
# for the download guard and the oversized-job warning. The value is
# a policy threshold supplied by the verification report's guard
# rule, not a price from any provider's table.
EXPENSIVE_RATE_THRESHOLD_CCU_PER_HOUR = 5.0

# At or above this much GPU memory, the tuning advice suggests
# keeping the model resident and using reduced-precision compute
# where the model supports it. Advisory only; nothing is changed.
LARGE_VRAM_THRESHOLD_GB = 45.0

# Small / medium boundary in declared model size (billions of
# parameters). A language model below this is "small"; at or above
# it and below the large boundary it is "medium".
_SMALL_MODEL_MAX_PARAMS_BILLION = 10.0
_LARGE_MODEL_MIN_PARAMS_BILLION = 40.0

# Video-generation boundary: a video model at or above this size
# (billions of parameters, as declared by the caller) is "heavy".
_HEAVY_VIDEO_MIN_PARAMS_BILLION = 10.0

# Order-of-magnitude memory coefficients: gigabytes per billion
# parameters. Defaults are reference values only; the caller may
# override them. They are not measurements of any named model.
_DEFAULT_DTYPE_FACTORS = {"bf16": 2.4, "fp8": 1.2, "fp4": 0.7}

# Recommendation tiers. These are classes of runtime, not promises
# about availability: the caller must confirm that a tier is
# actually allocatable and what its current measured rate is.
_TIERS = ("cpu", "small_gpu", "large_vram_gpu")
_TIER_EXAMPLE_CARDS = {
    "cpu": ["cpu"],
    "small_gpu": ["t4", "l4"],
    "large_vram_gpu": ["g4", "a100", "h100"],
}


def _fail(message: str) -> None:
    raise CapabilityError(f"model.colab_hardware_advisor: {message}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def classify_task(task: Any) -> dict[str, Any]:
    """Classify a job into one of the six task classes.

    ``task`` is a caller-supplied description. Recognised signals:

    * ``task_type`` naming one of the six classes directly;
    * ``purpose``: ``"download"``, ``"video"`` or ``"llm"``;
    * ``is_first_download``: true when the job is a first download
      of model weights (no generation in the same job);
    * ``model_params_billion``: declared size for a language model;
    * ``video_model_params_billion``: declared size for a video
      model;
    * ``output_seconds`` is recorded but never used to guess a
      class on its own.

    Anything that does not match a rule is ``"unknown"`` with the
    reasons listed. Classification never invents a model size.
    """
    reasons: list[str] = []
    if not isinstance(task, dict):
        return {
            "task_type": "unknown",
            "unknown": True,
            "reasons": ["task: task description is not an object"],
        }
    declared = task.get("task_type")
    if declared is not None:
        if declared in TASK_TYPES:
            return {
                "task_type": declared,
                "unknown": False,
                "reasons": [f"task_type: caller declared {declared!r}"],
            }
        return {
            "task_type": "unknown",
            "unknown": True,
            "reasons": [f"task_type: unrecognised task type {declared!r}"],
        }
    if task.get("is_first_download") is True or task.get("purpose") == "download":
        reasons.append(
            "download: first download of model weights, no generation "
            "in this job"
        )
        return {"task_type": "download", "unknown": False, "reasons": reasons}
    purpose = task.get("purpose")
    if purpose == "llm":
        params = task.get("model_params_billion")
        if not _is_number(params):
            return {
                "task_type": "unknown",
                "unknown": True,
                "reasons": [
                    "llm: model_params_billion was not supplied, so no "
                    "size class can be assigned"
                ],
            }
        if params < _SMALL_MODEL_MAX_PARAMS_BILLION:
            reasons.append(
                f"llm_small: declared {params}B is below "
                f"{_SMALL_MODEL_MAX_PARAMS_BILLION}B"
            )
            return {"task_type": "llm_small", "unknown": False, "reasons": reasons}
        if params < _LARGE_MODEL_MIN_PARAMS_BILLION:
            reasons.append(
                f"llm_medium: declared {params}B is at least "
                f"{_SMALL_MODEL_MAX_PARAMS_BILLION}B and below "
                f"{_LARGE_MODEL_MIN_PARAMS_BILLION}B"
            )
            return {"task_type": "llm_medium", "unknown": False, "reasons": reasons}
        reasons.append(
            f"llm_large: declared {params}B is at least "
            f"{_LARGE_MODEL_MIN_PARAMS_BILLION}B"
        )
        return {"task_type": "llm_large", "unknown": False, "reasons": reasons}
    if purpose == "video":
        params = task.get("video_model_params_billion")
        if params is None:
            params = task.get("model_params_billion")
        if not _is_number(params):
            return {
                "task_type": "unknown",
                "unknown": True,
                "reasons": [
                    "video: no video model size was supplied, so no "
                    "video class can be assigned"
                ],
            }
        if params >= _HEAVY_VIDEO_MIN_PARAMS_BILLION:
            reasons.append(
                f"heavy_video: declared video model {params}B is at "
                f"least {_HEAVY_VIDEO_MIN_PARAMS_BILLION}B"
            )
            return {"task_type": "heavy_video", "unknown": False, "reasons": reasons}
        reasons.append(
            f"light_video: declared video model {params}B is below "
            f"{_HEAVY_VIDEO_MIN_PARAMS_BILLION}B"
        )
        return {"task_type": "light_video", "unknown": False, "reasons": reasons}
    return {
        "task_type": "unknown",
        "unknown": True,
        "reasons": [
            "task: purpose was not supplied or not recognised "
            "(expected 'download', 'video' or 'llm'); no class assigned"
        ],
    }


def validate_runtime(runtime: Any) -> dict[str, Any]:
    """Validate a caller-supplied runtime snapshot.

    Required: ``gpu_name`` (non-empty string), ``vram_gb`` (a
    positive number), ``rate_ccu_per_hour`` (a number at or above
    zero, measured at runtime), ``snapshot_date`` (non-empty
    string, so the rate can be recognised as a snapshot, not a
    standing price). ``balance_ccu`` is optional. A missing rate
    is an error: this module never falls back to a baked-in rate.
    Returns a normalised copy of the snapshot.
    """
    if not isinstance(runtime, dict):
        _fail("runtime: runtime snapshot is not an object")
    problems: list[str] = []
    gpu_name = runtime.get("gpu_name")
    if not isinstance(gpu_name, str) or not gpu_name.strip():
        problems.append("gpu_name: a non-empty runtime name is required")
    vram = runtime.get("vram_gb")
    if not _is_number(vram) or float(vram) <= 0:
        problems.append("vram_gb: a positive number of gigabytes is required")
    rate = runtime.get("rate_ccu_per_hour")
    if not _is_number(rate) or float(rate) < 0:
        problems.append(
            "rate_ccu_per_hour: a runtime-measured rate is required; "
            "no default rate is used"
        )
    snapshot_date = runtime.get("snapshot_date")
    if not isinstance(snapshot_date, str) or not snapshot_date.strip():
        problems.append(
            "snapshot_date: a snapshot date is required so the rate "
            "is read as a dated measurement, not a standing price"
        )
    balance = runtime.get("balance_ccu")
    if balance is not None and (not _is_number(balance) or float(balance) < 0):
        problems.append("balance_ccu: when supplied, it must be at or above zero")
    if problems:
        _fail("runtime: " + "; ".join(problems))
    normalised: dict[str, Any] = {
        "gpu_name": str(gpu_name).strip(),
        "vram_gb": float(vram),
        "rate_ccu_per_hour": float(rate),
        "snapshot_date": str(snapshot_date).strip(),
        "rate_source": "caller_supplied_runtime_snapshot",
    }
    if balance is not None:
        normalised["balance_ccu"] = float(balance)
    if runtime.get("high_memory") is not None:
        normalised["high_memory"] = bool(runtime["high_memory"])
    return normalised


def estimate_vram_gb(
    params_billion: Any,
    *,
    dtype: str = "bf16",
    dtype_factors: dict[str, float] | None = None,
    kv_reserve_gb: float = 0.0,
) -> dict[str, Any]:
    """Estimate GPU memory for a declared model size.

    The estimate is ``params_billion * factor + kv_reserve_gb``.
    Factors are caller-configurable; the defaults are
    order-of-magnitude references only and are labelled as such in
    the result. ``kv_reserve_gb`` is the caller's allowance for
    key/value cache and activations (default zero: no allowance
    invented). An unknown dtype or a missing size is an error.
    """
    factors = dict(_DEFAULT_DTYPE_FACTORS)
    if dtype_factors:
        factors.update(dtype_factors)
    if not _is_number(params_billion) or float(params_billion) <= 0:
        _fail("estimate_vram_gb: params_billion must be a positive number")
    if dtype not in factors:
        _fail(
            f"estimate_vram_gb: unknown dtype {dtype!r}; known: "
            f"{', '.join(sorted(factors))}"
        )
    if not _is_number(kv_reserve_gb) or float(kv_reserve_gb) < 0:
        _fail("estimate_vram_gb: kv_reserve_gb must be at or above zero")
    estimate = float(params_billion) * float(factors[dtype]) + float(kv_reserve_gb)
    return {
        "params_billion": float(params_billion),
        "dtype": dtype,
        "factor_gb_per_billion": float(factors[dtype]),
        "kv_reserve_gb": float(kv_reserve_gb),
        "estimated_vram_gb": estimate,
        "estimate_kind": "order_of_magnitude_reference_only",
        "factors_source": "caller_supplied_or_default_reference",
    }


def recommend_tier(task_type: str, estimate: dict[str, Any] | None = None) -> dict[str, Any]:
    """Recommend a runtime tier for a classified task.

    The tier is a class of runtime plus the minimum memory the
    estimate calls for; example card names are illustrations only.
    An unknown task gets no recommendation. The recommendation
    never switches anything: the caller (a person) chooses and
    confirms the actual runtime.
    """
    if task_type == "unknown":
        return {
            "tier": None,
            "minimum_vram_gb": None,
            "candidate_cards": [],
            "reason": "unknown task: no runtime tier can be recommended "
            "without a classification",
        }
    tier_map = {
        "download": "cpu",
        "llm_small": "small_gpu",
        "light_video": "small_gpu",
        "llm_medium": "large_vram_gpu",
        "llm_large": "large_vram_gpu",
        "heavy_video": "large_vram_gpu",
    }
    tier = tier_map[task_type]
    minimum = None
    if estimate is not None:
        minimum = estimate.get("estimated_vram_gb")
    reasons = {
        "download": "downloads need no accelerator; a paid runtime "
        "would burn units while only moving bytes",
        "llm_small": "a small model fits an entry-level accelerator; "
        "a large-memory runtime is not needed for it",
        "light_video": "a light video model fits an entry-level "
        "accelerator",
        "llm_medium": "a medium model needs a large-memory runtime "
        "to stay resident without offloading",
        "llm_large": "a large model needs a large-memory runtime; "
        "check the estimate against the measured memory before "
        "starting",
        "heavy_video": "a heavy video model needs a large-memory "
        "runtime to keep the full pipeline resident",
    }
    return {
        "tier": tier,
        "minimum_vram_gb": minimum,
        "candidate_cards": list(_TIER_EXAMPLE_CARDS[tier]),
        "candidate_cards_note": "examples only; confirm allocatability "
        "and the current measured rate at runtime",
        "reason": reasons[task_type],
    }


def estimate_cost(
    runtime: dict[str, Any],
    *,
    duration_hours: Any = None,
    duration_seconds: Any = None,
) -> dict[str, Any]:
    """Estimate compute units for a job from the snapshot rate.

    The caller supplies a duration; with no duration no estimate
    is invented. The result carries the snapshot date so the
    estimate is traceable to the measurement it used.
    """
    if duration_hours is None and duration_seconds is None:
        return {
            "estimated_ccu": None,
            "estimated_ccu_low": None,
            "estimated_ccu_high": None,
            "reason": "no duration was supplied, so no cost estimate "
            "is invented",
            "rate_ccu_per_hour": runtime["rate_ccu_per_hour"],
            "snapshot_date": runtime["snapshot_date"],
        }
    if duration_hours is not None:
        if not _is_number(duration_hours) or float(duration_hours) < 0:
            _fail("estimate_cost: duration_hours must be at or above zero")
        hours = float(duration_hours)
    else:
        if not _is_number(duration_seconds) or float(duration_seconds) < 0:
            _fail("estimate_cost: duration_seconds must be at or above zero")
        hours = float(duration_seconds) / 3600.0
    point = runtime["rate_ccu_per_hour"] * hours
    return {
        "estimated_ccu": point,
        "estimated_ccu_low": point,
        "estimated_ccu_high": point,
        "duration_hours": hours,
        "rate_ccu_per_hour": runtime["rate_ccu_per_hour"],
        "snapshot_date": runtime["snapshot_date"],
        "rate_source": "caller_supplied_runtime_snapshot",
    }


def check_download_guard(
    task_type: str,
    runtime: dict[str, Any],
    *,
    is_first_download: bool = True,
    force: Any = False,
) -> dict[str, Any]:
    """Hard guard against downloading on an expensive runtime.

    Blocked when the task is a first download, the measured rate
    is at or above the expensive threshold, and ``force`` is not
    exactly ``True``. An explicit ``force=True`` from the caller
    is recorded in the result (``forced: true``) rather than
    hidden. This guard covers the download call only; it does not
    police idling, generation, or shutdown, and the caller must
    still release the runtime itself.
    """
    rate = runtime["rate_ccu_per_hour"]
    expensive = rate >= EXPENSIVE_RATE_THRESHOLD_CCU_PER_HOUR
    if task_type == "download" and is_first_download and expensive and force is not True:
        return {
            "blocked": True,
            "forced": False,
            "reason": (
                f"download guard: current runtime {runtime['gpu_name']} "
                f"is measured at {rate} compute units per hour, at or "
                f"above the expensive threshold "
                f"{EXPENSIVE_RATE_THRESHOLD_CCU_PER_HOUR}; first "
                "downloads of model weights should run on a "
                "no-accelerator runtime. Switch to a CPU runtime "
                "first, or pass force=True explicitly to record an "
                "override."
            ),
        }
    forced = task_type == "download" and is_first_download and expensive and force is True
    return {
        "blocked": False,
        "forced": forced,
        "reason": (
            "download guard: allowed"
            + (" (explicit force override recorded)" if forced else "")
            + ("" if expensive else " (runtime below the expensive threshold)")
        ),
    }


def check_oversized_warning(task_type: str, runtime: dict[str, Any]) -> dict[str, Any]:
    """Warn when a costly runtime runs a small job.

    A runtime counts as costly here when its measured rate is at
    or above the expensive threshold or its memory is at or above
    the large-memory threshold. Small jobs are ``llm_small`` and
    ``light_video``. The warning names a cheaper tier to consider;
    it never downgrades anything by itself.
    """
    costly = (
        runtime["rate_ccu_per_hour"] >= EXPENSIVE_RATE_THRESHOLD_CCU_PER_HOUR
        or runtime["vram_gb"] >= LARGE_VRAM_THRESHOLD_GB
    )
    small = task_type in ("llm_small", "light_video")
    if costly and small:
        return {
            "warning": True,
            "reason": (
                f"oversized runtime: {runtime['gpu_name']} "
                f"({runtime['vram_gb']} GB, "
                f"{runtime['rate_ccu_per_hour']} compute units per "
                f"hour) is a costly runtime for a {task_type} job; "
                "consider a small_gpu tier or a CPU runtime and "
                "re-check the measured rate before starting"
            ),
            "downgrade_suggestion": "small_gpu",
        }
    return {
        "warning": False,
        "reason": "oversized runtime: no warning; the runtime is not "
        "costly for this task class, or the task is not a small job",
        "downgrade_suggestion": None,
    }


def tuning_advice(runtime: dict[str, Any]) -> dict[str, Any]:
    """Suggest tuning for a large-memory runtime. Advisory only.

    At or above the large-memory threshold, the advice suggests
    keeping the model resident (no CPU offload) and using
    reduced-precision compute where the model supports it. Below
    the threshold it makes no such suggestion. This function
    returns suggestions; it never changes the caller's config.
    """
    if runtime["vram_gb"] >= LARGE_VRAM_THRESHOLD_GB:
        return {
            "suggest_cpu_offload": False,
            "suggest_reduced_precision": True,
            "suggested_dtypes": ["fp8", "fp4"],
            "applies": True,
            "reason": (
                f"tuning: {runtime['vram_gb']} GB is at or above the "
                f"large-memory threshold "
                f"{LARGE_VRAM_THRESHOLD_GB} GB, so keeping the model "
                "resident and using reduced-precision compute where "
                "the model supports it is suggested. Advisory only; "
                "the caller's configuration is unchanged."
            ),
        }
    return {
        "suggest_cpu_offload": None,
        "suggest_reduced_precision": False,
        "suggested_dtypes": [],
        "applies": False,
        "reason": (
            f"tuning: {runtime['vram_gb']} GB is below the "
            f"large-memory threshold {LARGE_VRAM_THRESHOLD_GB} GB, "
            "so no resident-model tuning is suggested here"
        ),
    }


def spend_brake_input(advice: dict[str, Any]) -> dict[str, Any]:
    """Shape an advice report for ``pipeline.spend_brake``.

    Returns only the estimate fields a caller needs alongside the
    brake's own inputs (storyboard, confirmation, smoke result).
    It performs no freeze, no settle, and no approval; the brake
    itself still decides. A blocked download has no spend-brake
    input at all, because the job must not be presented for
    confirmation in the first place.
    """
    if advice.get("download_guard", {}).get("blocked"):
        return {
            "spend_brake_ready": False,
            "reason": "download guard blocked the job; do not present "
            "it to the spend brake",
        }
    cost = advice.get("cost_estimate", {})
    return {
        "spend_brake_ready": cost.get("estimated_ccu") is not None,
        "estimated_ccu_low": cost.get("estimated_ccu_low"),
        "estimated_ccu_high": cost.get("estimated_ccu_high"),
        "rate_snapshot_date": cost.get("snapshot_date"),
        "balance_ccu": advice.get("runtime", {}).get("balance_ccu"),
        "note": "feed this estimate plus the storyboard, the exact-True "
        "confirmation, and the smoke result to pipeline.spend_brake; "
        "this module approves nothing and freezes nothing",
    }


def advise(
    task: Any,
    runtime: Any,
    *,
    duration_hours: Any = None,
    duration_seconds: Any = None,
    dtype: str = "bf16",
    dtype_factors: dict[str, float] | None = None,
    kv_reserve_gb: float = 0.0,
    force_download: Any = False,
) -> dict[str, Any]:
    """Full advice report for one job on one measured runtime.

    Runs classification, runtime validation, memory estimation
    (when a size was declared), tier recommendation, cost
    estimation, the three gates, and the spend-brake shaping, in
    that order. A blocked download still returns the full report
    with ``download_guard.blocked`` set, so the caller can show
    the reason instead of guessing. No runtime is switched, no
    instance is created, and no external service is called.
    """
    classification = classify_task(task)
    task_type = classification["task_type"]
    checked_runtime = validate_runtime(runtime)
    estimate = None
    params = None
    if isinstance(task, dict):
        if task_type.startswith("llm"):
            params = task.get("model_params_billion")
        elif task_type in ("light_video", "heavy_video"):
            params = task.get("video_model_params_billion")
            if params is None:
                params = task.get("model_params_billion")
    if params is not None:
        estimate = estimate_vram_gb(
            params, dtype=dtype, dtype_factors=dtype_factors,
            kv_reserve_gb=kv_reserve_gb,
        )
        estimate["fits_runtime"] = (
            estimate["estimated_vram_gb"] <= checked_runtime["vram_gb"]
        )
        estimate["shortfall_gb"] = max(
            0.0, estimate["estimated_vram_gb"] - checked_runtime["vram_gb"]
        )
    recommendation = recommend_tier(task_type, estimate)
    cost = estimate_cost(
        checked_runtime,
        duration_hours=duration_hours,
        duration_seconds=duration_seconds,
    )
    is_first = bool(task.get("is_first_download")) if isinstance(task, dict) else False
    if task_type == "download":
        is_first = True
    guard = check_download_guard(
        task_type, checked_runtime,
        is_first_download=is_first, force=force_download,
    )
    warning = check_oversized_warning(task_type, checked_runtime)
    tuning = tuning_advice(checked_runtime)
    balance_note = None
    if (
        checked_runtime.get("balance_ccu") is not None
        and cost.get("estimated_ccu_high") is not None
        and checked_runtime["balance_ccu"] < cost["estimated_ccu_high"]
    ):
        balance_note = (
            "balance: measured balance is below the estimated cost; "
            "confirm the budget before starting"
        )
    report: dict[str, Any] = {
        "task_type": task_type,
        "classification": classification,
        "runtime": checked_runtime,
        "memory_estimate": estimate,
        "recommendation": recommendation,
        "cost_estimate": cost,
        "download_guard": guard,
        "oversized_warning": warning,
        "tuning_advice": tuning,
        "balance_note": balance_note,
        "no_switching_notice": (
            "this module switches no runtime and calls no Colab API; "
            "a paid runtime change must be made by a person saving "
            "the change in the Colab page, or by a CLI command the "
            "account owner explicitly authorises"
        ),
    }
    report["spend_brake_input"] = spend_brake_input(report)
    return report


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    action = params.get("action", "advise")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if action == "advise":
        result: dict[str, Any] = {
            "action": "advise",
            "advice": advise(
                params.get("task", {}),
                params.get("runtime", {}),
                duration_hours=params.get("duration_hours"),
                duration_seconds=params.get("duration_seconds"),
                dtype=params.get("dtype", "bf16"),
                dtype_factors=params.get("dtype_factors"),
                kv_reserve_gb=float(params.get("kv_reserve_gb", 0.0)),
                force_download=params.get("force_download", False),
            ),
        }
    elif action == "classify":
        result = {"action": "classify", "classification": classify_task(params.get("task", {}))}
    else:
        raise CapabilityError(
            f"model.colab_hardware_advisor: unknown action {action!r}; "
            "known: advise, classify"
        )
    report_path = out_dir / "colab_hardware_advisor_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path)},
    )


def register_colab_hardware_advisor_capabilities_once() -> list[str]:
    """Register model.colab_hardware_advisor exactly once (report only)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="model.colab_hardware_advisor",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "task": {"type": "object"},
                    "runtime": {"type": "object"},
                    "duration_hours": {"type": "number"},
                    "duration_seconds": {"type": "number"},
                    "dtype": {"type": "string"},
                    "dtype_factors": {"type": "object"},
                    "kv_reserve_gb": {"type": "number"},
                    "force_download": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Colab hardware advisor (advice and gating only): "
                "classifies a job into download / light_video / "
                "heavy_video / llm_small / llm_medium / llm_large, "
                "checks it against a caller-supplied runtime "
                "snapshot (name, memory, measured rate, snapshot "
                "date), blocks a first download on an expensive "
                "runtime unless explicitly forced, warns when a "
                "costly runtime runs a small job, and suggests "
                "resident-model tuning on large-memory runtimes. "
                "No price table is baked in; rates always come "
                "from the caller. Switches no runtime and calls "
                "no Colab API. Report only; never generates media."
            ),
            line="model",
        )
    )
    return ["model.colab_hardware_advisor"]


register_colab_hardware_advisor_capabilities_once()
