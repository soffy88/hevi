import json,re,sys,time
sys.path.insert(0,'/data/soffy/projects/hevi-live')
from hevi.live_host.oprim.llm_ollama import OllamaLLM
m=OllamaLLM(model=sys.argv[1],max_reply_chars=60); qs=json.load(open('heldout.json'))
bad=re.compile(r'[A-Za-z]|[()（）\[\]【】*<>]|[\U0001F300-\U0001FAFF\u2600-\u27BF]')
rows=[]
for q in qs:
    t=time.time(); first=None; out=''
    for s in m.stream_reply(q):
        if first is None: first=time.time()-t
        out+=s
    rows.append({'q':q,'a':out,'first_sentence_s':round(first or 0,2),'violation':bool(bad.search(out.replace('AI',''))),'empty':not out})
n=len(rows); s={'model':sys.argv[1],'n':n,'violation_rate':sum(r['violation'] for r in rows)/n,'empty':sum(r['empty'] for r in rows),'avg_chars':round(sum(len(r['a']) for r in rows)/n,1),'avg_first_sentence_s':round(sum(r['first_sentence_s'] for r in rows)/n,2)}
json.dump({'summary':s,'rows':rows},open(f'stream_{sys.argv[1]}.json','w'),ensure_ascii=False,indent=1)
print(json.dumps(s,ensure_ascii=False))
for r in rows: print(r['q'],'→',r['a'])
