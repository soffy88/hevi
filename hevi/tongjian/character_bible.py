"""L5 角色卡(文本部分)—— script + chapter_ir + constitution → character_bible.json。
见 HEVI-SPEC-01 §5。

**范围说明**:spec §5.1 的 4 个步骤里,这里只实现步骤 2("LLM 依据 chapter_ir + 宪法
visual_style 生成外形描述"),纯文本 LLM 调用,不需要 GPU。步骤 3-4(文生图产出候选
立绘 → VLM 年代审 → 锁定 ref_image/gen_lock 三元组)需要本地 SDXL+IP-Adapter 图像生成,
当前环境 GPU 不可访问(`nvidia-smi`/`torch.cuda.is_available()` 均报错),阻塞在环境
问题上,未实现。`ref_image`/`gen_lock`/`voice_id` 字段留空,等对应能力接入后再补。

G5 门这里也只做文本部分能做的检查(外形描述非空、年代错误词扫描);真正的"VLM 审参考图
服饰年代/性别年龄一致性"同样阻塞在 GPU 上,未实现。
"""

from __future__ import annotations

import logging
from typing import Any

from hevi.tongjian.chapter_ir import _call_llm_json
from hevi.tongjian.schemas import (
    ChapterIR,
    CharacterBible,
    CharacterBibleEntry,
    CharacterIR,
    Constitution,
    GateResult,
    Script,
)

logger = logging.getLogger(__name__)

# 年代错误词起始黑名单(起始版,遇到新违规词直接往里加,不必等 RFC;同 L2 违禁词黑名单的惯例)。
_ANACHRONISM_BLACKLIST = [
    "西装",
    "手机",
    "眼镜",
    "唐装",
    "旗袍",
    "中山装",
    "幞头",
    "龙袍",
    "高跟鞋",
]

_CHARACTER_BIBLE_PROMPT_TEMPLATE = """你是历史短片的角色造型设计师。基于下面每个人物在史料中的身份信息和
整体美术风格,为每个人物写一句话外形描述,并给出时代服制校验说明。

美术风格: {art_direction}
色彩基调: {palette}

人物列表:
{character_lines}

只输出一个 JSON 对象:
{{"characters": [
  {{"character_id": "...", "appearance": "外形描述(年龄/体态/服饰/神情,需符合时代)",
    "era_check": "时代服制校验依据(如:战国早期服制:深衣、束发、无幞头)"}}
]}}

硬性规则:
1. 服饰/器物必须符合人物所处历史时期,不得出现后世朝代元素(如唐装/幞头出现在战国场景)。
2. character_id 必须逐一对应上面人物列表里给出的 character_id,不得遗漏、不得杜撰新角色。
"""


def _characters_with_dramatic_role(script: Script, chapter_ir: ChapterIR) -> list[CharacterIR]:
    """spec §5.1 步骤1:"从 script 统计出有戏份的角色(出现在 dialogue 或 visual_hint 中)"。"""
    speaker_ids = {ln.speaker for ln in script.lines if ln.type == "dialogue"}
    result = []
    for c in chapter_ir.characters:
        names = [c.canonical_name, *c.aliases]
        mentioned_in_visual_hint = any(
            ln.visual_hint and any(name in ln.visual_hint for name in names) for ln in script.lines
        )
        if c.character_id in speaker_ids or mentioned_in_visual_hint:
            result.append(c)
    return result


def _build_prompt(characters: list[CharacterIR], constitution: Constitution) -> str:
    character_lines = "\n".join(
        f"{c.character_id}: {c.canonical_name}"
        f"(role={c.role_in_chapter or '未知'}, faction={c.faction or '未知'}, fate={c.fate or '未知'})"
        for c in characters
    )
    return _CHARACTER_BIBLE_PROMPT_TEMPLATE.format(
        art_direction=constitution.visual_style.art_direction,
        palette=", ".join(constitution.visual_style.palette),
        character_lines=character_lines,
    )


def _coerce_character_bible(draft: dict[str, Any], characters: list[CharacterIR]) -> CharacterBible:
    by_id = {c.character_id: c for c in characters}
    drafted: dict[str, dict[str, str]] = {}
    for item in draft.get("characters") or []:
        cid = str(item.get("character_id") or "")
        if cid in by_id:
            drafted[cid] = {
                "appearance": str(item.get("appearance") or ""),
                "era_check": str(item.get("era_check") or ""),
            }

    entries = []
    for c in characters:
        info = drafted.get(c.character_id, {})
        entries.append(
            CharacterBibleEntry(
                character_id=c.character_id,
                name=c.canonical_name,
                appearance=info.get("appearance", ""),
                era_check=info.get("era_check", ""),
            )
        )
    return CharacterBible(characters=entries)


async def generate_character_bible(
    script: Script, chapter_ir: ChapterIR, constitution: Constitution, *, llm: Any = None
) -> CharacterBible:
    """script + chapter_ir + constitution → 角色外形描述(文本部分)。LLM 调用失败 →
    返回只有 character_id/name、外形字段为空的壳(降级,G5 会把这标成 error 而不是崩溃)。
    """
    if llm is None:
        from obase.provider_registry import ProviderRegistry

        llm = ProviderRegistry.get().llm("default")

    characters = _characters_with_dramatic_role(script, chapter_ir)
    if not characters:
        return CharacterBible(characters=[])

    prompt = _build_prompt(characters, constitution)
    try:
        draft = await _call_llm_json(llm, prompt)
    except Exception as e:
        logger.warning("character_bible 生成 LLM 调用失败,返回空壳: %s", e)
        draft = {}
    return _coerce_character_bible(draft, characters)


def gate_character_bible(bible: CharacterBible) -> GateResult:
    """G5 门(仅文本部分):外形描述非空 + 年代错误词扫描。真正的"VLM 审参考图"部分
    阻塞在 GPU 图像生成能力上,未实现——每个角色的 ref_image 缺失只计入 warnings。
    """
    errors: list[str] = []
    warnings: list[str] = []
    filled = 0

    for entry in bible.characters:
        if not entry.appearance:
            errors.append(f"角色 {entry.character_id} 缺少外形描述(LLM 遗漏)")
        else:
            filled += 1
        for term in _ANACHRONISM_BLACKLIST:
            if term in entry.appearance or term in entry.era_check:
                errors.append(f"角色 {entry.character_id} 外形描述命中疑似年代错误词 {term!r}")
        if entry.ref_image is None:
            warnings.append(
                f"角色 {entry.character_id} 尚无权威参考图"
                "(文生图+VLM年代审阻塞在本地 GPU 环境,见 SPEC-01 §5.1 步骤3-4)"
            )

    coverage = (filled / len(bible.characters)) if bible.characters else 1.0
    return GateResult(passed=not errors, coverage=coverage, errors=errors, warnings=warnings)
