"""R3 verifier adversarial probe for F2 (no shadow storage) and F9 (replay equal).

Independent of the unit's tests: drives the real FastAPI app + real SQLite store,
writes a graph through the Repository the bridge exposes, and checks the ops API
reads it back; asserts propose leaves the task repo unchanged and confirm creates
a task readable via the existing TaskRepository protocol.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

OUT = Path("audit/agentops/verify_r3")
tmp = Path(tempfile.mkdtemp(dir=".tmp"))
os.environ["HEVI_AGENT_OPS_DB"] = str(tmp / "ops.db")

# network guard
_orig = socket.socket.connect
NET = []


def _guard(self, addr):
    NET.append(str(addr))
    raise OSError("network blocked by verifier")


socket.socket.connect = _guard

from fastapi.testclient import TestClient  # noqa: E402

from hevi.api.main import app  # noqa: E402
from hevi.auth.dependencies import get_current_user  # noqa: E402
from hevi.operations.bridge import SqliteOperationsStore  # noqa: E402

app.dependency_overrides[get_current_user] = lambda: {"id": "v", "email": "v@x", "role": "user"}
c = TestClient(app)
s = SqliteOperationsStore(tmp / "ops.db")
R = {}

# F2a: write a graph via the bridge's Repository, read it back through the ops API
G = str(uuid4())
asyncio.run(
    s._graph_repo.create(
        {
            "id": G,
            "graph_id": G,
            "nodes": [{"type": "script", "rows": []}],
            "edges": [],
            "revision": 0,
        }
    )
)
r = c.post("/api/ops/canvas.get", json={"params": {"graph_id": G}})
R["F2a_canvas_get_reads_repo"] = {
    "status": r.status_code,
    "revision": r.json().get("revision"),
    "same_id": r.json().get("graph", {}).get("graph_id") == G,
}


# F2b: propose leaves task repo unchanged; confirm creates exactly one task
def tcount():
    return len(asyncio.run(s._task_repo.list_tasks()))


t0 = tcount()
rp = c.post(
    "/api/ops/canvas.generation.propose",
    json={"params": {"graph_id": G, "prompt": "小狐狸", "rows": [0]}},
)
t1 = tcount()
rc = c.post(
    "/api/ops/canvas.generation.propose/confirm",
    json={"params": {"proposalId": rp.json().get("proposalId")}},
)
t2 = tcount()
tid = rc.json().get("task_id")
back = asyncio.run(s._task_repo.get_task(tid)) if tid else None
R["F2b_propose_no_task"] = {"propose_status": rp.status_code, "delta_propose": t1 - t0}
R["F2b_confirm_task_via_repo"] = {
    "confirm_status": rc.status_code,
    "delta_confirm": t2 - t1,
    "readable": bool(back),
}

# F2c: no parallel CREATE TABLE in hevi/operations except the receipt tables
import re

src = Path("hevi/operations/bridge.py").read_text(encoding="utf-8")
tables = re.findall(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)", src)
R["F2c_create_tables"] = {
    "tables": tables,
    "ok": set(tables) <= {"agent_op_receipts", "agent_schema_version"},
}
# also scan the whole package
pkg_tables = []
for p in Path("hevi/operations").glob("*.py"):
    pkg_tables += re.findall(
        r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)", p.read_text(encoding="utf-8")
    )
R["F2c_pkg_tables"] = {
    "tables": sorted(set(pkg_tables)),
    "ok": set(pkg_tables) <= {"agent_op_receipts", "agent_schema_version"},
}

# F9: replay receipt equal to first (minus 'replayed')
row = {"effect": "warm", "transition_in": "fade", "duration": 3.0}
rev0 = c.post("/api/ops/canvas.get", json={"params": {"graph_id": G}}).json()["revision"]
body = {"params": {"graph_id": G, "row": row}, "opId": "probe-A", "expectedRevision": rev0}
a1 = c.post("/api/ops/canvas.script.rows.append", json=body).json()
a2 = c.post("/api/ops/canvas.script.rows.append", json=body).json()
same = {k: v for k, v in a2.items() if k != "replayed"} == a1
R["F9_replay_equal"] = {"replayed": a2.get("replayed"), "equal": same}

R["network_attempts"] = NET
(OUT / "probe_f2f9.json").write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str))
print(json.dumps(R, ensure_ascii=False, indent=1, default=str))
print("PROBEDONE")
