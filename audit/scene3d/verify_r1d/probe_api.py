import os, json, subprocess, sys, tempfile, time
from fastapi import FastAPI
from fastapi.testclient import TestClient
from hevi.api.routers.capabilities import router
app = FastAPI(); app.include_router(router, prefix="/api")
c = TestClient(app, raise_server_exceptions=False)
out = {}
def probe(tag, url, body):
    t=time.time(); r = c.post(url, json=body); dt=time.time()-t
    rec = {"status": r.status_code, "ctype": r.headers.get("content-type"), "secs": round(dt,1)}
    if r.status_code == 200 and "video" in (r.headers.get("content-type") or ""):
        p = f"audit/scene3d/verify_r1d/api_{tag}.mp4"; open(p,"wb").write(r.content)
        pr = subprocess.run(["/home/soffy/.local/bin/ffprobe","-v","error","-count_frames","-select_streams","v:0","-show_entries","stream=width,height,r_frame_rate,nb_read_frames:format=duration","-of","json",p],capture_output=True,text=True)
        rec["/home/soffy/.local/bin/ffprobe"] = json.loads(pr.stdout)
    else:
        rec["body"] = r.text[:400]
    out[tag]=rec; print(tag, json.dumps(rec), flush=True)
B="/api/capabilities/scene3d.fox_wheat/preview"
probe("valid_9x16", B+"?aspect=9:16&seed=5", {"resolution":270})
probe("bad_aspect_4x3", B+"?aspect=4:3&seed=5", {"resolution":270})
probe("unsupported_1x1", B+"?aspect=1:1&seed=5", {"resolution":270})
probe("bad_aspect_garbage", B+"?aspect=abc", {"resolution":270})
probe("short_duration_param", B+"?aspect=9:16", {"resolution":270, "duration":1.0})
probe("short_duration_s_param", B+"?aspect=9:16", {"resolution":270, "duration_s":1.5})
probe("bad_param_type", B+"?aspect=9:16", {"resolution":"x"})
probe("unknown_cap", "/api/capabilities/scene3d.nope/preview?aspect=9:16", {"resolution":270})
# capability layer short duration
from hevi.capabilities import get, CapabilityError
cap = get("scene3d.fox_wheat")
for d in (1.0, 1.99):
    try:
        r = cap.render({"resolution":270}, tempfile.mkdtemp(dir=".tmp"), duration=d, aspect="9:16", seed=5)
        out[f"cap_duration_{d}"]={"result":"rendered","mp4":str(r.mp4)}
    except CapabilityError as e:
        out[f"cap_duration_{d}"]={"result":"CapabilityError","msg":str(e)[:200]}
    except Exception as e:
        out[f"cap_duration_{d}"]={"result":type(e).__name__,"msg":str(e)[:200]}
    print(d, out[f"cap_duration_{d}"], flush=True)
json.dump(out, open("audit/scene3d/verify_r1d/api_probe.json","w"), indent=1)
print("DONEPROBE")
