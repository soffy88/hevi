"""preflight.prompt_audit —— 生成前 prompt／节拍文本审计。

复用仓内既有现代词黑名单（hevi.tongjian.script._MODERN_VOCAB_BLACKLIST），
作用域与通鉴一致：只约束历史叙事段（narration / dialogue / commentary），
modern_echo 鉴今段豁免。导包失败时用同表本地副本兜底（表本身抄自该处，
改动须以通鉴表为准）。

人物可执行性启发规则（WARN，不阻塞）：人物描述里至少要有一个动作／
姿态／支撑类锚词，或附定妆图；只有人名／ID 的，判 WARN。锚词表是
启发式，不是词表全文——词表全文在 hevi/image/portrait_vocab/。
"""

from __future__ import annotations

from typing import Any

from hevi.preflight.beats import Beat
from hevi.preflight.findings import Finding

try:  # 优先复用通鉴既有表
    from hevi.tongjian.script import _MODERN_VOCAB_BLACKLIST as _BLACKLIST
except Exception:  # pragma: no cover - tongjian.script 导包失败时兜底
    _BLACKLIST = [
        "点赞", "关注", "打卡", "网红", "破防", "yyds", "绝绝子",
        "内卷", "躺平", "OK", "拜拜",
    ]

MODERN_BLACKLIST: list[str] = list(_BLACKLIST)

# 无文字声明：中英双语，任一命中即算声明在位。
NO_TEXT_CLAUSES = (
    "no text", "no subtitles", "no subtitle", "no watermark",
    "no written text", "no on-screen text",
    "无文字", "无字幕", "无水印", "不要文字", "不出现文字",
)

# 伪文字高风险场景词：画面出现文字载体时，伪文字概率显著上升。
SIGNAGE_TERMS = ("牌匾", "匾额", "题字", "招牌", "门楣", "榜文", "石碑", "对联")

# 人物可执行性锚词（动作／姿态／支撑／视线类，启发式）。
EXECUTABLE_MARKERS = (
    "站", "坐", "行走", "跑", "跪", "俯身", "转身", "抬头", "低头",
    "注视", "看向", "手持", "伸手", "拱手", "仗剑", "扛", "递",
    "standing", "sitting", "walking", "holding", "looking",
    "raising", "turning", "kneeling", "bowing",
)

# 现代词黑名单只约束历史叙事段；modern_echo 豁免（五段法规范）。
_SCOPED_KINDS = ("narration", "dialogue", "commentary")


def _find_banned(text: str) -> list[str]:
    return [term for term in MODERN_BLACKLIST if term and term in text]


def audit_prompt(beat: Beat, prompt_text: str = "") -> list[Finding]:
    """审计一个 beat 及其编译后 prompt（prompt_text 可空）。"""
    findings: list[Finding] = []

    # 1. 现代词黑名单（按段作用域）
    if beat.kind in _SCOPED_KINDS:
        banned = _find_banned(beat.text)
        if prompt_text:
            banned = sorted(set(banned) | set(_find_banned(prompt_text)))
        if banned:
            findings.append(Finding(
                "FAIL", "modern_vocab",
                f"历史叙事段命中现代词黑名单：{banned}（modern_echo 段才豁免）",
                beat_id=beat.beat_id, detail={"terms": banned},
            ))
    else:
        findings.append(Finding(
            "INFO", "modern_vocab_exempt",
            f"{beat.kind} 段豁免现代词黑名单（五段法作用域）",
            beat_id=beat.beat_id,
        ))

    # 2. 无文字声明（只在提供了编译后 prompt 时硬查；否则 INFO 提醒）
    if not beat.on_screen_text:
        if not prompt_text:
            findings.append(Finding(
                "INFO", "no_text_unchecked",
                "未提供编译后 prompt，无文字声明未核查（编译器默认带 no-text 段）",
                beat_id=beat.beat_id,
            ))
        else:
            lowered = prompt_text.lower()
            if not any(c.lower() in lowered for c in NO_TEXT_CLAUSES):
                findings.append(Finding(
                    "FAIL", "no_text_missing",
                    "编译后 prompt 缺无文字声明：画面伪文字／字幕风险未锁死",
                    beat_id=beat.beat_id,
                ))

    # 3. 定妆引用是否在位
    for ch in beat.characters:
        if ch.sheet_path:
            findings.append(Finding(
                "INFO", "character_sheet_ok",
                f"人物 {ch.char_id} 附定妆引用：{ch.sheet_path}",
                beat_id=beat.beat_id,
            ))
        elif ch.description and any(m in ch.description for m in EXECUTABLE_MARKERS):
            findings.append(Finding(
                "INFO", "character_desc_ok",
                f"人物 {ch.char_id} 有可执行描述（含动作／姿态锚词）",
                beat_id=beat.beat_id,
            ))
        else:
            findings.append(Finding(
                "WARN", "character_ref_weak",
                f"人物 {ch.char_id} 仅 ID、无定妆引用也无可执行描述：脸漂移风险",
                beat_id=beat.beat_id,
            ))

    # 4. 对白在位
    if beat.kind == "dialogue" and not beat.dialogue_text.strip():
        findings.append(Finding(
            "FAIL", "dialogue_missing",
            "演绎段无对白文本：视频模型无话可说",
            beat_id=beat.beat_id,
        ))

    # 5. 伪文字高风险场景（只告警，不硬拦：无 OCR 手段，须人工验首帧）
    risky = [t for t in SIGNAGE_TERMS if t in beat.text or t in beat.scene]
    if risky:
        findings.append(Finding(
            "WARN", "signage_risk",
            f"场景含文字载体 {risky}：伪文字风险高，生成前须人工确认首帧无伪文字",
            beat_id=beat.beat_id, detail={"terms": risky},
        ))

    return findings
