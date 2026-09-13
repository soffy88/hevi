#!/usr/bin/env python3
"""Run a real Trivy scan and classify environmental failures explicitly."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _finding_count(report: dict[str, Any]) -> int:
    total = 0
    for result in report.get("Results", []):
        total += len(result.get("Vulnerabilities") or [])
        total += len(result.get("Secrets") or [])
        total += len(result.get("MisconfSummary") or [])
        total += len(result.get("Misconfigurations") or [])
    return total


def classify(returncode: int | None, stdout: str, stderr: str, report: dict[str, Any] | None) -> str:
    findings = _finding_count(report or {})
    combined = f"{stdout}\n{stderr}".lower()
    if findings:
        return "FAILED_VULNERABILITIES"
    if any(token in combined for token in ("need to update db", "vulnerability db", "checks bundle")):
        return "BLOCKED_DATABASE"
    if any(token in combined for token in ("lookup", "timed out", "timeout", "connection reset", "download")):
        return "BLOCKED_NETWORK"
    if returncode == 0:
        return "PASS"
    return "TOOL_ERROR"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=Path(".trivy-cache"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/security/trivy.json"))
    args = parser.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("trivy") is None:
        payload = {"status": "TOOL_ERROR", "error": "trivy executable not found"}
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        args.output.with_name("trivy-summary.md").write_text("# Trivy\n\nStatus: `TOOL_ERROR`\n", encoding="utf-8")
        return 3
    command = [
        "trivy", "fs", "--cache-dir", str(args.cache_dir), "--format", "json",
        "--output", str(args.output), "--scanners", "vuln,secret,misconfig",
        "--severity", "HIGH,CRITICAL", "--ignore-unfixed", "--exit-code", "1",
        "--skip-dirs", "services/gen_engine/vibeasr-src/3rdparty/llama.cpp",
        "--skip-files", "services/gen_engine/third_party/Matcha-TTS/requirements.txt", ".",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=900)
        returncode: int | None = result.returncode
        stdout, stderr = result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        returncode, stdout, stderr = None, str(exc.stdout or ""), "timeout"
    except OSError as exc:
        returncode, stdout, stderr = None, "", type(exc).__name__
    try:
        report = json.loads(args.output.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = None
    status = classify(returncode, stdout, stderr, report)
    payload = report if report is not None else {}
    payload.update({"status": status, "returncode": returncode, "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:]})
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    findings = _finding_count(report or {})
    summary = ["# Trivy scan", "", f"Status: `{status}`", f"Findings: `{findings}`", f"Return code: `{returncode}`", ""]
    if status != "PASS":
        summary.append("The scan did not pass; this result is fail-closed and requires remediation or environment recovery.")
    args.output.with_name("trivy-summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "findings": findings, "returncode": returncode}))
    return 0 if status == "PASS" else (1 if status == "FAILED_VULNERABILITIES" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
