#!/usr/bin/env python3
"""D7-G: operator CLI for the single-host differentiation authority stores.

Backs up / verifies / restores the coordinated authority store set
(identity + incident [+ optional usage]) under one boundary token. This is the
operational entry point over ``hevi.creative.layer4.store_backup``.

Usage::

    python scripts/ops/authority_backup.py backup  --dest /backups/hevi
    python scripts/ops/authority_backup.py verify  --manifest /backups/hevi/manifest.json
    python scripts/ops/authority_backup.py restore --manifest ... --target /restore

Secrets are never included: the authority stores contain no credentials.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hevi.creative.layer4.identity_store import identity_db_path
from hevi.creative.layer4.incident_store import incident_db_path
from hevi.creative.layer4.store_backup import (
    backup_stores,
    boundary_token,
    restore_stores,
    verify_backup,
)


def _store_set() -> dict[str, Path]:
    return {"identities": identity_db_path(), "incidents": incident_db_path()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--dest", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--manifest", required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--manifest", required=True)
    restore.add_argument("--target", required=True)
    args = parser.parse_args()

    if args.command == "backup":
        manifest = backup_stores(_store_set(), Path(args.dest))
        print(json.dumps({
            "boundary_token": manifest["boundary_token"],
            "members": [m["name"] for m in manifest["members"]],
        }, indent=2))
        return 0
    if args.command == "verify":
        results = verify_backup(Path(args.manifest))
        print(json.dumps({"verified": results, "ok": all(results.values())}, indent=2))
        return 0 if all(results.values()) else 1
    restored = restore_stores(Path(args.manifest), Path(args.target))
    print(json.dumps({
        "boundary_token": boundary_token(Path(args.manifest)),
        "restored": restored,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
