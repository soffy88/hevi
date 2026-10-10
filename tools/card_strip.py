"""Render every card in the planner library once (alpha over mesh) for visual curation."""
import json, sys
sys.path.insert(0, '/data/soffy/projects/hevi-talkcraft')
from hevi.layer4_legacy.talkcraft.oskill_impl.shotbook import CARDS, _clip
text = "越早开始越好，因为时间是杠杆。"
kw = "时间"
extra = {"_items": ["尽早开始", "持续投入", "控制成本"], "_title": "让复利工作", "_term": "复利", "_desc": "利息也能继续生利息，越滚越大。", "_num": "02"}
clips, t = [], 0
order = sorted(CARDS)
for cid in order:
    lead_key, alpha, build = CARDS[cid]
    p = build(text, kw, extra)
    if lead_key: p[lead_key] = 0.2
    if alpha: p["__alpha"] = True
    clips.append(_clip(cid, cid, t, 120, p, label=cid)); t += 120
proj = {"name": "strip", "fps": 30, "width": 960, "height": 540, "tracks": [
    {"id": "cards", "name": "c", "clips": clips},
    {"id": "bg", "name": "bg", "clips": [_clip("bg", "bg-mesh", 0, t, {})]}]}
json.dump({"project": proj, "renderExact": True}, open('/tmp/strip_props.json', 'w'), ensure_ascii=False)
print(len(order), order)
