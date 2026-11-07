"""CLI for the spatial world contract validator.

Usage:
    python -m hevi.world_contract validate CONTRACT.json MANIFEST.json
    python -m hevi.world_contract check-contract CONTRACT.json

Prints the structured result as JSON to stdout.  Exit code is 0 when the
validation passes and 1 when any violation is found (2 on usage / IO
errors), so the CLI can gate a build pipeline directly.
"""

from __future__ import annotations

import argparse
import json
import sys

from .model import ContractError, load_json
from .validate import validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m hevi.world_contract",
        description="Validate a spatial world contract and/or world manifest.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="contract + manifest")
    p_validate.add_argument("contract")
    p_validate.add_argument("manifest")

    p_check = sub.add_parser("check-contract", help="contract only")
    p_check.add_argument("contract")

    args = parser.parse_args(argv)
    try:
        contract = load_json(args.contract)
        manifest = load_json(args.manifest) if args.command == "validate" else None
    except ContractError as exc:
        print(json.dumps({"pass": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    result = validate(contract, manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
