#!/usr/bin/env python3
"""Fail-closed second independent provider qualification audit (Track 4).

Classifies every video-provider candidate for the case corpus against the
honesty bar in docs/VIDEO-INTELLIGENCE-FINAL-CLOSURE.md:

  A second independent provider is counted only after a real, authorized
  qualification run through the canonical durable case_reproduction path.

Status vocabulary (candidates):
  BASELINE_QUALIFIED            first independent provider already counted
  FREE_LOCAL_RUNNABLE           free local path can run a real durable repro now
  OWNER_BLOCKED_NO_CREDENTIAL   required credential absent
  OWNER_BLOCKED_SPEND           credentials present; real run spends money
  ENV_BLOCKED                   hardware/tool absent; classified, not fail-closed
  NOT_REGISTERED_VIDEO          not registered as a generic video provider

The audit never prints secret values — only PRESENT/ABSENT for env names.
Corpus projections are read live (no hardcoded counts).

Exit 0 when software checks are healthy; ENV_BLOCKED / OWNER_* candidates
are classification rows, not gate failures.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]

# First provider that already produced the corpus (history fact, not a claim).
BASELINE_PROVIDER = "hyperframes"

# Env names only — values never leave this process.
_CREDENTIAL_ENVS: dict[str, list[str]] = {
    "happyhorse_1_1": ["WAVESPEED_API_KEY"],
    "wan_2_7": ["WAVESPEED_API_KEY"],
    "veo3": ["FAL_API_KEY"],
    "kling_v2": ["FAL_API_KEY"],
    "hailuo": ["FAL_API_KEY"],
    "ltx2_cloud": ["FAL_API_KEY"],
    "wan_cloud": ["FAL_API_KEY"],
    "happyhorse_1_1_maas": ["ALIBABA_MAAS_API_KEY"],
    "happyhorse_1_1_maas_lock": ["ALIBABA_MAAS_API_KEY"],
    "wan_2_7_maas": ["ALIBABA_MAAS_API_KEY"],
    "h3_local": ["H3_COMFY_URL"],
    "wan_local": [],
    "ltx2_local": [],
    "manim": [],
    "hyperframes": [],
    "remotion": [],
    "ffmpeg": [],
    "motion_graphics": [],
}

# Candidates that would spend owner budget if a real run executes.
_SPEND_CANDIDATES = {
    "veo3",
    "kling_v2",
    "hailuo",
    "ltx2_cloud",
    "wan_cloud",
    "happyhorse_1_1_maas",
    "happyhorse_1_1_maas_lock",
    "wan_2_7_maas",
}

# GPU / local-model dependents (classified ENV_BLOCKED when hardware down).
_GPU_LOCAL = {"h3_local", "wan_local", "ltx2_local"}


def _env_present(name: str) -> bool:
    return bool((os.environ.get(name) or "").strip())


def _credential_matrix(provider: str) -> dict[str, str]:
    envs = _CREDENTIAL_ENVS.get(provider, [])
    if not envs:
        return {}
    return {name: ("PRESENT" if _env_present(name) else "ABSENT") for name in envs}


def _gpu_ok() -> tuple[bool, str]:
    smi = shutil.which("nvidia-smi")
    if smi is None:
        return False, "nvidia-smi absent"
    try:
        proc = subprocess.run([smi, "-L"], capture_output=True, text=True, timeout=8)
        if proc.returncode == 0 and (proc.stdout or "").strip():
            return True, "nvidia-smi ok"
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return False, f"nvidia-smi rc={proc.returncode}: {detail[0] if detail else 'no output'}"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"nvidia-smi failed: {type(exc).__name__}: {exc}"


def _url_reachable(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, method="GET"), timeout=4
        ) as response:
            return True, f"HTTP_{response.status}"
    except urllib.error.HTTPError as exc:
        return exc.code < 500, f"HTTP_{exc.code}"
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return False, type(exc).__name__


def _registered_video_providers() -> tuple[list[str], str | None]:
    try:
        from obase.provider_registry import ProviderRegistry

        from hevi.providers.registry import register_all_providers

        register_all_providers()
        reg = ProviderRegistry.get()
        names = sorted(
            {
                name
                for category, name in reg.list_providers("video") or []
                if category == "video"
            }
        )
        return names, None
    except Exception as exc:  # audit records, never raises
        return [], f"{type(exc).__name__}: {exc}"


def _capability_modes(provider: str) -> list[str] | None:
    try:
        from hevi.video.capability_guard import PROVIDER_LIMITS

        limits = PROVIDER_LIMITS.get(provider)
        if limits is None:
            return None
        return sorted(limits.modes)
    except Exception:
        return None


def _probe_free_local(provider: str) -> dict[str, Any] | None:
    """Real, free local probe for manim only (no spend, no GPU)."""
    if provider != "manim":
        return None
    output = Path("/tmp/hevi-provider-probes/manim-audit.mp4")
    try:
        from hevi.providers.manim.provider import manim_generate

        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()
        started = time.perf_counter()
        asyncio.run(
            manim_generate(
                prompt="HEVI second-provider audit probe",
                output_path=output,
                duration_s=2.0,
                width=640,
                height=360,
                fps=24,
                quality="low",
            )
        )
        ok = output.is_file() and output.stat().st_size > 0
        return {
            "passed": ok,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "bytes": output.stat().st_size if ok else 0,
            "error": None if ok else "empty_output",
        }
    except Exception as exc:
        return {"passed": False, "error": f"{type(exc).__name__}: {exc}"}


def _classify(
    provider: str,
    *,
    registered: bool,
    gpu_ok: bool,
    gpu_detail: str,
    probe: bool,
) -> dict[str, Any]:
    credentials = _credential_matrix(provider)
    modes = _capability_modes(provider)
    record: dict[str, Any] = {
        "provider": provider,
        "registered_video": registered,
        "credential_env": credentials,
        "capability_modes": modes,
        "probe": None,
        "status": "NOT_REGISTERED_VIDEO",
        "reason": "not registered as generic video provider",
    }

    if not registered:
        if provider == "remotion":
            record["reason"] = (
                "readiness READY via hevi-remotion npx render, but no generic "
                "video registration and no prompt→composition compiler"
            )
        elif provider == "ffmpeg":
            record["reason"] = "helper tool, not a registered video provider"
        elif provider == "motion_graphics":
            record["reason"] = (
                "production_source name, not a registered video provider "
                "(uses remotion assembly path)"
            )
        return record

    if provider == BASELINE_PROVIDER:
        record["status"] = "BASELINE_QUALIFIED"
        record["reason"] = (
            "first independent provider; corpus case_reproductions already "
            "succeeded under this provider"
        )
        return record

    if provider in _GPU_LOCAL:
        if provider == "h3_local":
            comfy_url = (os.environ.get("H3_COMFY_URL") or "http://127.0.0.1:8188").rstrip("/")
            reachable, detail = _url_reachable(comfy_url)
            if not reachable:
                record["status"] = "ENV_BLOCKED"
                record["reason"] = f"ComfyUI unreachable ({detail})"
                return record
        if not gpu_ok:
            record["status"] = "ENV_BLOCKED"
            record["reason"] = f"GPU required: {gpu_detail}"
            return record
        record["status"] = "FREE_LOCAL_RUNNABLE"
        record["reason"] = "local GPU provider registered and hardware reachable"
        return record

    if provider == "manim":
        if any(value == "ABSENT" for value in credentials.values()):
            record["status"] = "OWNER_BLOCKED_NO_CREDENTIAL"
            record["reason"] = "required credential absent"
            return record
        if not probe:
            record["status"] = "ENV_BLOCKED"
            record["reason"] = "free local probe disabled (--no-probe)"
            return record
        probe_result = _probe_free_local("manim")
        record["probe"] = probe_result
        if probe_result and probe_result.get("passed"):
            record["status"] = "FREE_LOCAL_RUNNABLE"
            record["reason"] = (
                "registered free local video provider; real MP4 produced "
                "(Manim CLI absent → documented Pillow+ffmpeg fallback, "
                "same fallback class as the baseline corpus run)"
            )
        else:
            error = (probe_result or {}).get("error") or "probe failed"
            record["status"] = "ENV_BLOCKED"
            record["reason"] = f"free local probe failed: {error}"
        return record

    if provider in ("wan_2_7", "happyhorse_1_1"):
        if credentials.get("WAVESPEED_API_KEY") == "ABSENT":
            record["status"] = "OWNER_BLOCKED_NO_CREDENTIAL"
            record["reason"] = "WAVESPEED_API_KEY absent"
            return record
        record["status"] = "OWNER_BLOCKED_SPEND"
        record["reason"] = "WaveSpeed credentials present; real run spends money"
        return record

    if provider in _SPEND_CANDIDATES:
        if any(value == "ABSENT" for value in credentials.values()):
            record["status"] = "OWNER_BLOCKED_NO_CREDENTIAL"
            record["reason"] = "required credential absent"
            return record
        record["status"] = "OWNER_BLOCKED_SPEND"
        record["reason"] = "credentials present; real qualification run spends owner budget"
        return record

    record["status"] = "ENV_BLOCKED"
    record["reason"] = "no free authorized path classified"
    return record


def _corpus_state() -> dict[str, Any]:
    """Read live corpus projections — never hardcode 9/10/2 counts."""
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        import asyncpg

        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            return {"error": "DATABASE_URL absent"}

        async def _read() -> dict[str, Any]:
            conn = await asyncpg.connect(dsn=dsn)
            try:
                providers = await conn.fetch(
                    "SELECT provider_id, status, count(*)::int AS n "
                    "FROM case_reproductions GROUP BY 1,2 ORDER BY 1,2"
                )
                distinct_succeeded = await conn.fetchval(
                    "SELECT count(DISTINCT provider_id)::int FROM case_reproductions "
                    "WHERE status='succeeded'"
                )
                benches = await conn.fetch(
                    "SELECT status, provider_count, failure_code, count(*)::int AS n "
                    "FROM case_benchmarks GROUP BY 1,2,3 ORDER BY 1"
                )
                pattern = await conn.fetchrow(
                    "SELECT lifecycle_status, positive_evidence_count, "
                    "negative_evidence_count FROM video_patterns "
                    "ORDER BY updated_at DESC LIMIT 1"
                )
                evidence_providers = await conn.fetchval(
                    "SELECT count(DISTINCT r.provider_id)::int "
                    "FROM video_pattern_evidence e "
                    "JOIN case_reproductions r ON r.id=e.reproduction_id"
                )
                cases = await conn.fetchval("SELECT count(*)::int FROM video_cases")
                analyses = await conn.fetchval(
                    "SELECT count(*)::int FROM video_case_analyses WHERE status='succeeded'"
                )
                return {
                    "video_cases": int(cases or 0),
                    "succeeded_analyses": int(analyses or 0),
                    "reproductions_by_provider": [dict(row) for row in providers],
                    "distinct_succeeded_repro_providers": int(distinct_succeeded or 0),
                    "benchmarks": [dict(row) for row in benches],
                    "pattern": dict(pattern) if pattern else None,
                    "pattern_distinct_repro_providers": int(evidence_providers or 0),
                }
            finally:
                await conn.close()

        return asyncio.run(_read())
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def run_audit(*, probe: bool = True) -> dict[str, Any]:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:
        pass

    registered, reg_error = _registered_video_providers()
    gpu_ok, gpu_detail = _gpu_ok()

    # Full candidate set: registered video + known non-registered names the
    # qualification discussion keeps circling back to.
    candidate_names = list(
        dict.fromkeys(
            [
                *registered,
                "remotion",
                "ffmpeg",
                "motion_graphics",
            ]
        )
    )
    registered_set = set(registered)

    candidates = [
        _classify(
            name,
            registered=name in registered_set,
            gpu_ok=gpu_ok,
            gpu_detail=gpu_detail,
            probe=probe,
        )
        for name in candidate_names
    ]

    runnable = [c["provider"] for c in candidates if c["status"] == "FREE_LOCAL_RUNNABLE"]
    baseline = [c["provider"] for c in candidates if c["status"] == "BASELINE_QUALIFIED"]
    owner_blocked = [
        c["provider"]
        for c in candidates
        if c["status"].startswith("OWNER_BLOCKED")
    ]
    env_blocked = [c["provider"] for c in candidates if c["status"] == "ENV_BLOCKED"]
    not_registered = [
        c["provider"] for c in candidates if c["status"] == "NOT_REGISTERED_VIDEO"
    ]

    second_ready = bool(runnable) and bool(baseline)
    software_gate = "FAIL" if reg_error else "PASS"
    corpus = _corpus_state()
    distinct_succeeded = int(corpus.get("distinct_succeeded_repro_providers") or 0) if "error" not in corpus else 0
    # Honesty bar: a FREE_LOCAL_RUNNABLE candidate is counted only after a
    # real durable case_reproduction succeeds under it alongside the baseline.
    second_counted = bool(second_ready and distinct_succeeded >= 2)

    return {
        "doctor": "second_provider",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": str(ROOT),
        "registration_error": reg_error,
        "registered_video_providers": registered,
        "gpu": {"available": gpu_ok, "detail": gpu_detail},
        "candidates": candidates,
        "corpus": corpus,
        "summary": {
            "BASELINE_QUALIFIED": baseline,
            "FREE_LOCAL_RUNNABLE": runnable,
            "OWNER_BLOCKED": owner_blocked,
            "ENV_BLOCKED": env_blocked,
            "NOT_REGISTERED_VIDEO": not_registered,
        },
        "second_independent_provider_ready": second_ready,
        "second_independent_provider_counted": second_counted,
        "distinct_succeeded_repro_providers": distinct_succeeded,
        "cross_model_gate": (
            "READY_FOR_REAL_RUN" if second_ready else "BLOCKED"
        ),
        "cross_model_qualified": second_counted and software_gate == "PASS",
        "software_gate": software_gate,
        "notes": [
            "A FREE_LOCAL_RUNNABLE candidate is not yet counted as the second "
            "independent provider until a real durable case_reproduction "
            "succeeds under it (canonical path, not a direct probe).",
            "owner-blocked candidates require soffy authorization before any "
            "spending run; credentials are reported PRESENT/ABSENT only.",
            "baseline corpus repros predate the HyperFrames CLI install and "
            "used the provider's documented ffmpeg card fallback — that is "
            "the honesty bar applied to free-local fallbacks as well.",
            (
                f"second independent provider counted: distinct_succeeded_repro_providers={distinct_succeeded}"
                if second_counted
                else f"second independent provider not yet counted: distinct_succeeded_repro_providers={distinct_succeeded}"
            ),
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, help="write the full report to this path")
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="skip the free-local manim real probe (classification shape only)",
    )
    args = parser.parse_args()

    report = run_audit(probe=not args.no_probe)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    for item in report["candidates"]:
        print(
            f"[{item['status']:>24}] {item['provider']}: {item['reason']}",
            file=sys.stderr,
        )
    print(
        f"cross_model_gate={report['cross_model_gate']} "
        f"second_ready={report['second_independent_provider_ready']} "
        f"second_counted={report.get('second_independent_provider_counted')} "
        f"cross_model_qualified={report.get('cross_model_qualified')} "
        f"distinct_succeeded={report.get('distinct_succeeded_repro_providers')} "
        f"software_gate={report['software_gate']}",
        file=sys.stderr,
    )
    return 1 if report["software_gate"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
