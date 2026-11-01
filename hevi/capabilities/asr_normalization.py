"""Traditional-to-simplified normalisation for ASR observed text.

The observed side of an ASR coverage comparison is normalised before
scoring; the expected script text is NEVER touched (see
``hevi.capabilities.prompt_eval_harness._containment_coverage``).
Normalisation is: traditional -> simplified (t2s), then the audited
ASR glossary (``hevi.capabilities.asr_glossary``). It is never
skipped silently: every result records which backend produced it,
and requesting the OpenCC backend when OpenCC is not importable
raises instead of falling back quietly.

Backends
--------
``builtin`` (default): a minimal single-character t2s table kept in
this module. It covers the characters that occur in the audited
2026-11-01 ASR-fix transcripts plus common traditional forms. The
table was checked character-by-character against OpenCC ``t2s`` on
the measurement machine; entries that disagreed with OpenCC were
dropped, so the built-in backend reproduces OpenCC on the audited
transcripts exactly. Context-sensitive characters follow the OpenCC
default: ``著`` is left untouched (it is also a simplified character,
e.g. ``著名``), and ``乾``/``幹`` map to ``干`` exactly as OpenCC
``t2s`` does.

``opencc``: the ``opencc-python-reimplemented`` package, used only
when it imports. The hevi ``.venv`` does not ship it (system Python
does), so this backend is opt-in; callers that need it must install
the package or run under an interpreter that has it.

``none``: explicit opt-out, recorded as such in evidence. The text
is returned unchanged and the glossary is NOT applied either: a
caller that disables normalisation gets the raw text, labelled raw.
"""

from __future__ import annotations

from typing import Any

from hevi.capabilities.asr_glossary import GLOSSARY_VERSION, apply_asr_glossary

