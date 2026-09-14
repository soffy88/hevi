"""Build the source-of-truth 3O v3 migration inventory from the whole tree."""

from __future__ import annotations

import ast
import json
import sys
from collections import defaultdict

from _3o_common import (
    ROOT,
    has_real_implementation,
    imported_layers,
    local_sources,
    parse,
)

FIELDS = (
    "business_state_dependency",
    "business_instance_ids",
    "filesystem_io",
    "db_io",
    "network_io",
    "provider_io",
    "subprocess_io",
    "mutates_input",
    "persistent_side_effect",
    "sibling_calls",
    "reverse_dependencies",
)


def _flags(tree: ast.AST) -> dict[str, object]:
    text = ast.unparse(tree).lower()
    return {
        "business_state_dependency": any(
            x in text
            for x in (
                "user_id",
                "tenant_id",
                "project_id",
                "job_id",
                "business_record",
                ".status",
                ".timeline",
            )
        ),
        "business_instance_ids": sorted(
            x for x in ("user_id", "tenant_id", "project_id", "job_id") if x in text
        ),
        "filesystem_io": any(
            x in text for x in ("open(", "write_text", "write_bytes", "mkdir(", "pathlib")
        ),
        "db_io": any(x in text for x in ("sqlalchemy", "pgpool", "session", "insert(", "update(")),
        "network_io": any(x in text for x in ("httpx", "requests", "aiohttp", "urlopen")),
        "provider_io": any(
            x in text
            for x in ("providerregistry", "provider_registry", "client.generate", "model=")
        ),
        "subprocess_io": "subprocess" in text or "create_subprocess" in text,
        "mutates_input": any(
            x in text for x in (".status =", ".timeline =", ".append(", ".update(")
        ),
        "persistent_side_effect": any(
            x in text for x in ("commit(", "write_text", "write_bytes", "insert(")
        ),
    }


def _target(layer: str, flags: dict[str, object], real: bool) -> tuple[str, str]:
    if not real:
        return "DELEGATE_TO_CANONICAL", "canonical import/delegation shim"
    if layer == "obase" or (flags["db_io"] and layer not in {"omodul", "oservi"}):
        return "MOVE_TO_OBASE", "infrastructure or persistence adapter"
    if layer == "oprim":
        return "MOVE_TO_OPRIM", "atomic element"
    if layer == "oskill":
        return "MOVE_TO_OSKILL", "stateless multi-primitive algorithm"
    if layer == "omodul":
        return "MOVE_TO_OMODUL", "transaction element"
    if layer == "oservi":
        return "MOVE_TO_OSERVI", "generic runtime service"
    return "BLOCKED", "requires classification"


def main() -> int:
    inventory: list[dict[str, object]] = []
    by_symbol: defaultdict[str, list[str]] = defaultdict(list)
    for source in local_sources():
        tree = parse(source.path)
        flags = _flags(tree)
        real = has_real_implementation(tree)
        funcs = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if not funcs:
            funcs = [None]
        for fn in funcs:
            symbol = fn.name if fn else source.path.stem
            key = f"{source.layer}.{symbol}"
            by_symbol[key].append(source.rel)
            action, why = _target(source.layer, flags, real)
            item: dict[str, object] = {
                "current_path": source.rel,
                "current_symbol": symbol,
                "declared_layer": source.layer,
                "actual_behavior": why,
                "actual_layer": source.layer,
                "canonical_equivalent": f"{source.layer}.{symbol}",
                "duplicate_of": None,
                "target_repo": source.layer,
                "target_symbol": symbol,
                "migration_action": action,
                "severity": "P0"
                if real and source.layer in {"oprim", "oskill", "omodul"}
                else "P1",
                "signature_status": "unknown",
                "pillar_status": "unknown",
                "sibling_calls": sorted(imported_layers(tree) & {"oprim", "oskill", "omodul"}),
                **flags,
            }
            inventory.append(item)
    duplicates: list[str] = []
    for key, paths in by_symbol.items():
        if len(paths) > 1:
            duplicates.extend(paths[1:])
            for item in inventory:
                if (
                    f"{item['target_repo']}.{item['current_symbol']}" == key
                    and item["current_path"] in paths[1:]
                ):
                    item["duplicate_of"] = paths[0]
                    item["migration_action"] = "DELETE_DUPLICATE"
    out = ROOT / "artifacts/3o-v3/migration_inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_from": "AST/filesystem",
        "source_of_truth": True,
        "symbols": inventory,
        "summary": {
            "TOTAL_LOCAL_3O_SYMBOLS": len(inventory),
            "P0": sum(x["severity"] == "P0" for x in inventory),
            "P1": sum(x["severity"] == "P1" for x in inventory),
            "P2": sum(x["severity"] == "P2" for x in inventory),
        },
    }
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
