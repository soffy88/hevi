#!/usr/bin/env python3
"""Run a real Trivy scan and classify environmental failures explicitly."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
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
    report = report or {}
    vulnerability_count = sum(len(result.get("Vulnerabilities") or []) for result in report.get("Results", []))
    misconfiguration_count = sum(len(result.get("Misconfigurations") or []) for result in report.get("Results", []))
    if vulnerability_count:
        return "VULNERABILITY_FOUND"
    if misconfiguration_count:
        return "MISCONFIGURATION_FOUND"
    combined = f"{stdout}\n{stderr}".lower()
    if any(token in combined for token in ("need to update db", "vulnerability db", "checks bundle")):
        return "BLOCKED_DB"
    if any(token in combined for token in ("lookup", "timed out", "timeout", "connection reset", "download")):
        return "BLOCKED_NETWORK"
    if returncode == 0:
        return "PASS"
    return "TOOL_ERROR"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=Path(".trivy-cache"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/security/trivy.json"))
    parser.add_argument("--image", help="Optional already-built release image to scan")
    args = parser.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    runner = "binary"
    output_path = args.output.resolve()
    cache_path = args.cache_dir.resolve()
    if shutil.which("trivy") is None and shutil.which("docker") is None:
        payload = {"status": "BLOCKED_TOOL_INSTALL", "error": "trivy executable not found", "scan_timestamp": datetime.now(UTC).isoformat()}
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        args.output.with_name("trivy-summary.md").write_text("# Trivy\n\nStatus: `TOOL_ERROR`\n", encoding="utf-8")
        return 2
    scan_args = [
        "fs", "--cache-dir", str(args.cache_dir), "--format", "json",
        "--output", str(args.output), "--scanners", "vuln,secret,misconfig",
        "--severity", "HIGH,CRITICAL", "--ignore-unfixed", "--exit-code", "1",
        "--skip-dirs", "services/gen_engine/vibeasr-src/3rdparty/llama.cpp",
        "--skip-files", "services/gen_engine/third_party/Matcha-TTS/requirements.txt", ".",
    ]
    if shutil.which("trivy"):
        command = ["trivy", *scan_args]
    else:
        runner = "docker"
        relative_output = output_path.relative_to(Path.cwd())
        command = ["docker", "run", "--rm", "--network", "host", "-v", f"{Path.cwd()}:/workspace", "-v", f"{cache_path}:/root/.cache/trivy", "-e", f"TRIVY_DB_REPOSITORY={os.getenv('TRIVY_DB_REPOSITORY', 'ghcr.io/aquasecurity/trivy-db:2')}", "-e", f"TRIVY_CHECKS_BUNDLE_REPOSITORY={os.getenv('TRIVY_CHECKS_BUNDLE_REPOSITORY', 'ghcr.io/aquasecurity/trivy-checks:1')}", "aquasec/trivy:0.68.2", *["/root/.cache/trivy" if arg == str(args.cache_dir) else (f"/workspace/{relative_output}" if arg == str(args.output) else ("/workspace" if arg == "." else arg)) for arg in scan_args]]
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
    version_command = ["trivy", "--version"] if runner == "binary" else ["docker", "run", "--rm", "aquasec/trivy:0.68.2", "--version"]
    version = subprocess.run(version_command, capture_output=True, text=True, check=False).stdout.strip()
    cache_entries = [{"path": str(path), "mtime": path.stat().st_mtime, "size": path.stat().st_size} for path in args.cache_dir.rglob("*") if path.is_file()][:100]
    payload = report if report is not None else {}
    payload.update({"status": status, "returncode": returncode, "scan_timestamp": datetime.now(UTC).isoformat(), "trivy_version": version, "runner": runner, "db_metadata": {"cache_dir": str(args.cache_dir), "entries": cache_entries, "db_repository": os.getenv("TRIVY_DB_REPOSITORY", "ghcr.io/aquasecurity/trivy-db:2"), "checks_bundle_repository": os.getenv("TRIVY_CHECKS_BUNDLE_REPOSITORY", "ghcr.io/aquasecurity/trivy-checks:1")}, "container_scan": {"image": args.image, "status": "NOT_REQUESTED" if not args.image else "NOT_RUN"}, "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:]})
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    findings = _finding_count(report or {})
    summary = ["# Trivy scan", "", f"Status: `{status}`", f"Findings: `{findings}`", f"Return code: `{returncode}`", ""]
    if status != "PASS":
        summary.append("The scan did not pass; this result is fail-closed and requires remediation or environment recovery.")
    args.output.with_name("trivy-summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "findings": findings, "returncode": returncode}))
    return 0 if status == "PASS" else (1 if status in {"VULNERABILITY_FOUND", "MISCONFIGURATION_FOUND"} else 2)


if __name__ == "__main__":
    raise SystemExit(main())
