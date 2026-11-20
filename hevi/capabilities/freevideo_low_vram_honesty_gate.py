"""Low-VRAM H3 honesty gate (``qa.freevideo_low_vram_honesty_gate``).

"8 GB can run H3" is true only under streaming residency,
and only with its conditions stated: it is slow, and disk
speed is the main bottleneck. In the reviewer's own words,
a low-VRAM claim must carry the hardware it ran on, the
quality tier, and a time estimate — a 15-second Max render
on a 10 GB card took about 33 minutes in community testing,
so a claim of a few minutes for that shape is understated
and fails. A claim that the run is free, or zero-cost, fails:
disk, power, and time are real costs even when no API is
billed. The gate judges claim descriptions only; it never
runs a render.

Clean-room restatement of the FlashML-org/FreeVideo method
(see ``FREEVIDEO_ATTRIBUTION.md``); no upstream code appears
here.
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

MIN_VRAM_GIB = 8.0
MIN_HOST_RAM_GIB = 16.0
SLOW_DISK_READ_MBPS = 110.0
MAX_10GB_15S_MINUTES = 30.0
QUALITY_LEVELS: frozenset[str] = frozenset({"Light", "Medium", "High", "Max"})


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_freevideo_low_vram_claim(claim: Any) -> dict[str, Any]:
    """Validate a low-VRAM H3 run claim.

    Verdicts are ``pass`` / ``fail`` only. A claim fails when
    VRAM is below 8 GiB or host RAM below 16 GiB, when the
    quality tier is unknown, when it claims zero cost, when
    a 15-second-or-longer Max render on a 10 GiB-or-smaller
    card is estimated under 30 minutes, or when a slow disk
    (under 110 MB/s) is reported without acknowledging disk
    streaming as the bottleneck.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(claim, dict):
        return fail("claim_not_object", "low-VRAM claim must be a JSON object")
    for field in ("vram_gib", "host_ram_gib", "quality", "seconds"):
        if field not in claim:
            return fail("claim_field_missing", f"low-VRAM claim must carry {field!r}")
    vram = claim["vram_gib"]
    host_ram = claim["host_ram_gib"]
    if not _is_number(vram) or vram < MIN_VRAM_GIB:
        return fail(
            "vram_below_minimum",
            f"low-VRAM runs need at least {MIN_VRAM_GIB} GiB of VRAM, got {vram}",
        )
    if not _is_number(host_ram) or host_ram < MIN_HOST_RAM_GIB:
        return fail(
            "host_ram_below_minimum",
            f"low-VRAM runs need at least {MIN_HOST_RAM_GIB} GiB of host RAM, got {host_ram}",
        )
    if claim["quality"] not in QUALITY_LEVELS:
        return fail(
            "quality_unknown",
            f"quality must be one of Light, Medium, High, Max, got {claim['quality']!r}",
        )
    if not _is_number(claim["seconds"]) or claim["seconds"] <= 0:
        return fail("seconds_invalid", "seconds must be a positive number")
    if claim.get("zero_cost_claim") is True:
        return fail(
            "zero_cost_claim_refused",
            "a low-VRAM run is not zero-cost: disk, power, and time "
            "are real costs even when no API is billed",
        )
    estimated = claim.get("estimated_minutes")
    if (
        claim["quality"] == "Max"
        and vram <= 10
        and claim["seconds"] >= 15
        and estimated is not None
        and _is_number(estimated)
        and estimated < MAX_10GB_15S_MINUTES
    ):
        return fail(
            "time_estimate_understated",
            "a 15-second Max render on a 10 GiB card took about 33 "
            f"minutes in community testing; {estimated} minutes understates it",
        )
    disk_read = claim.get("disk_read_mbps")
    if (
        disk_read is not None
        and _is_number(disk_read)
        and disk_read < SLOW_DISK_READ_MBPS
        and claim.get("disk_streaming_acknowledged") is not True
    ):
        return fail(
            "disk_bottleneck_unacknowledged",
            f"disk read {disk_read} MB/s is below {SLOW_DISK_READ_MBPS} MB/s, "
            "so disk streaming must be acknowledged as the bottleneck",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_freevideo_low_vram_claim(params.get("claim"))
    report_path = out_dir / "freevideo_low_vram_honesty_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_freevideo_low_vram_honesty_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.freevideo_low_vram_honesty_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "claim": {"type": "object"},
                },
                "required": ["claim"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "FreeVideo low-VRAM honesty gate: 8 GiB VRAM and 16 "
                "GiB host RAM minimums, no zero-cost claims, Max on "
                "a 10 GiB card needs an honest time estimate, slow "
                "disk must be acknowledged as the bottleneck."
            ),
        )
    )
    return ["qa.freevideo_low_vram_honesty_gate"]


__all__ = [
    "MAX_10GB_15S_MINUTES",
    "MIN_HOST_RAM_GIB",
    "MIN_VRAM_GIB",
    "QUALITY_LEVELS",
    "SLOW_DISK_READ_MBPS",
    "check_freevideo_low_vram_claim",
    "register_freevideo_low_vram_honesty_gate_capabilities_once",
]
