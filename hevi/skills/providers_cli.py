"""HEVI external provider doctor.

Examples::

    uv run python -m hevi.skills.providers_cli status
    uv run python -m hevi.skills.providers_cli status --no-probe
    uv run python -m hevi.skills.providers_cli status --provider pexels --provider mpt
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from dotenv import load_dotenv

from hevi.provider_policy.runtime import (
    inspect_providers,
    probe_provider_readiness,
    runtime_provider_ids,
)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="HEVI external provider configuration doctor")
    sub = parser.add_subparsers(dest="verb", required=True)
    status = sub.add_parser("status", help="检查配置与真实 Provider 可达性")
    status.add_argument("--provider", action="append", choices=runtime_provider_ids())
    status.add_argument("--no-probe", action="store_true", help="只看配置，不发网络探针")
    status.add_argument("--timeout", type=float, default=5.0)
    readiness = sub.add_parser(
        "readiness", help="运行 fail-closed readiness 审计；健康检查不等于可生产"
    )
    readiness.add_argument("--provider", action="append", choices=runtime_provider_ids())
    readiness.add_argument("--timeout", type=float, default=5.0)
    readiness.add_argument(
        "--artifact",
        help="本次真实 submit/ACK 产生的本地 artifact；缺失时保持 BLOCKED_RUNTIME",
    )
    readiness.add_argument("--model-ready", action="store_true")
    readiness.add_argument("--submit-ready", action="store_true")
    readiness.add_argument("--provider-job-id")
    args = parser.parse_args(argv)

    if args.verb == "readiness":
        ids = args.provider or list(runtime_provider_ids())

        async def run_readiness() -> list[dict[str, object]]:
            return list(
                await asyncio.gather(
                    *(
                        probe_provider_readiness(
                            provider_id,
                            artifact_path=args.artifact,
                            model_ready=args.model_ready,
                            submit_ready=args.submit_ready,
                            provider_job_id=args.provider_job_id,
                            timeout_s=max(0.1, args.timeout),
                        )
                        for provider_id in ids
                    )
                )
            )

        providers = asyncio.run(run_readiness())
        print(json.dumps({"providers": providers}, ensure_ascii=False, indent=2))
        return 0 if all(item["status"] == "READY" for item in providers) else 1
    if args.verb != "status":
        return 2
    providers = asyncio.run(
        inspect_providers(
            provider_ids=args.provider,
            probe=not args.no_probe,
            timeout_s=max(0.1, args.timeout),
        )
    )
    print(json.dumps({"providers": providers}, ensure_ascii=False, indent=2))
    if args.no_probe:
        return 0 if all(item["configured"] for item in providers) else 1
    return 0 if all(item["ready"] for item in providers) else 1


if __name__ == "__main__":
    sys.exit(main())
