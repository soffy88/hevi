import copy, json
from pathlib import Path
from hevi.kids.story_gate import kids_story_gate
FIX=Path("tests/fixtures/kids"); fox=json.loads((FIX/"story_fox_star.json").read_text())
def run(label, beat_i, text, expect):
    s=copy.deepcopy(fox); s["beats"][beat_i]["text"]=text
    try: r=kids_story_gate(s); st=r.status; bad=[f.rule for f in r.findings if f.severity!="PASS"]
    except Exception as e: st="FAIL"; bad=["exc:"+type(e).__name__]
    ok = (st=="PASS") if expect in("PASS","WARN_OK") else st in("FAIL","WARN")
    print("OK  " if ok else "MISS", label, "->", st, bad, "|", text)
run("fp_open",3,"小狐狸打开了门，向大家打招呼。","PASS")
run("fp_sweep",3,"大家一起打扫房间，把玩具放回篮子里。","PASS")
run("fp_umbrella",3,"小狐狸打着小雨伞，走过彩色的小路。","PASS")
run("fp_hot",3,"太阳公公出来啦，小狐狸热得出汗，喝了一大口水。","PASS")
run("fn_hit",3,"小狐狸狠狠地揍了小兔子一顿，小兔子疼得大哭。","FAIL")
run("fn_kick",3,"大家一起踢小松鼠，推他摔进泥坑里嘲弄他。","FAIL")
run("fn_monster",3,"夜里怪兽把小朋友一口吞进肚子里，再也没有出来。","FAIL")
run("fn_poison",3,"小熊偷偷在水里放了毒药，想让朋友们肚子疼。","FAIL")
run("fn_bomb",3,"小狐狸点燃炸弹，轰的一声把房子炸飞了。","FAIL")
run("fn_en",3,"The fox kills the rabbit with a knife and blood everywhere.","FAIL")
run("fn_stranger",3,"陌生叔叔说跟我走吧，小狐狸没告诉爸爸妈妈就自己跟着他走了。","FAIL")
run("fn_insult",3,"大家都骂小刺猬是傻瓜、胖子，没人愿意理他。","FAIL")
