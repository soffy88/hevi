import json, time
from pathlib import Path
from hevi.judge.backend import OpencodeJudgeBackend
from hevi.judge.calibration import calibrate

backend = OpencodeJudgeBackend(model="opencode-go/crouton-alpha-free")
audit="/data/soffy/projects/hevi-audit-1106/samples"
integ="/data/soffy/projects/hevi-integ/samples"
pairs=[]
lines=["explainer","cinematic","kinetic_promo","history_scene","talking_head","director_pipeline"]
for l in lines:
    a=f"{audit}/{l}/run1/output.mp4"
    b=f"{integ}/{l}/run1/output.mp4"
    if Path(a).is_file() and Path(b).is_file():
        pairs.append((a,b))
# bad clips vs good explainer integ
good=f"{integ}/explainer/run1/output.mp4"
for bad in ["silent","black","frozen","short2s"]:
    bp=f"/data/soffy/projects/hevi-judge/bad_clips/{bad}.mp4"
    if Path(bp).is_file():
        pairs.append((bp, good))

t=time.time()
res=calibrate(backend, pairs, work_dir=Path("/data/soffy/projects/hevi-judge/calib_tmp"))
print(json.dumps(res, ensure_ascii=False, indent=2))
print("elapsed", round(time.time()-t,1))
Path("/data/soffy/projects/hevi-judge/calib_result.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