# Built-in minimal traditional -> simplified table. Single characters
# only, each mapping verified against OpenCC t2s (see module
# docstring). Deliberately absent: 著 (also simplified), 妳/您 and
# other context-sensitive forms OpenCC does not map 1:1.
_T2S: dict[str, str] = {
    "萬": "万", "與": "与", "學": "学", "會": "会", "興": "兴",
    "舉": "举", "歡": "欢", "觀": "观", "讓": "让", "說": "说",
    "話": "话", "語": "语", "認": "认", "識": "识", "體": "体",
    "麵": "面", "頭": "头", "髮": "发", "發": "发", "關": "关",
    "開": "开", "門": "门", "問": "问", "間": "间", "聞": "闻",
    "閱": "阅", "讀": "读", "書": "书", "畫": "画", "晝": "昼",
    "歲": "岁", "歷": "历", "邊": "边", "遠": "远", "還": "还",
    "這": "这", "麼": "么", "嗎": "吗", "們": "们", "兩": "两", "親": "亲", "兒": "儿",
    "幾": "几", "機": "机", "樂": "乐", "驚": "惊", "險": "险",
    "驗": "验", "證": "证", "職": "职", "選": "选", "釋": "释",
    "適": "适", "達": "达", "運": "运", "動": "动", "園": "园",
    "圓": "圆", "員": "员", "願": "愿", "顧": "顾", "顯": "显",
    "觸": "触", "覺": "觉", "覽": "览", "計": "计", "記": "记",
    "許": "许", "評": "评", "詩": "诗", "詞": "词", "試": "试",
    "課": "课", "調": "调", "談": "谈", "講": "讲", "謝": "谢",
    "豐": "丰", "豔": "艳", "麗": "丽", "麥": "麦", "龍": "龙",
    "龜": "龟", "魚": "鱼", "鳥": "鸟", "馬": "马", "鳳": "凤",
    "鶴": "鹤", "陽": "阳", "蓋": "盖", "電": "电", "來": "来",
    "裏": "里", "裡": "里", "鄧": "邓", "該": "该", "點": "点",
    "幫": "帮", "屜": "屉", "燈": "灯", "籠": "笼", "條": "条",
    "寫": "写", "過": "过", "乾": "干", "幹": "干", "隻": "只",
    "餘": "余", "後": "后", "雲": "云", "葉": "叶", "廣": "广",
    "闊": "阔", "華": "华", "勞": "劳", "勢": "势", "務": "务",
    "戰": "战", "戲": "戏", "敵": "敌", "數": "数", "斷": "断",
    "時": "时", "曉": "晓", "曬": "晒", "暢": "畅", "權": "权",
    "聲": "声", "處": "处", "號": "号", "慮": "虑", "虛": "虚",
    "螢": "萤", "營": "营", "熒": "荧", "燦": "灿", "爛": "烂",
    "潔": "洁", "淨": "净", "淺": "浅", "測": "测", "湯": "汤",
    "溫": "温", "濕": "湿", "濟": "济", "濤": "涛", "濃": "浓",
    "灣": "湾", "災": "灾", "無": "无", "熱": "热", "燒": "烧",
    "燭": "烛", "爐": "炉", "煙": "烟", "絲": "丝", "紙": "纸",
    "細": "细", "組": "组", "終": "终", "結": "结", "給": "给",
    "絡": "络", "絕": "绝", "統": "统", "經": "经", "線": "线",
    "緣": "缘", "緊": "紧", "紅": "红", "級": "级", "紀": "纪",
    "紋": "纹", "紗": "纱", "納": "纳", "純": "纯", "紹": "绍",
    "織": "织", "繪": "绘", "繼": "继", "續": "续", "纖": "纤",
    "維": "维", "綱": "纲", "網": "网", "綁": "绑", "緩": "缓",
    "練": "练", "縣": "县", "總": "总", "繩": "绳", "車": "车",
    "輕": "轻", "載": "载", "輝": "辉", "輩": "辈", "輪": "轮",
    "輸": "输", "轉": "转", "轍": "辙", "轟": "轰", "軟": "软",
    "軍": "军", "軌": "轨", "軒": "轩", "軸": "轴", "較": "较",
    "輔": "辅", "錢": "钱", "鐘": "钟", "鍵": "键", "鎮": "镇",
    "鏡": "镜", "鐵": "铁", "銀": "银", "銅": "铜", "鋼": "钢",
    "針": "针", "鈴": "铃", "鋪": "铺", "錯": "错", "錫": "锡",
    "錄": "录", "鍛": "锻", "鍊": "炼", "鎖": "锁", "鑽": "钻",
    "長": "长", "閉": "闭", "閃": "闪", "閒": "闲", "闖": "闯",
    "隊": "队", "陰": "阴", "階": "阶", "隨": "随", "隱": "隐",
    "隸": "隶", "雙": "双", "雜": "杂", "離": "离",
    "難": "难", "雞": "鸡", "霧": "雾", "靈": "灵", "響": "响",
    "頁": "页", "頂": "顶", "頃": "顷", "順": "顺", "須": "须",
    "預": "预", "領": "领", "顏": "颜", "類": "类", "題": "题",
    "額": "额", "顛": "颠", "風": "风", "飛": "飞", "飯": "饭",
    "飲": "饮", "餓": "饿", "館": "馆", "餃": "饺", "餅": "饼",
    "餵": "喂", "養": "养", "駕": "驾", "駛": "驶", "駐": "驻",
    "髒": "脏", "鬆": "松", "鬍": "胡", "鬧": "闹", "鬱": "郁",
    "魯": "鲁", "鮮": "鲜", "黨": "党", "齊": "齐", "齒": "齿",
    "辦": "办", "辭": "辞", "辯": "辩", "農": "农", "遲": "迟",
    "遷": "迁", "進": "进", "週": "周", "遊": "游", "遞": "递",
    "導": "导", "尋": "寻", "產": "产", "嚴": "严", "廠": "厂",
    "慶": "庆", "庫": "库", "應": "应", "廟": "庙", "廢": "废",
    "廚": "厨", "廳": "厅", "曆": "历", "壓": "压", "壞": "坏",
    "壟": "垄", "賣": "卖", "殼": "壳", "殺": "杀", "歸": "归",
    "殘": "残", "毀": "毁", "氈": "毡", "氣": "气", "沒": "没",
    "況": "况", "決": "决", "沖": "冲", "涼": "凉", "減": "减",
    "滿": "满", "漢": "汉", "潛": "潜", "濁": "浊", "澤": "泽",
    "濱": "滨", "瀏": "浏", "爭": "争", "爲": "为", "爺": "爷",
    "爾": "尔", "牆": "墙", "壯": "壮", "備": "备", "夠": "够",
    "夢": "梦", "夥": "伙", "夾": "夹", "奪": "夺", "奮": "奋",
    "奐": "奂", "奧": "奥", "婦": "妇", "婁": "娄", "嬰": "婴",
    "嬸": "婶", "孃": "娘", "寧": "宁", "寶": "宝", "實": "实",
    "審": "审", "寢": "寝", "寬": "宽", "寵": "宠", "將": "将",
    "專": "专", "對": "对", "層": "层", "屆": "届", "屬": "属",
    "島": "岛", "峽": "峡", "崍": "崃", "嵐": "岚", "嶺": "岭",
    "嶽": "岳", "巒": "峦", "巖": "岩", "帥": "帅", "帳": "帐",
    "帶": "带", "幣": "币", "張": "张", "強": "强", "彈": "弹",
    "彎": "弯", "彥": "彦", "徑": "径", "從": "从", "復": "复",
    "悅": "悦", "惡": "恶", "惱": "恼", "愛": "爱", "態": "态",
    "懶": "懒", "懷": "怀", "懸": "悬", "戀": "恋", "拋": "抛",
    "掛": "挂", "捨": "舍", "捲": "卷", "掃": "扫", "採": "采",
    "掙": "挣", "擺": "摆", "擔": "担", "擋": "挡",
    "擴": "扩", "攏": "拢", "攜": "携", "攝": "摄",
}

