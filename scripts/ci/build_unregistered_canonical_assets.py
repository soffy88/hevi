"""Record exported support API that is not a canonical 3O element.

Root ``__all__`` is deliberately broader than the 3O manifest for backwards
compatibility.  This evidence keeps that support surface explicit instead of
silently treating it as an element.
"""
from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

from _3o_common import CANONICAL, ROOT


def consumer_count(name: str) -> int:
    result = subprocess.run(
        ["rg", "-l", rf"\b{ name }\b", "hevi", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return len([line for line in result.stdout.splitlines() if line])


def root_exports(package: str) -> set[str]:
    path = Path("/tmp/hevi-3o-canonical") / package / package / "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                # Dynamic __all__ is recorded from the already generated audit.
                break
            return set(ast.literal_eval(value))
    return set()


def main() -> int:
    audit_path = ROOT / "artifacts/qualification/3o-v3-global-audit-after-oprim-oskill.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for item in audit.get("NON_ELEMENT_EXPORTS", []):
        package = item["package"]
        name = item["name"]
        classification = "INFRASTRUCTURE_SUPPORT" if package == "obase" else "RUNTIME_SUPPORT"
        action = "RECLASSIFY" if name.endswith("Engine") or name in {"FS", "Cache", "http"} else "MAKE_PRIVATE"
        rows.append(
            {
                "repo": package,
                "module": f"{package}.__init__",
                "symbol": name,
                "export_source": "package root __all__",
                "consumer_count": consumer_count(name),
                "public_api": True,
                "documented": False,
                "registered": False,
                "current_classification": "support_export_not_3o_element",
                "target_classification": classification,
                "action": action,
            }
        )
    out = ROOT / "artifacts/3o-v3/unregistered-canonical-assets.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"source": "current manifest-authoritative export scan", "count": len(rows), "assets": rows}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"NON_ELEMENT_EXPORTS={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
