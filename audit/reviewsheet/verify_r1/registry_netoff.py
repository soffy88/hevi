"""核验员：registry 调起 + 断网运行（由 root `unshare -n` 包裹执行，进程内无任何网络接口）。"""
import json
import socket
from pathlib import Path

from hevi import capabilities as caps

OUT = Path(__file__).resolve().parent
R = {}
# 断网自证：连外网必须失败
try:
    socket.create_connection(("1.1.1.1", 443), timeout=3)
    R["network"] = "REACHABLE(未断网)"
except OSError as e:
    R["network"] = f"unreachable: {e}"
names = [c.name if hasattr(c, "name") else c for c in caps.list()] if hasattr(caps, "list") else []
R["registered"] = sorted(n for n in names if "kids" in str(n))
mp = OUT / "e2e" / "manifest_v1.json"
out = OUT / "registry_call"
out.mkdir(exist_ok=True)
for n in ("kids.review_sheet", "kids.annotation_revision"):
    c = caps.get(n)
    params = {"manifest_path": str(mp)}
    if n == "kids.annotation_revision":
        params["annotation"] = {"shot_index": 3, "source_time_ms": [9000],
                                "marks": [{"kind": "pin", "nx": .5, "ny": .5}]}
    try:
        res = c.render(params, out / n, duration=4.0, aspect="9:16", seed=1)
        R[n] = {"ok": True, "res": str(res)[:400]}
    except Exception as e:  # noqa: BLE001
        R[n] = {"ok": False, "err": f"{type(e).__name__}: {e}"[:300]}
(OUT / "results_registry_netoff.json").write_text(json.dumps(R, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(R, ensure_ascii=False))
