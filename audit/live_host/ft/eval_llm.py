import json,re,sys,time,httpx
sys.path.insert(0,'/data/soffy/projects/hevi-live')
from hevi.live_host.oprim.llm_ollama import SYSTEM_PROMPT
model=sys.argv[1]; qs=json.load(open('heldout.json'))
sysm=SYSTEM_PROMPT.format(persona='小雅',max_chars=60)
bad=re.compile(r'[A-Za-z]|[()（）\[\]【】*]|[\U0001F300-\U0001FAFF\u2600-\u27BF]')
res=[];
for q in qs:
    t=time.time(); first=None; out=''
    with httpx.stream('POST','http://localhost:11434/api/chat',json={'model':model,'stream':True,'messages':[{'role':'system','content':sysm},{'role':'user','content':q}]},timeout=300) as r:
        for l in r.iter_lines():
            if not l: continue
            p=json.loads(l).get('message',{}).get('content','')
            if p and first is None: first=time.time()-t
            out+=p
    res.append({'q':q,'a':out.strip(),'first_tok_s':round(first or 0,2),'total_s':round(time.time()-t,2),'violation':bool(bad.search(out.replace('AI',''))),'chars':len(out.strip())})
n=len(res)
summ={'model':model,'n':n,'violation_rate':round(sum(r['violation'] for r in res)/n,3),'over60':sum(r['chars']>60 for r in res),'avg_chars':round(sum(r['chars'] for r in res)/n,1),'avg_first_tok_s':round(sum(r['first_tok_s'] for r in res)/n,2),'avg_total_s':round(sum(r['total_s'] for r in res)/n,2)}
json.dump({'summary':summ,'rows':res},open(f"eval_{model.replace(':','_').replace('/','_')}.json",'w'),ensure_ascii=False,indent=1)
print(json.dumps(summ,ensure_ascii=False))
for r in res[:25]: print(r['q'],'→',r['a'].replace('\n',' '))
