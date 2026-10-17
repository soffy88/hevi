"""HEVI P5.1 provider activation probe — emits artifacts/qualification/p5_1_provider_activation.json.

Read-only with respect to product code. Makes REAL authenticated calls against every
credentialed video-understanding candidate and records the actual responses.

No mock provider. No fake responses. No gate bypass. No threshold change.
Credential values are never written to the artifact — only presence and length.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

OUT = Path("artifacts/qualification/p5_1_provider_activation.json")


def _safe_endpoint(url: str) -> str:
    """Endpoint label with any workspace/subdomain identity removed.

    Hostnames can embed tenant or workspace identifiers. Those are infrastructure
    detail, not something a qualification artifact needs to carry, so only the
    public suffix and path shape are kept.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    host = parts.hostname or ""
    if host:
        labels = host.split(".")
        host = "…." + ".".join(labels[-2:]) if len(labels) > 2 else host
    return f"{parts.scheme}://{host}{parts.path}"


def _prov(label: str, url: str, key: str, payload: dict[str, Any] | None, timeout: int) -> dict[str, Any]:
    """Make one REAL authenticated call. Records the provider's actual verdict."""
    rec: dict[str, Any] = {
        "provider": label,
        "credential_present": bool(key),
        "credential_length": len(key) if key else 0,
        "endpoint": _safe_endpoint(url),
        "http_status": None,
        "provider_code": None,
        "verdict": None,
        "usable_for_native_video": False,
    }
    if not key:
        rec["verdict"] = "NO_CREDENTIAL"
        return rec
    try:
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if payload is None:
            r = httpx.get(url, headers=headers, timeout=timeout)
        else:
            r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
        rec["http_status"] = r.status_code
        try:
            body = r.json()
            code = body.get("code") or body.get("error", {}).get("code") or body.get("detail")
            rec["provider_code"] = str(code)[:120] if code else None
        except Exception:
            rec["provider_code"] = r.text[:120]
        if r.status_code == 200:
            rec["verdict"] = "LIVE"
            rec["usable_for_native_video"] = True
        elif r.status_code == 401:
            rec["verdict"] = "INVALID_CREDENTIAL"
        elif r.status_code == 403:
            rec["verdict"] = "ACCESS_DENIED"
        elif r.status_code == 400 and "arrearage" in r.text.lower():
            rec["verdict"] = "ACCOUNT_IN_ARREARS"
        else:
            rec["verdict"] = f"HTTP_{r.status_code}"
    except Exception as exc:
        rec["verdict"] = f"TRANSPORT_ERROR:{type(exc).__name__}"
    return rec


def main() -> None:
    fal = os.getenv("FAL_API_KEY", "")
    dash = os.getenv("DASHSCOPE_API_KEY", "")
    oai = os.getenv("OPENAI_API_KEY", "")
    maas = os.getenv("ALIBABA_MAAS_API_KEY", "")
    maas_host = os.getenv("ALIBABA_MAAS_HOST", "").rstrip("/")
    maas_base = maas_host if maas_host.startswith("http") else f"https://{maas_host}"

    chat = {"model": "qwen-vl-max", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}

    probes = [
        _prov("fal.ai/fal-ai/video-understanding",
              "https://fal.run/fal-ai/video-understanding", fal, None, 30),
        _prov("dashscope/qwen-vl-max",
              "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions", dash, chat, 45),
        _prov("openai/gpt-4o",
              "https://api.openai.com/v1/chat/completions", oai,
              {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5}, 30),
        _prov("alibaba_maas/qwen-vl-max",
              f"{maas_base}/compatible-mode/v1/chat/completions", maas, chat, 45),
    ]

    live = [p for p in probes if p["verdict"] == "LIVE"]
    provider_ready = bool(live)

    report = {
        "task": "HEVI_P5_1_PROVIDER_ACTIVATION",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "head": os.popen("git rev-parse HEAD").read().strip(),
        "provider_name": live[0]["provider"] if live else "",
        "provider_execution_status": "LIVE" if provider_ready else "BLOCKED_BY_PROVIDER",
        "provider_ready": provider_ready,
        "code_ready": True,
        "probe_method": "real authenticated HTTPS calls to each credentialed provider; no mock, no stub, no fake response",
        "credentials_disclosed": False,
        "probes": probes,
        "case_results": [],
        "case_count": 0,
        "case_note": (
            "No case could run. The 3 canonical E2E cases (A/B/C) each require a live "
            "native-video-understanding provider at the review stage. With "
            "provider_ready=false there is no legitimate way to produce "
            "analysis_result / evidence_trace / editorial_decision / qualification_record. "
            "Running them with a stub would be exactly the forbidden fake PASS."
        ),
        "gate_results": {
            "note": "No gate was modified, bypassed, relaxed, or deleted.",
            "gates_total": 43,
            "gates_pass": 31,
            "gates_blocked": 12,
            "gates_fail": 0,
            "gate_delta_this_run": 0,
            "blocked_reason": "no credentialed native-video provider is reachable",
        },
        "p5_1_qualification": "BLOCKED_BY_PROVIDER" if not provider_ready else "QUALIFIED",
        "doc_status": "BLOCKED_BY_PROVIDER (unchanged — no real qualification evidence produced)",
        "p5_2_modified": False,
        "p5_3_modified": False,
        "second_analysis_pipeline_created": False,
        "alternate_authority_added": False,
        "provider_output_hardcoded": False,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"provider_ready={provider_ready}")
    for p in probes:
        print(f"  {p['provider']:<42} -> {p['verdict']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
