"""R4 verifier probe: lexicon breadth beyond the FIX-listed samples.

Independent fresh sentences (NOT in any FIX order / prior probe) using common
child-relevant harm words. Hard gate KIDS_ANIME_DIRECTION.md L11 forbids
"暴力、血、武器、恐怖画面、惊吓、危险行为示范、嘲笑与羞辱".
"""
from hevi.quality.kids_gate import check_content_safety_text as c

CASES = [
    ("勒脖子",        "小狐狸用绳子把小兔勒住了脖子。",              "violence"),
    ("揪耳朵按地",    "坏孩子揪住小熊的耳朵，把他按在地上。",        "violence"),
    ("踹飞",          "大灰狼一脚把小猪踹飞了。",                    "violence"),
    ("针扎",          "小狐狸拿针扎了小兔的手。",                    "violence"),
    ("绑树堵嘴",      "他们把小熊绑在树上，还堵住了他的嘴。",        "violence"),
    ("鞭打",          "小狐狸狠狠抽了小马一鞭子。",                  "violence"),
    ("狗咬",          "小猫被大狗咬得直叫。",                        "violence"),
    ("扯断尾巴",      "小狐狸把小猫的尾巴扯断了。",                  "violence"),
    ("关笼子",        "坏人把小熊关进了笼子里。",                    "intimidation"),
    ("棍子敲头",      "小狐狸拿棍子敲了小兔的头。",                  "violence"),
    ("摔断腿",        "小兔从高高的树上摔下来，摔断了腿。",          "violence"),
    ("踩踏",          "小狐狸一脚踩在小猫身上。",                    "violence"),
    ("踢打",          "小狐狸对着小兔又踢又打。",                    "violence"),
]

print(f"{'verdict':8} {'category':14} {'hits':30} sentence")
miss = []
for name, text, cat in CASES:
    r = c(text)
    verdict = "FAIL" if r else "PASS!!"
    if not r:
        miss.append((name, text, cat))
    print(f"{verdict:8} {cat:14} {str(r):30} {text}")
print(f"\nMISS (harmful PASSed, should FAIL): {len(miss)}/{len(CASES)}")
