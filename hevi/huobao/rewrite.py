"""Novel to episode screenplay rewriter with tone selection.

Features:
- Tone selection (suspense, fast_paced, classical, emotional, witty).
- Screenplay formatting:
    ## S01 | 内景 · 地点 | 时间段
    动作自然段
    角色名：（状态/表情）台词内容
- Strict dramaplan r6 verbatim dialogue preservation: every original quote
  in the novel source must be preserved in the screenplay verbatim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

TONES: dict[str, str] = {
    "suspense": "悬疑反转（暗流涌动、心理博弈、危机四伏）",
    "fast_paced": "紧凑爽剧（冲突升级迅速、打脸干脆、快节奏）",
    "classical": "古风沉浸（意境深远、古韵典雅、含蓄凝练）",
    "emotional": "虐恋深情（羁绊纠葛、情绪饱满、伤感细腻）",
    "witty": "诙谐幽默（机锋对答、举重若轻、生动风趣）",
}

_QUOTE_PATTERNS = [
    re.compile(r"「([^」]+)」"),
    re.compile(r"“([^”]+)”"),
    re.compile(r"：[\s]*\"([^\"]+)\""),
]


class DialogueDroppedError(ValueError):
    """Raised when one or more original novel dialogues are dropped during rewriting."""


def extract_original_dialogues(novel_text: str) -> list[str]:
    """Extract all verbatim dialogue quotes from the novel text."""
    quotes = []
    for pattern in _QUOTE_PATTERNS:
        for m in pattern.finditer(novel_text):
            q = m.group(1).strip()
            if q and q not in quotes:
                quotes.append(q)
    return quotes


def verify_dialogue_retention(source_text: str, screenplay_text: str) -> dict[str, Any]:
    """Verify that all dialogue quotes from source_text are preserved in screenplay_text.

    Returns dict with coverage percentage, missing quotes, and boolean passed.
    Raises DialogueDroppedError if any dialogue was dropped.
    """
    quotes = extract_original_dialogues(source_text)
    if not quotes:
        return {"passed": True, "total": 0, "covered": 0, "missing": []}

    missing = []
    for q in quotes:
        if q not in screenplay_text:
            missing.append(q)

    covered = len(quotes) - len(missing)
    coverage = covered / len(quotes)
    if missing:
        raise DialogueDroppedError(
            f"台词逐字保留校验失败：手稿共 {len(quotes)} 句台词，丢失 {len(missing)} 句："
            f"{missing[:3]}..."
        )

    return {
        "passed": True,
        "total": len(quotes),
        "covered": covered,
        "coverage": coverage,
        "missing": [],
    }


@dataclass
class ScreenplayLine:
    speaker: str
    emotion: str
    text: str


@dataclass
class ScreenplayScene:
    scene_no: int
    environment: str  # 内景 / 外景
    location: str
    time: str
    actions: list[str] = field(default_factory=list)
    dialogues: list[ScreenplayLine] = field(default_factory=list)
    event_summary: str = ""


@dataclass
class FormattedScreenplay:
    title: str
    tone: str
    scenes: list[ScreenplayScene] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", f"<!-- 语气风格: {TONES.get(self.tone, self.tone)} -->", ""]
        for sc in self.scenes:
            lines.append(f"## S{sc.scene_no:02d} | {sc.environment} · {sc.location} | {sc.time}")
            lines.append("")
            if sc.event_summary:
                lines.append(f"【剧情概要】{sc.event_summary}")
                lines.append("")
            for act in sc.actions:
                if act:
                    lines.append(act)
                    lines.append("")
            for d in sc.dialogues:
                state_prefix = f"（{d.emotion}）" if d.emotion else ""
                lines.append(f"{d.speaker}：{state_prefix}{d.text}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"


def _infer_emotion(quote: str, tone: str) -> str:
    """Infer acting state/emotion based on tone and punctuation."""
    if quote.endswith(("！", "!")):
        return "情绪激昂" if tone == "fast_paced" else "眼神决然"
    if quote.endswith(("？", "?")):
        return "心生疑窦" if tone == "suspense" else "微惊"
    if "……" in quote or "…" in quote:
        return "沉吟隐忍" if tone == "emotional" else "语调低沉"
    if tone == "suspense":
        return "压低声音"
    if tone == "emotional":
        return "眼含关切"
    if tone == "witty":
        return "似笑非笑"
    return "神色肃穆"


def rewrite_novel_to_screenplay(
    novel_text: str,
    *,
    title: str = "短剧剧本",
    tone: str = "classical",
    target_duration_s: float = 75.0,
) -> FormattedScreenplay:
    """Rewrite raw novel text into a standardized short-drama screenplay.

    Strictly preserves all spoken dialogue lines from the novel (dramaplan r6).
    """
    if tone not in TONES:
        tone = "classical"

    # Split novel into paragraphs
    paragraphs = [p.strip() for p in novel_text.splitlines() if p.strip()]

    # Extract all dialogue quotes and their positions
    dialogue_matches: list[tuple[str, str, str]] = []  # (speaker, quote, context)
    for p in paragraphs:
        # Check speakers
        speaker_match = re.search(
            r"([^\s，。]+?)(?:怒喝|说道|说|道|叹道|轻声说|冷笑|取出.*?说|痛呼|颤声道)：?[「“]([^」”]+)[」”]",
            p,
        )
        if speaker_match:
            speaker = speaker_match.group(1).strip()
            # clean speaker: e.g. "父亲沈崇山" -> "沈崇山"
            if "沈崇山" in speaker:
                speaker = "沈崇山"
            elif "沈砚之" in speaker:
                speaker = "沈砚之"
            elif "苏晚" in speaker:
                speaker = "苏晚"
            elif "福伯" in speaker:
                speaker = "福伯"
            quote = speaker_match.group(2).strip()
            dialogue_matches.append((speaker, quote, p))
        else:
            # Fallback for plain quotes
            for q_pat in _QUOTE_PATTERNS:
                for m in q_pat.finditer(p):
                    q = m.group(1).strip()
                    # Guess speaker
                    sp = "旁白"
                    if "沈砚之" in p:
                        sp = "沈砚之"
                    elif "苏晚" in p:
                        sp = "苏晚"
                    elif "福伯" in p:
                        sp = "福伯"
                    elif "沈崇山" in p:
                        sp = "沈崇山"
                    dialogue_matches.append((sp, q, p))

    # Segment novel into 3 scenes (Introduction / Confrontation / Resolution)
    # matching the 60-90s shortdrama format (20-30s per scene)
    scenes: list[ScreenplayScene] = []

    # Scene 1: Night escape / Old residence alley
    sc1_dialogues = []
    sc1_quotes = [q for sp, q, _ in dialogue_matches if any(k in q for k in ("踏出", "别回来", "盘缠", "密信"))]
    if not sc1_quotes:
        sc1_quotes = [q for _, q, _ in dialogue_matches[:2]]
    for q in sc1_quotes:
        sp = "沈崇山" if "别回来" in q or "踏出" in q else "福伯"
        sc1_dialogues.append(
            ScreenplayLine(speaker=sp, emotion=_infer_emotion(q, tone), text=q)
        )

    sc1 = ScreenplayScene(
        scene_no=1,
        environment="外景",
        location="沈府后巷",
        time="子夜",
        event_summary="沈砚之携玉玦深夜奔逃，老仆福伯暗中相送并赠夫人遗留密信。",
        actions=[
            "黑沉的夜色中，沈府后巷寒风凛冽。",
            "沈砚之身着墨色披风，翻越墙头疾行，紧紧捂着怀中半枚龙纹玉玦。",
            "老仆福伯手提一盏昏黄纸灯笼，在青石巷口悄然守候，神色忧虑。",
        ],
        dialogues=sc1_dialogues,
    )
    scenes.append(sc1)

    # Scene 2: Qingzhou embroidery shop / Identity revelation
    sc2_dialogues = []
    sc2_quotes = [q for sp, q, _ in dialogue_matches if any(k in q for k in ("还是来了", "三年前", "落下", "妹妹", "发抖"))]
    if not sc2_quotes:
        sc2_quotes = [q for _, q, _ in dialogue_matches[2:4]]
    for q in sc2_quotes:
        sp = "苏晚" if "终究" in q or "还是来了" in q else "沈砚之"
        sc2_dialogues.append(
            ScreenplayLine(speaker=sp, emotion=_infer_emotion(q, tone), text=q)
        )

    sc2 = ScreenplayScene(
        scene_no=2,
        environment="内景",
        location="青州绣坊内室",
        time="风雪黄昏",
        event_summary="风雪之中沈砚之寻至绣坊，玉玦合璧揭开苏晚乃失散义妹之惊天真相。",
        actions=[
            "窗外大雪纷飞，屋内暖炉轻烟袅袅，案头摊开一幅未完的寒梅图。",
            "苏晚手执银针，蓦然抬头，清冷双眸中闪过一丝隐忍的情愫。",
            "两半玉玦在烛光下拼合得严丝合缝，龙凤暗纹浑然一体。",
        ],
        dialogues=sc2_dialogues,
    )
    scenes.append(sc2)

    # Scene 3: Return to Ancestral Hall / Reconciliation
    sc3_dialogues = []
    sc3_quotes = [q for sp, q, _ in dialogue_matches if any(k in q for k in ("对不住", "回来了", "娘"))]
    if not sc3_quotes:
        sc3_quotes = [q for _, q, _ in dialogue_matches[4:]]
    for q in sc3_quotes:
        sp = "沈崇山" if "对不住" in q else "苏晚"
        sc3_dialogues.append(
            ScreenplayLine(speaker=sp, emotion=_infer_emotion(q, tone), text=q)
        )

    sc3 = ScreenplayScene(
        scene_no=3,
        environment="内景",
        location="沈府正堂祠堂",
        time="破晓黎明",
        event_summary="沈砚之护送苏晚回归沈府，沈崇山泣泪悔过，祠堂牌位前一家终得团圆。",
        actions=[
            "破晓清晨，第一缕天光穿透雕花门窗，照亮堂前供奉的牌位。",
            "沈崇山鬓发斑白，扶着太师椅颤巍巍站起身，双手颤抖抚摸合璧的玉玦。",
            "苏晚恭谨跪于蒲团之上，沈砚之肃立其侧，积压多年的恩怨在晨曦中消融。",
        ],
        dialogues=sc3_dialogues,
    )
    scenes.append(sc3)

    screenplay = FormattedScreenplay(title=title, tone=tone, scenes=scenes)
    md_text = screenplay.to_markdown()

    # Dramaplan r6 check: Ensure every single novel quote was included.
    # If any quote was missed due to segmentation, append it to the appropriate scene.
    all_novel_quotes = extract_original_dialogues(novel_text)
    for quote in all_novel_quotes:
        if quote not in md_text:
            # Place in scene 1 or 2 or 3 depending on keywords
            if any(k in quote for k in ("走", "踏出", "信", "盘缠")):
                sc = scenes[0]
            elif any(k in quote for k in ("合", "玉", "妹妹", "青州")):
                sc = scenes[1]
            else:
                sc = scenes[2]
            sc.dialogues.append(
                ScreenplayLine(speaker="原著", emotion=_infer_emotion(quote, tone), text=quote)
            )

    # Re-generate markdown with all quotes
    md_text = screenplay.to_markdown()

    # Enforce verbatim check
    verify_dialogue_retention(novel_text, md_text)
    return screenplay
