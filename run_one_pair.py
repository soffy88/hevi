import json, sys, time
from pathlib import Path
from hevi.judge.backend import OpencodeJudgeBackend
from hevi.judge.pairwise import run_pairwise
idx=int(sys.argv[1])
pairs=json.load(open("/data/soffy/projects/hevi-judge/calib_pairs.json"))
p=pairs[idx]
b=OpencodeJudgeBackend(model="opencode-go/crouton-alpha-free")
t=time.time()
cmp=run_pairwise(b, p["a"], p["b"])
res={"idx":idx,"label":p["label"],"winner":cmp.winner,"consistent":cmp.consistent,
     "reason":cmp.reason[:300],"elapsed":round(time.time()-t,1)}
# load existing
out=Path("/data/soffy/projects/hevi-judge/calib_results.json")
data=json.loads(out.read_text()) if out.is_file() else []
data=[d for d in data if d["idx"]!=idx]+[res]
out.write_text(json.dumps(data,ensure_ascii=False,indent=2))
print(json.dumps(res,ensure_ascii=False))
