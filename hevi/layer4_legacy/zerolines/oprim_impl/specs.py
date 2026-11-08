"""Zero-cost line primitives: line specs, QA thresholds, request contract.

Pure data only (oprim layer): no IO, no subprocess, no imports from the
oskill/omodul siblings.  Every number here is a *gate*, not a claim: the
omodul transaction measures the rendered MP4 and compares it with these.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

#: the 12 canonical Studio lines that have a zero-cost (CPU, no paid API) engine
ZERO_LINES: tuple[str, ...] = (
    "kinetic_promo",
    "explainer",
    "cinematic",
    "director_pipeline",
    "history_scene",
    "character_animation",
    "talking_head",
    "avatar_spokesperson",
    "shorts_clip",
    "podcast_repurpose",
    "reference_adapt",
    "comic_narration",
)

#: canonical lines that intentionally keep their original implementation only
LEGACY_ONLY_LINES: tuple[str, ...] = ("documentary_montage", "localization_dub")

ENGINES: tuple[str, ...] = ("zero", "legacy")


@dataclass(frozen=True)
class QAThresholds:
    """Measured-gate thresholds.  ``None`` = check not applicable to this format
    (the record lists it under ``checks_not_applicable`` with the reason)."""

    min_motion: float = 1.0
    max_static_ratio: float = 0.5
    max_black_ratio: float | None = 0.1
    max_dark_ratio: float | None = 0.5
    min_volume_db: float = -45.0
    expect_audio: bool = True
    min_duration_s: float = 6.0
    not_applicable_reason: str = ""


@dataclass(frozen=True)
class ZeroLineSpec:
    line_id: str
    width: int
    height: int
    inputs: tuple[str, ...]  # required request fields
    qa: QAThresholds = field(default_factory=QAThresholds)
    max_texts: int | None = None
    description: str = ""


_DEF = QAThresholds()

LINE_SPECS: dict[str, ZeroLineSpec] = {
    "kinetic_promo": ZeroLineSpec(
        "kinetic_promo", 720, 1280, ("texts", "queries"),
        description="stock b-roll + per-clause kinetic typography (ASS transforms) + bright BGM",
    ),
    "explainer": ZeroLineSpec(
        "explainer", 720, 1280, ("texts", "queries"),
        description="one stock shot per narration line, numbered headings, captions",
    ),
    "cinematic": ZeroLineSpec(
        "cinematic", 720, 1280, ("texts", "queries"),
        # letterbox bars (2 x 12% of height) + night grade: black frames are by design,
        # so the black-frame ceiling is raised to 0.25 (still gated), dark-card stays 0.5
        qa=QAThresholds(max_black_ratio=0.25),
        description="graded letterboxed b-roll film, slower read, title card",
    ),
    "director_pipeline": ZeroLineSpec(
        "director_pipeline", 720, 1280, ("texts", "queries"),
        description="rule-based director: beat -> shot spec (size/camera/query) -> assembly; writes shot_list.json",
    ),
    "history_scene": ZeroLineSpec(
        "history_scene", 720, 1280, ("texts", "queries"),
        description="archival-graded b-roll, year/label lower-thirds",
    ),
    "character_animation": ZeroLineSpec(
        "character_animation", 720, 1280, ("texts",),
        qa=QAThresholds(min_motion=0.4, min_duration_s=8.0),
        max_texts=4,
        description="procedural 2D caveman (PIL): walk, crouch+pick stone, light torch, turn; lines timed to actions",
    ),
    "talking_head": ZeroLineSpec(
        "talking_head", 720, 1280, ("texts",),
        qa=QAThresholds(min_motion=0.3),
        description="2D illustrated presenter, mouth driven by VO RMS (5 visemes); not a photoreal avatar",
    ),
    "avatar_spokesperson": ZeroLineSpec(
        "avatar_spokesperson", 720, 1280, ("texts", "queries"),
        description="stock b-roll + circular 2D presenter PiP (RMS lip-sync) + lower third + CTA card",
    ),
    "shorts_clip": ZeroLineSpec(
        "shorts_clip", 720, 1280, ("media_path",),
        description="whisper word timestamps -> 18-32 s windows -> 9:16 blurred-fill reframe + word captions",
    ),
    "podcast_repurpose": ZeroLineSpec(
        "podcast_repurpose", 1080, 1080, ("media_path",),
        qa=QAThresholds(
            min_motion=0.5, max_dark_ratio=None,
            not_applicable_reason="audiogram uses a deliberate dark backdrop; gated by motion/static instead",
        ),
        description="audiogram: cover + live waveform + captions + progress bar",
    ),
    "reference_adapt": ZeroLineSpec(
        "reference_adapt", 720, 1280, ("media_path", "texts", "offsets"),
        # orbital night passes in the reference are legitimately black
        qa=QAThresholds(max_black_ratio=0.35),
        description="re-structured reference segments + new narration, grade, moves, transitions",
    ),
    "comic_narration": ZeroLineSpec(
        "comic_narration", 1080, 1920, ("topic",),
        qa=QAThresholds(min_motion=0.5, min_duration_s=10.0),
        description="Pixelle-style comic narration: prompt/story -> script -> per-sentence AI keyframes + TTS + BGM + Ken Burns + subtitles",
    ),
}


@dataclass(frozen=True)
class ZeroLineRequest:
    line_id: str
    texts: tuple[str, ...] = ()
    queries: tuple[str, ...] = ()
    topic: str = ""
    title: str = ""
    lang: str = "zh"
    media_path: str = ""
    offsets: tuple[float, ...] = ()
    labels: tuple[str, ...] = ()
    extras: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        spec = LINE_SPECS.get(self.line_id)
        if spec is None:
            return [f"line {self.line_id!r} has no zero-cost engine"]
        errors: list[str] = []
        for name in spec.inputs:
            if not getattr(self, name):
                if self.line_id == "comic_narration" and name == "topic" and self.texts:
                    continue
                errors.append(f"{self.line_id}: missing required input {name!r}")
        if "queries" in spec.inputs and self.texts and self.queries and self.line_id not in {
            "kinetic_promo", "avatar_spokesperson"
        } and len(self.queries) < len(self.texts):
            errors.append(f"{self.line_id}: need one b-roll query per narration line "
                          f"({len(self.queries)} queries for {len(self.texts)} lines)")
        if self.line_id == "reference_adapt" and self.offsets and len(self.offsets) != len(self.texts):
            errors.append("reference_adapt: offsets must align 1:1 with texts")
        if spec.max_texts is not None and len(self.texts) > spec.max_texts:
            errors.append(f"{self.line_id}: at most {spec.max_texts} narration lines")
        if self.lang not in ("zh", "en"):
            errors.append(f"unsupported language {self.lang!r} (zh|en)")
        if any(not t.strip() for t in self.texts):
            errors.append("empty narration line")
        if self.lang == "zh":
            import re as _re
            for t in self.texts:
                if _re.search(r"[A-Za-z]{2,}", t):
                    errors.append(f"{self.line_id}: narration must be Chinese (no Latin letters): {t!r}")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_engine(*, line_id: str, slot_engine: Any = None, env_engine: Any = None) -> str:
    """Engine policy: explicit order slot > deployment env (HEVI_LINE_ENGINE) > legacy.

    Lines without a zero implementation always resolve to ``legacy``.  An
    unknown engine name is an error (never silently mapped).
    """
    raw = slot_engine if slot_engine not in (None, "") else env_engine
    chosen = str(raw).strip().lower() if raw not in (None, "") else "legacy"
    if chosen not in ENGINES:
        raise ValueError(f"unknown line engine {chosen!r}; expected one of {ENGINES}")
    if line_id not in ZERO_LINES:
        return "legacy"
    return chosen


_LINE_SCRIPT_TEMPLATES: dict[str, list[str]] = {
    "kinetic_promo": [
        "{topic}，三秒抓住你的眼球！",
        "节奏拉满，画面跟着鼓点跳。",
        "字幕炸开，信息一秒到位。",
        "别眨眼，高潮就在下一拍。",
        "快切、推进、再来一个特写。",
        "记住这个名字，也记住这个瞬间。",
        "现在就去试试，别错过。",
    ],
    "explainer": [
        "今天我们用{topic}讲清楚一个概念。",
        "先说它是什么，以及为什么值得关注。",
        "把复杂的问题，拆成几个清楚的步骤。",
        "再看一个值得记住的具体细节。",
        "数据和例子，会让抽象变得具体。",
        "其中也有容易被忽略的反面。",
        "最后，给你一个可以立刻用上的结论。",
    ],
    "cinematic": [
        "{topic}，在光影里慢慢展开。",
        "风从远处吹来，世界安静下来。",
        "镜头贴着呼吸，缓慢向前推进。",
        "一个眼神，藏着没有说出口的话。",
        "光线落下，时间像被拉长。",
        "远方的轮廓，终于显出行迹。",
        "故事结束，回声还在。",
    ],
    "director_pipeline": [
        "第一场：{topic}，全景建立空间。",
        "第二场：中景推进，交代人物关系。",
        "第三场：特写，捕捉手上的细节。",
        "第四场：横向移动，带出环境。",
        "第五场：俯拍，压住整体节奏。",
        "第六场：拉远，留出呼吸。",
        "最后一场：收束全片，停在一个空镜。",
    ],
    "history_scene": [
        "很久以前，{topic}已经留下痕迹。",
        "档案里的纸页，记下了当时的声音。",
        "影像褪色，细节却还清楚。",
        "一件器物，连着一段生活。",
        "一条街巷，走过几代人的脚步。",
        "把碎片拼起来，时间重新有了形状。",
        "回望过去，是为了理解现在。",
    ],
    "character_animation": [
        "小角色登场：{topic}。",
        "它先探出头，看看四周。",
        "然后迈开步子，走向前面。",
        "一个动作，胜过千言万语。",
        "停下、转身、再抬手示意。",
        "节奏跟着动作，一点点展开。",
        "动画结束，微笑留下。",
    ],
    "talking_head": [
        "大家好，今天我们聊聊{topic}。",
        "我先给你一个直观的感受。",
        "这件事，远比看上去复杂。",
        "我们把它拆成三个关键点。",
        "第一点，先看它的来龙去脉。",
        "第二点，看看它影响了谁。",
        "希望对你有帮助，我们下期见。",
    ],
    "avatar_spokesperson": [
        "欢迎收看本期节目，主题是{topic}。",
        "我是你的主持人，带你深入了解。",
        "今天的节目，准备了三个部分。",
        "先看背景，再看现场。",
        "接着请出两位当事人。",
        "最后给出我们的观察。",
        "感谢收看，记得关注。",
    ],
    "shorts_clip": [
        "你绝对想不到{topic}的反应！",
        "三秒高能，别划走。",
        "这就是全部真相。",
        "点赞关注，下期更精彩。",
    ],
    "podcast_repurpose": [
        "今天我们请到嘉宾，聊聊{topic}。",
        "先从一个故事开始。",
        "中间穿插几段精彩对话。",
        "最后总结给听众的启示。",
    ],
    "reference_adapt": [
        "参考镜头的节奏，我们重新演绎{topic}。",
        "保留原来的运镜，换上新旁白。",
        "关键画面重新排序，重点更清楚。",
        "色调统一，字幕跟着语速走。",
        "快的地方更快，慢的地方留白。",
        "新的故事，仍沿用熟悉的骨架。",
        "成品更贴合你的需求。",
    ],
    "comic_narration": [
        "第一格：{topic}登场。",
        "第二格：发生意外。",
        "第三格：反转来了。",
        "第四格：结局出人意料。",
    ],
    "documentary_montage": [
        "镜头记录{topic}的完整过程。",
        "从准备到高潮，一气呵成。",
        "每帧都是真实瞬间。",
        "纪录片的温度，在细节里。",
    ],
    "localization_dub": [
        "This is {topic} in a new voice.",
        "We dub and subtitle for you.",
        "Same story, new language.",
        "Enjoy the localized version.",
    ],
    "handdraw": [
        "从前有一只小家伙，第一次遇见{topic}。",
        "画笔慢慢勾勒出海边的风景。",
        "一笔一画，都是心意。",
        "故事画完，梦还没醒。",
    ],
    "scene3d": [
        "在三维场景中，{topic}立体呈现。",
        "镜头环绕，空间感十足。",
        "光影变化，突出主体。",
        "渲染完成，所见即所得。",
    ],
}


def generate_script_lines(topic: str, *, lang: str = "zh", n: int = 4, line_id: str = "") -> tuple[str, ...]:
    """Deterministic per-line narration fallback.

    Used when a request supplies only a topic.  Each production line has its
    own template (structure / tone / voice) so that the 16 lines never share
    the same narration text.  ``line_id`` selects the template; unknown lines
    fall back to a generic but line-salted skeleton.  A free LLM may be used
    when ``HEVI_USE_FREE_LLM_SCRIPTS=1`` and a channel is available.
    """
    topic = (topic or "").strip()
    if not topic:
        return ()
    templates = None
    if line_id and line_id in _LINE_SCRIPT_TEMPLATES:
        templates = _LINE_SCRIPT_TEMPLATES[line_id]
    if templates is None:
        salt = line_id or "default"
        if lang == "en":
            templates = [
                f"Today we explore {topic} ({salt}).",
                "First, what it is and why it matters.",
                "Then, one concrete detail worth remembering.",
                "Finally, a takeaway you can use right away.",
            ]
        else:
            templates = [
                f"今天，我们聊聊{topic}（{salt}视角）。",
                "先说它是什么，以及为什么值得关注。",
                "再看一个值得记住的具体细节。",
                "最后，给你一个可以立刻用上的结论。",
            ]
    if os.environ.get("HEVI_USE_FREE_LLM_SCRIPTS") == "1":
        try:
            import asyncio

            from hevi.providers.free_llm import resolve_free_llm

            _ch, caller = resolve_free_llm("auto")

            async def _run():
                style_hint = line_id or "generic"
                prompt = (
                    f"请为视频脚本写{n}句中文旁白，主题：{topic}，风格：{style_hint}。"
                    "只输出JSON数组，不要其它文字。"
                )
                resp = await caller(messages=[{"role": "user", "content": prompt}], max_tokens=512)
                import json as _json

                content = resp.get("content", "")
                arr = _json.loads(content.strip().strip("`").strip())
                if isinstance(arr, list):
                    return [str(x) for x in arr][:n]
                return []

            out = asyncio.run(asyncio.wait_for(_run(), timeout=8.0))
            if out and len(out) >= max(1, n // 2):
                return tuple(out[: max(1, n)])
        except Exception:
            pass
    base = [t.format(topic=topic) for t in templates]
    return tuple(base[: max(1, n)])


def generate_broll_queries(
    topic: str,
    texts: tuple[str, ...] = (),
    *,
    lang: str = "zh",
    line_id: str = "",
    subject_hint: str = "",
) -> tuple[str, ...]:
    """Derive English b-roll queries from the topic, differentiated per line.

    ``subject_hint`` is an optional English rendering of the topic (the IO layer
    may translate it with a free service); when empty, ASCII topics are used
    directly and a small keyword map covers the common Chinese subjects.  The
    old hard-coded "orange tabby cat on a beach" default is gone: an unknown
    topic gets neutral visual queries instead of off-topic cat footage.
    """
    t = (topic or "").strip()
    subject = subject_hint.strip()
    if not subject:
        subject = _topic_subject(t) or ("visual story" if not _is_ascii(t) else t)
    subject = subject.strip(" .,;:!?，。；：！？") or "visual story"

    per_line = {
        "kinetic_promo": [
            f"{subject} dynamic motion",
            f"{subject} fast action",
            f"{subject} bright detail",
            f"{subject} close up",
            f"{subject} wide shot",
            f"{subject} slow motion",
            f"{subject} energy",
            f"{subject} portrait",
        ],
        "explainer": [
            f"{subject} close up",
            f"{subject} detail",
            f"{subject} wide shot",
            f"{subject} texture",
            f"{subject} macro",
            f"{subject} in context",
            f"{subject} background",
            f"{subject} overview",
        ],
        "cinematic": [
            f"{subject} cinematic wide",
            f"{subject} slow motion",
            f"{subject} golden hour",
            f"{subject} silhouette",
            f"{subject} aerial",
            f"{subject} detail",
            f"{subject} atmosphere",
            f"{subject} night",
        ],
        "director_pipeline": [
            f"{subject} wide shot",
            f"{subject} medium shot",
            f"{subject} close up",
            f"{subject} detail",
            f"{subject} profile",
            f"{subject} environment",
            f"{subject} wide shot",
            f"{subject} still",
        ],
        "history_scene": [
            f"{subject} archival",
            f"{subject} old film",
            f"{subject} museum",
            f"{subject} sepia",
            f"{subject} document",
            f"{subject} ancient",
            f"{subject} wide shot",
            f"{subject} archive",
        ],
        "avatar_spokesperson": [
            f"{subject} background",
            f"{subject} studio",
            f"{subject} workspace",
            f"{subject} wide shot",
            f"{subject} detail",
            f"{subject} in context",
            f"{subject} atmosphere",
            f"{subject} close up",
        ],
        "reference_adapt": [
            f"{subject} wide shot",
            f"{subject} medium shot",
            f"{subject} close up",
            f"{subject} detail",
            f"{subject} movement",
            f"{subject} atmosphere",
            f"{subject} still",
            f"{subject} overview",
        ],
    }
    candidates = per_line.get(
        line_id,
        [
            f"{subject} wide shot",
            f"{subject} close up",
            f"{subject} detail",
            f"{subject} environment",
            f"{subject} portrait",
            f"{subject} overview",
            f"{subject} still",
            f"{subject} movement",
        ],
    )
    seen: set[str] = set()
    out: list[str] = []
    for q in candidates:
        if q not in seen:
            seen.add(q)
            out.append(q)
    target = max(4, len(texts) or 0)
    i = 0
    while len(out) < target:
        out.append(f"{subject} scene {i + 1}")
        i += 1
    return tuple(out[:target])


#: common Chinese subject words -> English Pexels query (used when translation is unavailable)
_TOPIC_MAP: tuple[tuple[str, str], ...] = (
    ("橘猫", "orange tabby cat"), ("橙猫", "orange tabby cat"), ("猫", "cat"),
    ("狗", "dog"), ("熊猫", "panda"), ("鸟", "bird"), ("海", "ocean waves"),
    ("沙滩", "beach sand"), ("山", "mountain landscape"), ("森林", "forest"),
    ("城市", "city skyline"), ("夜景", "city night"), ("街道", "street"),
    ("敦煌", "Dunhuang murals"), ("壁画", "ancient mural"), ("故宫", "Forbidden City"),
    ("长城", "Great Wall of China"), ("茶", "tea ceremony"), ("咖啡", "coffee"),
    ("美食", "food cooking"), ("厨房", "kitchen cooking"), ("面", "noodles"),
    ("量子", "quantum physics"), ("人工智能", "artificial intelligence"),
    ("机器人", "robot"), ("芯片", "computer chip"), ("太空", "outer space"),
    ("火箭", "rocket launch"), ("星球", "planet"), ("星空", "starry sky"),
    ("历史", "history archive"), ("战争", "war history"), ("古", "ancient ruins"),
    ("博物馆", "museum"), ("书法", "calligraphy"), ("绘画", "painting art"),
    ("音乐", "music performance"), ("舞蹈", "dance"), ("电影", "cinema"),
    ("运动", "sports action"), ("足球", "soccer"), ("篮球", "basketball"),
    ("跑步", "running"), ("旅行", "travel landscape"), ("火车", "train"),
    ("飞机", "airplane"), ("汽车", "car driving"), ("工厂", "factory"),
    ("科技", "technology"), ("电脑", "computer"), ("手机", "smartphone"),
    ("医疗", "medical hospital"), ("医生", "doctor"), ("学校", "school classroom"),
    ("孩子", "children playing"), ("老人", "elderly people"), ("家庭", "family"),
    ("花", "flowers"), ("雨", "rain"), ("雪", "snow"), ("风", "wind landscape"),
    ("火", "fire"), ("光", "light abstract"), ("水", "water surface"),
    ("树", "trees"), ("沙漠", "desert"), ("河", "river"), ("湖", "lake"),
    ("建筑", "architecture"), ("桥", "bridge"), ("港口", "harbor"),
    ("渔", "fishing boat"), ("农", "farm field"), ("稻田", "rice field"),
)


def _is_ascii(text: str) -> bool:
    return bool(text) and all(ord(ch) < 128 for ch in text)


def _topic_subject(topic: str) -> str:
    """First matching keyword -> English subject; longest key wins."""
    matches = [en for zh, en in _TOPIC_MAP if zh in topic]
    return max(matches, key=len) if matches else ""


def spec_for(line_id: str) -> ZeroLineSpec:
    try:
        return LINE_SPECS[line_id]
    except KeyError as exc:
        raise KeyError(f"no zero-cost spec for {line_id!r}") from exc


__all__ = [
    "ENGINES",
    "LEGACY_ONLY_LINES",
    "LINE_SPECS",
    "QAThresholds",
    "ZERO_LINES",
    "ZeroLineRequest",
    "ZeroLineSpec",
    "resolve_engine",
    "spec_for",
]
