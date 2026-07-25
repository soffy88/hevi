"""N0-D-027 语体量化指标(R-soft 软评,不进硬门)——vo 正文文言度打分。

给每集出一个数:文言标记加权占比。越高越"文言腔"、越低越"口语白话"。白话集设阈值
(按 qwen-max 白话基线校准),超线 R-soft 红旗、不送閘④——治"名叫白话实为文言"。

判据(简易文白判别,非硬门):
- 文言强标记(白话罕用):句末/虚词 之乎矣焉哉者、代词 吾汝尔、发语 夫盖、连词 遂乃亦弗毋於曰岂;
  文言单字死亡/构陷动词 缢谮嬖壅弑薨黜诛篡僭诬。命中 +权重。
- 白话强标记(文言无):的了吗呢、把被、这那、就都还、因为所以于是、多字口语动词。命中 -权重(冲抵)。
纯字符级、零 LLM、确定性可复现。
"""

from __future__ import annotations

# 文言强标记:句末助词/虚词/文言代词/发语词(白话极少单用)
_WENYAN_FN = set("乎矣焉哉者兮之乃遂亦弗毋於曰夫盖惟厥爰兹曷苟岂尔汝吾聿")
# 文言单字动词/名词(白话改用多字词)
_WENYAN_V = set("缢谮嬖壅弑薨崩卒黜诛篡僭诬谒殂薧娶谮")
# 白话强标记(文言几乎不用)——命中冲抵,防术语误伤
_BAIHUA = (
    "的",
    "了",
    "吗",
    "呢",
    "把",
    "被",
    "这",
    "那",
    "就",
    "都",
    "还",
    "因为",
    "所以",
    "于是",
    "为了",
    "没有",
    "自己",
    "起来",
    "已经",
    "然后",
    "这样",
)


def wenyan_hits(text: str) -> dict:
    """返回文言/白话标记命中明细(供可视化)。"""
    wy = [c for c in text if c in _WENYAN_FN or c in _WENYAN_V]
    bh = [w for w in _BAIHUA if w in text]
    return {"wenyan_chars": wy, "baihua_words": bh}


def wenyan_score(text: str) -> float:
    """文言度分数∈[0,1]:文言标记字数 / 有效字数,再按白话标记密度下调。
    越高越文言。纯确定性。"""
    core = [c for c in text if "一" <= c <= "鿿"]  # 只算汉字
    n = len(core)
    if n == 0:
        return 0.0
    wy = sum(1 for c in core if c in _WENYAN_FN or c in _WENYAN_V)
    bh = sum(text.count(w) * len(w) for w in _BAIHUA)  # 白话标记覆盖字数
    raw = wy / n  # 文言标记密度
    baihua_density = min(1.0, bh / n)  # 白话标记密度(封顶1)
    # 白话密度越高越压低文言分(口语连接词多=白话)
    return round(max(0.0, raw * (1.0 - 0.6 * baihua_density)), 4)


def episode_register(draft: dict) -> dict:
    """全集 vo 正文(非 onscreen)合并打分,返回 {score, n_chars, per_sentence[]}。"""
    vo = []
    per = []
    for b in draft.get("beats", []):
        for s in b.get("sentences", []):
            if s.get("presentation") == "onscreen":
                continue  # onscreen 文言引不计(那本就该是文言原文)
            t = s.get("text", "")
            vo.append(t)
            per.append({"sid": s.get("sid"), "score": wenyan_score(t), "text": t})
    allvo = "".join(vo)
    return {
        "score": wenyan_score(allvo),
        "n_chars": sum(1 for c in allvo if "一" <= c <= "鿿"),
        "per_sentence": per,
    }


# 白话集阈值(N0-D-027,按 qwen-max s2 白话版实测校准):
# 文言原版 0.085 / qwen-plus 浅文言 0.058 / qwen-max 白话 0.034。阈值取 0.045——
# 白话(0.034)达标有余量,浅文言(0.058)与文言(0.085)双双红旗。见 docs/DECISIONS-N0。
BAIHUA_THRESHOLD = 0.045


def register_flag(score: float, threshold: float = BAIHUA_THRESHOLD) -> dict:
    """白话集语体红旗:score 超阈=名为白话实为文言,不送閘④。"""
    over = score > threshold
    return {
        "score": score,
        "threshold": threshold,
        "red_flag": over,
        "verdict": "文言腔超标·不送闸④" if over else "白话达标",
    }
