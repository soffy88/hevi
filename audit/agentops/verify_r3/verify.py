"""Independent verifier for AGENTOPS-R1 (real TestClient, real SQLite store)."""
import json, os, sys, tempfile, asyncio, sqlite3
from pathlib import Path
from uuid import uuid4
OUT = Path("audit/agentops/verify_r3"); OUT.mkdir(parents=True, exist_ok=True)
tmp = Path(tempfile.mkdtemp(dir=".tmp")); db = tmp / "ops.db"
os.environ["HEVI_AGENT_OPS_DB"] = str(db)
# network guard
import socket
_orig = socket.socket.connect
NET = []
def _guard(self, addr):
    NET.append(str(addr)); raise OSError("network blocked by verifier")
socket.socket.connect = _guard
# provider call counter: patch every class with generate/submit methods in hevi.providers
import importlib, pkgutil, hevi.providers as P
CALLS = []
for m in pkgutil.iter_modules(P.__path__):
    try: mod = importlib.import_module(f"hevi.providers.{m.name}")
    except Exception: continue
    for an, obj in list(vars(mod).items()):
        if isinstance(obj, type) and obj.__module__ == mod.__name__:
            for meth in ("generate","submit","create_task","generate_video","generate_image","run","__call__"):
                if meth in vars(obj):
                    orig = vars(obj)[meth]
                    def wrap(*a, _o=orig, _n=f"{mod.__name__}.{an}.{meth}", **k):
                        CALLS.append(_n); return _o(*a, **k)
                    try: setattr(obj, meth, wrap)
                    except Exception: pass
from fastapi.testclient import TestClient
from hevi.api.main import app
from hevi.auth.dependencies import get_current_user
from hevi.operations.bridge import SqliteOperationsStore
app.dependency_overrides[get_current_user] = lambda: {"id":"verifier","email":"v@x","role":"user"}
c = TestClient(app)
s = SqliteOperationsStore(db); G = str(uuid4())
asyncio.run(s._graph_repo.create({"id": G, "graph_id": G, "nodes": [{"type":"script","rows":[]},{"type":"image","id":"n1"}], "edges": [], "revision": 0}))
log = []; R = {}
def call(tag, method, url, body=None):
    r = c.get(url) if method=="GET" else c.post(url, json=body)
    try: j = r.json()
    except Exception: j = r.text
    log.append({"tag":tag,"method":method,"url":url,"request":body,"status":r.status_code,"response":j}); return r.status_code, j
def rows():
    st, j = call("probe.canvas.get","POST","/api/ops/canvas.get",{"params":{"graph_id":G}})
    n = [x for x in j["graph"]["nodes"] if x.get("type")=="script"][0]
    return len(n.get("rows",[])), j["revision"]
# 1
st,j = call("1.list","GET","/api/ops")
ops = j["operations"]; req = {"name","readOnly","scope","params","replay"}
R["1"] = dict(status=st, count=len(ops), all_fields=all(req<=set(o) for o in ops),
  readonly=sorted(o["name"] for o in ops if o["readOnly"]),
  pass_=st==200 and len(ops)==8 and all(req<=set(o) for o in ops) and sorted(o["name"] for o in ops if o["readOnly"])==sorted(["canvas.get","canvas.generation.propose","asset.list","task.get"]))
# 2
row = {"effect":"warm","transition_in":"fade","duration":3.0}
n0,rev0 = rows()
b = {"params":{"graph_id":G,"row":row},"opId":"op-A","expectedRevision":rev0}
s1,a1 = call("2.first","POST","/api/ops/canvas.script.rows.append",b)
s2,a2 = call("2.replay","POST","/api/ops/canvas.script.rows.append",b)
s3,a3 = call("2.replay2","POST","/api/ops/canvas.script.rows.append",b)
n1,rev1 = rows()
same = {k:v for k,v in a2.items() if k!="replayed"} == a1
s4,a4 = call("2.conflict","POST","/api/ops/canvas.script.rows.append",{"params":{"graph_id":G,"row":{**row,"duration":5.0}},"opId":"op-A","expectedRevision":rev1})
n2,_ = rows()
# write without opId
s5,a5 = call("2.no_opid","POST","/api/ops/canvas.script.rows.append",{"params":{"graph_id":G,"row":row},"expectedRevision":rev1})
n3,rev3 = rows()
R["2"] = dict(delta=n1-n0, replayed=a2.get("replayed"), receipt_equal=same, conflict_status=s4, rows_after_conflict=n2,
  no_opid_status=s5, no_opid_row_added=n3-n2,
  pass_=n1-n0==1 and a2.get("replayed") is True and same and s4==409 and n2==n1, opid_required=s5>=400)
