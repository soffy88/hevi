"""3O v3 async contract gate; sync/async changes require an explicit contract."""

from __future__ import annotations

import ast
import json
import sys

from _3o_common import ROOT, canonical_sources, parse, public_functions


def main() -> int:
    contract_path = ROOT / "artifacts/3o-v3/async_contract.json"
    contract = (
        json.loads(contract_path.read_text(encoding="utf-8")) if contract_path.exists() else {}
    )
    violations: list[str] = []
    current: dict[str, bool] = {}
    for source in canonical_sources():
        for fn in public_functions(parse(source.path)):
            key = f"{source.layer}.{fn.name}"
            current[key] = isinstance(fn, ast.AsyncFunctionDef)
            if key in contract and bool(contract[key]) != current[key]:
                violations.append(f"{key}: async contract changed")
    if contract_path.exists():
        contract_path.write_text(
            json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    for item in violations:
        print(item)
    return int(bool(violations))


if __name__ == "__main__":
    sys.exit(main())
