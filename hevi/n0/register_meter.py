"""N0-D-027/029 语体量化指标(R-soft 软评,不进硬门)——**双向**打分。

目标语体(N0-D-029)= **规范书面史述语**(参照《万历十五年》《叫魂》):既非文言、也非口语聊天腔。
故双向检测,两头都拦:
- **文言度** wenyan_score:文言虚词(之/则/乎/矣/焉)、文言单字动词(缢/谮/嬖/弑/薨/赴)、浅文言词
  (自缢/赴死/随之/由此/式微)。越高越文言。
- **口语度** koutou_score:网络口语/聊天腔(那事儿/哥俩/搞出来/说白了/使坏/吓跑/乱套/挺/特别)。
  越高越随便。
**达标 = 文言度低 且 口语度低**——只放规范书面史述。阈值按 Wiki 锚定样句实测重定基线。
纯字符级、零 LLM、确定性可复现。onscreen 文言引不计。
"""

from __future__ import annotations

# ── 文言标记(penalize 文言度) ──
# 文言虚词/句末助词/书面连词。注:吾/汝/尔 移除(夷吾等人名误伤);诬 移除(诬陷=书面正常)。
_WENYAN_FN = set("乎矣焉哉兮之乃遂亦弗毋於曰夫盖惟厥爰兹曷苟岂聿则")
# 文言单字动词/名词(书面史述改用多字词)
_WENYAN_V = set("缢谮嬖壅弑薨黜诛篡僭殂薧赴")
# 浅文言词(书面史述也不用,有明确白话替代)——命中×1.5 重罚
_SHUMIAN = (
    "自缢",
    "身亡",
    "赴死",
    "遭杀",
    "遇害",
    "遭受",
    "始于",
    "由此",
    "自此",
    "并未",
    "随之",
    "二人",
    "诸子",
    "乃至",
    "式微",
    "遂成",
    "进谗",
    "出奔",
    "所致",
    "以致",
    "继而",
    "旋即",
    "之乱",
    "之序",
    "之叹",
)
# ── 口语标记(penalize 口语度) ──
# 网络口语/聊天腔/过随便的口头语(规范书面史述不用)
_KOUYU = (
    "那事儿",
    "这事儿",
    "哥俩",
    "搞出来",
    "搞",
    "撑场面",
    "撑起",
    "挑大梁",
    "说白了",
    "闹得",
    "挺凶",
    "那会儿",
    "一下子",
    "使坏",
    "吓跑",
    "乱套",
    "散了",
    "跑了",
    "似的",
    "建不起",
    "呗",
    "啦",
    "咋",
    "反正",
    "你想",
    "好几",
    "连自己",
    "没法",
    "特别",
    "挺",
    "一个接一个",
    "中了诅咒",
    "家都",
)
# ── 中性白话粒子(仅冲抵文言度,不算口语随便) ──
_NEUTRAL = ("的", "了", "被", "把", "这", "那", "就", "在", "没有", "已经", "是", "为了")


def _chars(text: str) -> int:
    return sum(1 for c in text if "一" <= c <= "鿿")


def wenyan_hits(text: str) -> dict:
    """命中明细(供可视化——直接指出哪些词现形)。"""
    return {
        "wenyan_chars": [c for c in text if c in _WENYAN_FN or c in _WENYAN_V],
        "shumian_words": [w for w in _SHUMIAN if w in text],
        "kouyu_words": [w for w in _KOUYU if w in text],
    }


def wenyan_score(text: str) -> float:
    """文言度∈[0,1]:(文言单字 + 浅文言词×1.5) / 字数,按中性白话粒子密度轻度下调。越高越文言。"""
    n = _chars(text)
    if n == 0:
        return 0.0
    wy = sum(1 for c in text if c in _WENYAN_FN or c in _WENYAN_V)
    sm = sum(text.count(w) * len(w) for w in _SHUMIAN)
    neu = sum(text.count(w) * len(w) for w in _NEUTRAL)
    raw = (wy + 1.5 * sm) / n
    return round(max(0.0, raw * (1.0 - 0.4 * min(1.0, neu / n))), 4)


def koutou_score(text: str) -> float:
    """口语度∈[0,1]:口语聊天腔标记覆盖字数 / 字数。越高越随便。"""
    n = _chars(text)
    if n == 0:
        return 0.0
    ko = sum(text.count(w) * len(w) for w in _KOUYU)
    return round(min(1.0, ko / n), 4)


def episode_register(draft: dict) -> dict:
    """全集 vo 正文(非 onscreen)双向打分。返回 {wenyan, koutou, n_chars, per_sentence[]}。"""
    vo, per = [], []
    for b in draft.get("beats", []):
        for s in b.get("sentences", []):
            if s.get("presentation") == "onscreen":
                continue
            t = s.get("text", "")
            vo.append(t)
            per.append(
                {
                    "sid": s.get("sid"),
                    "wenyan": wenyan_score(t),
                    "koutou": koutou_score(t),
                    "text": t,
                }
            )
    allvo = "".join(vo)
    return {
        "wenyan": wenyan_score(allvo),
        "koutou": koutou_score(allvo),
        "n_chars": _chars(allvo),
        "per_sentence": per,
    }


# 阈值(N0-D-029,按 Wiki 锚定样句 + 各版实测重定基线;见 docs/DECISIONS-N0)。
WENYAN_MAX = 0.05  # 文言度上限
KOUTOU_MAX = 0.03  # 口语度上限


def register_flag(
    wy: float, ko: float, *, wy_max: float = WENYAN_MAX, ko_max: float = KOUTOU_MAX
) -> dict:
    """规范书面史述达标 = 文言度<wy_max 且 口语度<ko_max。任一超标→红旗、不送片。"""
    wy_over, ko_over = wy > wy_max, ko > ko_max
    if wy_over and ko_over:
        v = "文言腔+口语腔双超标"
    elif wy_over:
        v = "文言腔超标·不送片"
    elif ko_over:
        v = "口语聊天腔超标·不送片"
    else:
        v = "规范书面史述达标"
    return {
        "wenyan": wy,
        "koutou": ko,
        "wy_max": wy_max,
        "ko_max": ko_max,
        "red_flag": wy_over or ko_over,
        "verdict": v,
    }