# 3
s6,a6 = call("3.stale","POST","/api/ops/canvas.script.rows.append",{"params":{"graph_id":G,"row":row},"opId":"op-C","expectedRevision":0})
n4,rev4 = rows()
R["3"] = dict(status=s6, unchanged=(n4,rev4)==(n3,rev3), pass_=s6==409 and (n4,rev4)==(n3,rev3))
# 4
s7,a7 = call("4.readonly","POST","/api/ops/canvas.script.rows.append?mode=read-only",{"params":{"graph_id":G,"row":row},"opId":"op-D","expectedRevision":rev4})
n5,rev5 = rows()
err = (a7.get("detail") or {}).get("error") if isinstance(a7,dict) else None
R["4"] = dict(status=s7, error=err, unchanged=(n5,rev5)==(n4,rev4), pass_=err=="scope_denied" and (n5,rev5)==(n4,rev4))
# 5
def tcount(): return len(asyncio.run(s._task_repo.list_tasks()))
t0 = tcount(); CALLS.clear()
s8,a8 = call("5.propose","POST","/api/ops/canvas.generation.propose",{"params":{"graph_id":G,"prompt":"小狐狸刷牙","rows":[0]}})
t1 = tcount()
s9,a9 = call("5.confirm","POST","/api/ops/canvas.generation.propose/confirm",{"params":{"proposalId":a8.get("proposalId")}})
t2 = tcount()
R["5"] = dict(propose_status=s8, keys=sorted(a8), agent_tasks_delta_propose=t1-t0, provider_calls=list(CALLS),
  confirm_status=s9, confirm=a9, agent_tasks_delta_confirm=t2-t1,
  note="confirm creates task via TaskRepository / local stub; propose leaves task repository unchanged")
# 6
bad = [{"template":"no_such_tpl"},{"transition_in":"no_such_tr"},{"sfx":[{"id":"no_such_sfx"}]}]
res6 = []
for i,br in enumerate(bad):
    st,j = call(f"6.bad{i}","POST","/api/ops/canvas.script.rows.append",{"params":{"graph_id":G,"row":br},"opId":f"op-bad{i}","expectedRevision":rev5})
    res6.append((st, str(j)[:300]))
n6,rev6 = rows()
s10,a10 = call("6.bad_update","POST","/api/ops/canvas.script.rows.update",{"params":{"graph_id":G,"row_index":0,"row":{"transition_in":"nope"}},"opId":"op-bu","expectedRevision":rev5})
from hevi.production.shot_spec import ShotSpec
try: ShotSpec.model_validate({"transition_in":"no_such_tr"}); direct="accepted"
except Exception as e: direct=str(e)[:200]
R["6"] = dict(results=res6, update_status=s10, unchanged=(n6,rev6)==(n5,rev5), direct_validator=direct,
  pass_=all(x[0]==422 for x in res6) and s10==422 and (n6,rev6)==(n5,rev5))
# regression: openshorts route
paths = sorted({r.path for r in app.routes if hasattr(r,"path")})
R["regression_openshorts_mounted"] = "/api/ai-short/run" in paths
R["network_attempts"] = NET
(OUT/"requests.json").write_text(json.dumps(log, ensure_ascii=False, indent=1, default=str))
(OUT/"results.json").write_text(json.dumps(R, ensure_ascii=False, indent=1, default=str))
print(json.dumps(R, ensure_ascii=False, indent=1, default=str))