# Backend identifiers recorded in evidence. "builtin" is the default
# and the only backend the coverage comparison uses, so a score is
# reproducible on any machine regardless of OpenCC availability.
NORMALIZATION_BACKENDS = ("builtin", "opencc", "none")


def traditional_to_simplified(text: str, *, backend: str = "builtin") -> str:
    """Convert traditional characters in ``text`` to simplified ones.

    ``builtin`` uses the table above; ``opencc`` uses the OpenCC
    package and raises :class:`RuntimeError` when it cannot be
    imported (never a silent skip); ``none`` returns ``text``
    unchanged. The expected script side must never be passed here.
    """
    if backend == "none":
        return str(text)
    if backend == "builtin":
        return "".join(_T2S.get(ch, ch) for ch in str(text))
    if backend == "opencc":
        try:
            from opencc import OpenCC
        except ImportError as exc:
            raise RuntimeError(
                "audio.asr_transcribe: OpenCC backend requested but "
                "opencc-python-reimplemented is not importable in this "
                "environment; install it or use normalization='builtin'"
            ) from exc
        return OpenCC("t2s").convert(str(text))
    raise ValueError(
        f"audio.asr_transcribe: unknown normalization backend {backend!r}; "
        f"expected one of {NORMALIZATION_BACKENDS}"
    )


def normalize_observed_text(
    text: str,
    *,
    normalization: str = "builtin",
    apply_glossary: bool = True,
) -> dict[str, Any]:
    """Normalise observed (transcribed) text and report every step.

    Returns a dict with ``raw`` (input untouched), ``t2s`` (after the
    traditional-to-simplified step), ``normalized`` (after the glossary
    step, or equal to ``t2s`` when the glossary is disabled),
    ``glossary_hits``, ``glossary_version`` (or ``None`` when the
    glossary was disabled or normalisation was ``none``), and
    ``normalization_backend``. Nothing here ever rewrites the input
    in place: callers keep ``raw`` as the original evidence.
    """
    raw = str(text)
    if normalization == "none":
        return {
            "raw": raw,
            "t2s": raw,
            "normalized": raw,
            "glossary_hits": [],
            "glossary_version": None,
            "normalization_backend": "none",
            "normalization_applied": False,
            "warning": (
                "normalization explicitly disabled (normalization='none'); "
                "raw transcript is used as-is and no glossary was applied"
            ),
        }
    t2s = traditional_to_simplified(raw, backend=normalization)
    if apply_glossary:
        normalized, hits = apply_asr_glossary(t2s)
        version: str | None = GLOSSARY_VERSION
    else:
        normalized, hits, version = t2s, [], None
    return {
        "raw": raw,
        "t2s": t2s,
        "normalized": normalized,
        "glossary_hits": hits,
        "glossary_version": version,
        "normalization_backend": normalization,
        "normalization_applied": True,
    }


def normalized_text_only(
    text: str,
    *,
    normalization: str = "builtin",
    apply_glossary: bool = True,
) -> str:
    """The normalised string only (for coverage comparisons)."""
    return normalize_observed_text(
        text, normalization=normalization, apply_glossary=apply_glossary
    )["normalized"]
