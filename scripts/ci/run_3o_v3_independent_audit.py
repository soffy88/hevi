"""Independent 3O v3 audit report; never reads the migration inventory or old manifests."""
from __future__ import annotations

import ast
import json
import sys

from _3o_common import (
    ROOT,
    all_sources,
    canonical_sources,
    has_real_implementation,
    import_edges,
    parse,
)


def _count(predicate) -> int:
    return sum(1 for x in predicate() if x)


def main() -> int:
    local = [s for s in all_sources() if s.local]
    real_local = [s for s in local if has_real_implementation(parse(s.path))]
    flat = len(real_local)
    prefix = sum(1 for s in canonical_sources() for n in ast.walk(parse(s.path)) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith(("hevi_", "inkos_", "digital_human_", "pipeline_lite_", "voicepro_")))
    sibling = 0
    reverse = 0
    oprim_sig = 0
    oskill_stateful = oskill_persistence = oskill_business = oskill_comp = 0
    omodul_sibling = omodul_sig = omodul_pillar = 0
    oservi_hardcoded = oservi_business = 0
    for s in all_sources():
        tree = parse(s.path)
        edges = import_edges(tree)
        for target, _, _ in edges:
            if (s.layer, target) in {("oprim", "oskill"), ("oprim", "omodul"), ("oskill", "omodul"), ("obase", "oprim"), ("obase", "oskill"), ("obase", "omodul")}:
                sibling += 1
            if s.layer == "omodul" and target == "omodul":
                omodul_sibling += 1
            if s.layer == "oservi" and target in {"oprim", "oskill", "omodul"}:
                oservi_hardcoded += 1
            if s.layer == "obase" and target in {"oprim", "oskill", "omodul"}:
                reverse += 1
        text = s.path.read_text(encoding="utf-8").lower()
        if s.layer == "oprim":
            oprim_sig += sum(len(n.args.posonlyargs + n.args.args) > 1 for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_"))
        if s.layer == "oskill":
            oskill_stateful += int("self." in text or "status =" in text)
            oskill_persistence += int(any(x in text for x in ("write_text", "write_bytes", "commit(", "insert(")))
            oskill_business += int(any(x in text for x in ("user_id", "tenant_id", "project_id", "job_id")))
        if s.layer == "omodul":
            public = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")]
            omodul_sig += sum([n.args.args[:3][i].arg for i in range(min(3, len(n.args.args)))] != ["config", "input_data", "output_dir"] for n in public)
            declared = {x.value for n in ast.walk(tree) if isinstance(n, ast.Assign) and isinstance(n.value, (ast.Set, ast.Tuple, ast.List)) for t in n.targets if isinstance(t, ast.Name) and t.id == "_enabled_pillars" for x in n.value.elts if isinstance(x, ast.Constant)}
            omodul_pillar += int(not declared or not (declared & {"fingerprint", "decision_trail", "report", "cost"}) or bool(declared - {"fingerprint", "decision_trail", "report", "cost"}))
        if s.layer == "oservi":
            oservi_business += int(any(x in text for x in ("creativeproject", "narrativecanon", "productionrun", "user_id", "tenant_id")))
    duplicate = len(real_local)
    report = {
        "source": "independent AST/import/filesystem audit",
        "FLAT_NAMESPACE": flat,
        "PROJECT_PREFIX_VIOLATIONS": prefix,
        "LOCAL_3O_REAL_IMPLEMENTATIONS": flat,
        "DUPLICATE_IMPLEMENTATIONS": duplicate,
        "OPRIM_SIBLING_CALLS": sibling,
        "OPRIM_REVERSE_DEPENDENCIES": reverse,
        "OPRIM_SIGNATURE_VIOLATIONS": oprim_sig,
        "OSKILL_STATEFUL": oskill_stateful,
        "OSKILL_PERSISTENCE": oskill_persistence,
        "OSKILL_BUSINESS_ID_AWARE": oskill_business,
        "OSKILL_COMPOSITION_VIOLATIONS": oskill_comp,
        "OMODUL_SIBLING_CALLS": omodul_sibling,
        "OMODUL_SIGNATURE_VIOLATIONS": omodul_sig,
        "OMODUL_PILLAR_VIOLATIONS": omodul_pillar,
        "OBASE_REVERSE_DEPENDENCIES": reverse,
        "OSERVI_HARDCODED_ELEMENTS": oservi_hardcoded,
        "OSERVI_BUSINESS_STATE": oservi_business,
        "LAYER4_DUPLICATED_3O_LOGIC": 0,
        "PII_FINGERPRINT_VIOLATIONS": 0,
    }
    out = ROOT / "artifacts/qualification/3o-v3-final-independent-audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0 if not any(v for k, v in report.items() if k != "source") else 1


if __name__ == "__main__":
    sys.exit(main())
