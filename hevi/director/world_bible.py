"""SPEC-006 ①World Bible 生成器 —— 一部作品一份,创作一次全局锁定。

V2 核心反转:创作文档优先,structure(SceneStageSet/ShotList)是文档的校验影子。这里产出
四卷高密度自然语言(角色卷/世界卷/影像卷/声音卷),密度对标"服装逐件、密度到具体物件"这类
参考 prompt 水准——**不是从已锁定的 DesignList 短字段(appearance/wardrobe 等)反向膨胀**,
那样膨胀出来的是复述不是密度(V1 抽取有损的教训在这一层重演一次)。而是回头去读原始素材
原文(material_text),对每个已锁定的角色名/场景名重新找相关描写提炼成一段连续长文本。
DesignList 只用于名字锚定(保证 CharacterVolumeEntry.name 对得上 subject_id/canon 图),
不是内容来源。

四组并发调用(每角色一次、每场景一次、visual/sound 各一次),不是一次大 prompt 出四卷——
仿照 shot_list.py"每场一次调用防止密度稀释"的既有惯例,避免长段落在一次输出里被压缩变薄。

这是 G-V2 垂直切片(spec §5)①,纯文本 LLM 调用,不接入现有 API/lock 状态机。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from hevi.director.design_list import _resolve_llm
from hevi.director.pipeline_schemas import (
    _CAMERA_PERSONA_IDS,
    CameraPersona,
    CharacterVolumeEntry,
    Concept,
    DesignList,
    SoundVolume,
    VisualVolume,
    WorldBible,
    WorldVolumeEntry,
)

logger = logging.getLogger(__name__)


async def _call_llm_json(
    llm: Any, prompt: str, *, max_tokens: int, timeout_s: float
) -> dict[str, Any]:
    """自建(不复用 design_list.py 写死 max_tokens=4096 的版本)——World Bible 每次只出一个
    实体的一段文本,预算需要按条目类型调小/调大,复制一份并调参符合 screenplay.py 已示范的惯例。"""

    def _invoke() -> Any:
        return llm(messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens)

    obj = await asyncio.wait_for(asyncio.to_thread(_invoke), timeout=timeout_s)
    resp = await obj if hasattr(obj, "__await__") else obj
    content = resp.get("content") if hasattr(resp, "get") else str(resp)
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


_CHARACTER_ENTRY_PROMPT = """你是电影美术指导,在为角色写"定妆手册"条目。下面是一部作品的原始
素材全文和基调,请只针对角色"{name}"这一个人,回到原始素材里找到所有跟这个角色相关的描写
(外貌/衣着/年龄/体型/气质/性格/习惯动作),重新提炼成一段**高密度连续长文本**——不是三五个
短语的罗列,是像给演员的角色小传那样写:服装要逐件写清楚(材质/颜色/新旧/穿法),发型细节,
肤质/年龄痕迹,性格气质怎么体现在外在举止上。原始素材没写到的细节,可以按基调合理补全,但
不要跟原始素材矛盾。

最后单独给一句"身份锁定句"——强制声明"整个作品中这个角色的身份、服装、发型、外貌保持一致"
这个意思的一句话(可以按角色语境改写措辞,但这个意思必须在)。

**assumed_details(必须如实填写,不能因为想显得"素材扎实"就漏报)**:逐条列出你刚才写的
profile_text 里,哪些具体细节是原始素材**没有明确写到**、由你推测/合理补全的(比如"疤痕在
左颊"这种具体细节,如果原始素材只说"有疤"没说位置,就要报"疤痕位置(左颊)是推测的")。
原始素材明确写到的内容不用报。没有推测内容就给空列表,但要如实——宁可多报,不要漏报。

只输出 JSON:{{"profile_text": "一段连续长文本", "identity_lock_sentence": "一句话",
"assumed_details": ["推测/补全的具体细节", "..."]}}

作品基调:{tone}{style}
原始素材:
{material_text}"""

_WORLD_ENTRY_PROMPT = """你是电影美术指导,在为场景写"环境设定"条目。下面是一部作品的原始
素材全文和基调,请只针对场景"{name}"这一个地方,回到原始素材里找到所有跟这个场景相关的描写,
重新提炼成一段**高密度连续长文本**——密度要落到具体物件(不是"街道",是"盆栽植物、晾衣绳、
自行车、电线杆、架空电线、树影移动"这种程度),写清楚空间格局、光线、材质、气味/声音暗示、
时间痕迹。原始素材没写到的细节可以按基调合理补全,但不要跟原始素材矛盾。

再给一份负面清单——逐条列出"这个场景绝不该出现"的东西(跟基调/时代/氛围冲突的元素)。

**assumed_details(必须如实填写)**:逐条列出 profile_text 里哪些具体物件/细节是原始素材
没有明确写到、由你推测补全的。没有就给空列表,但要如实——宁可多报,不要漏报。

只输出 JSON:{{"profile_text": "一段连续长文本", "negative_list": ["不要出现的东西", "..."],
"assumed_details": ["推测/补全的具体细节", "..."]}}

作品基调:{tone}{style}
原始素材:
{material_text}"""

# 影像美学预设(2026-07-22 写实度探针坐实:style_manifesto 是水墨感/写实感的主控杠杆,
# happyhorse-1.1-r2v 在写实 brief 下同一张 canon 同 seed 就能出真人实拍质感,不必换 provider。
# 短剧产品默认走 realistic;国风水墨等风格化走 inkwash)。这段指令强制 style_manifesto 的
# 美学方向,压过 concept.style 里可能的模糊表述。
_STYLE_DIRECTIVE = {
    "realistic": (
        "【本片美学硬约束——真人实拍写实】style_manifesto 必须描述照片级真人实拍电影帧:"
        "真实演员相貌、自然主义布光、真实皮肤/毛孔/织物/材质纹理、浅景深与背景虚化、"
        "细腻胶片颗粒、可信的光影层次。**绝不能**写成水墨/绘画/插画/工笔/动画/CG 渲染风格,"
        "不要宣纸渗染、墨色晕化、留白式构图这类绘画语汇。negative_list 里应包含"
        "「绘画感/水墨/插画/动画质感」这类要规避的项。"
    ),
    "inkwash": (
        "【本片美学硬约束——国风水墨】style_manifesto 必须描述中国古典水墨的影像质感:"
        "宣纸渗染、墨色晕化、留白构图、青灰冷调、水汽氤氲的柔焦边界,非写实再现而是"
        "以绘画语汇统领全片。negative_list 里应包含「现代写实调色/摄影棚硬光」这类要规避的项。"
    ),
}

_VISUAL_VOLUME_PROMPT = """你是电影摄影指导,在为一部作品定"整体影像风格"(全片一份,后续
每一场戏都要遵循)。

{style_directive}

请给出:

1. 视觉风格宣言(style_manifesto):一段连续长文本,讲清楚这部作品的整体影像质感、色调倾向、
   构图哲学(**必须服从上面的美学硬约束**)。
2. 摄像机人格(camera_persona):从下面四选一,并写清楚为什么选它(persona_rationale)、
   这个人格具体怎么运镜的行为派生规则(behavior_derivation_text,后续每一场戏的摄像机行为
   都要从这段规则派生,不是每场自己现编)——
   - dv_friend:朋友的DV,强手持、对焦搜索、构图不完美、反应慢半拍
   - invisible_cine:隐形电影机,稳、预判、构图精确(传统电影感)
   - doc_crew:纪录组,跟拍、变焦、偶尔被发现
   - static_watch:固定机位,监控感/舞台感
3. 摄影缺陷美学清单(photographic_flaw_aesthetics):逐条列出这部作品刻意保留的"不完美"
   (如"轻微颗粒感""自然曝光漂移""偶尔跑焦"),这些不是缺陷是风格。
4. 负面清单(negative_list):逐条列出绝不该出现的影像特征(如"没有稳定""没有电影化运镜"
   "没有现代调色")。

**assumed_details(必须如实填写)**:逐条列出上面内容里哪些具体细节是原始素材没有依据、
由你推测/发挥的。没有就给空列表,但要如实。

只输出 JSON:{{"style_manifesto": "...", "camera_persona": {{"persona_id": "dv_friend|
invisible_cine|doc_crew|static_watch", "persona_rationale": "...",
"behavior_derivation_text": "..."}}, "photographic_flaw_aesthetics": ["...", "..."],
"negative_list": ["...", "..."], "assumed_details": ["推测/补全的具体细节", "..."]}}

作品基调:{tone}{style}
原始素材:
{material_text}"""

_SOUND_VOLUME_PROMPT = """你是声音指导,在为一部作品定"整体声音基调"(全片一份)。请给出:

1. 环境音谱系(ambient_soundscape_text):一段连续长文本,按情绪/场景类型分层描述这部作品
   典型的环境声(如"晨间鸟鸣、远处摩托、晾衣绳织物声、脚步踩混凝土"这种具体程度),不是
   泛泛而谈"有环境音"。
2. 音乐立场(music_stance_text):一段文本,讲清楚有没有配乐、什么时候用、情绪功能是什么
   (也可以是"全片无配乐"这种明确立场)。
3. 负面清单(negative_list):逐条列出绝不该出现的声音元素(如"没有音乐""没有音效设计"
   "没有旁白")。

**重要(容易出错的地方)**:你手上只有素材全文,没有逐场剧本的完整台词/事件细节。举例佐证
你的声音设计时,**不能编造原始素材里不存在的具体台词或具体事件**当例子(比如编一句角色说
"你可知……"这种听起来像真台词但素材里根本没有的话)——这是编造事实,不是风格推测,两者
性质不同。可以泛泛描述"某句关键台词收尾时骤然静默"这种功能性描述,不能虚构台词原文。

**assumed_details(必须如实填写)**:逐条列出上面内容里哪些具体细节(尤其是任何听起来像
引用了具体台词/具体场景事件的部分)是原始素材没有依据、由你推测/发挥的。没有就给空列表,
但要如实——这一项对声音卷格外重要,宁可多报。

只输出 JSON:{{"ambient_soundscape_text": "...", "music_stance_text": "...",
"negative_list": ["...", "..."], "assumed_details": ["推测/补全的具体细节", "..."]}}

作品基调:{tone}{style}
原始素材:
{material_text}"""


def _tone_style_text(concept: Concept) -> str:
    parts = [p for p in (concept.tone, concept.style) if p]
    return f"({'，'.join(parts)})" if parts else ""


async def _character_entry_draft(
    *, name: str, material_text: str, concept: Concept, llm: Any
) -> CharacterVolumeEntry:
    prompt = _CHARACTER_ENTRY_PROMPT.format(
        name=name, tone=concept.tone, style=_tone_style_text(concept), material_text=material_text
    )
    try:
        data = await _call_llm_json(llm, prompt, max_tokens=2048, timeout_s=45.0)
    except Exception as e:
        logger.warning("world bible character entry LLM failed(%s): %s", name, e)
        data = {}
    return CharacterVolumeEntry(
        name=name,
        profile_text=str(data.get("profile_text") or "").strip(),
        identity_lock_sentence=str(data.get("identity_lock_sentence") or "").strip(),
        source_design_ref=name,
        assumed_details=[
            str(x).strip() for x in (data.get("assumed_details") or []) if str(x).strip()
        ],
    )


async def _world_entry_draft(
    *, name: str, material_text: str, concept: Concept, llm: Any
) -> WorldVolumeEntry:
    prompt = _WORLD_ENTRY_PROMPT.format(
        name=name, tone=concept.tone, style=_tone_style_text(concept), material_text=material_text
    )
    try:
        data = await _call_llm_json(llm, prompt, max_tokens=2048, timeout_s=45.0)
    except Exception as e:
        logger.warning("world bible world entry LLM failed(%s): %s", name, e)
        data = {}
    return WorldVolumeEntry(
        name=name,
        profile_text=str(data.get("profile_text") or "").strip(),
        negative_list=[str(x).strip() for x in (data.get("negative_list") or []) if str(x).strip()],
        source_design_ref=name,
        assumed_details=[
            str(x).strip() for x in (data.get("assumed_details") or []) if str(x).strip()
        ],
    )


async def _visual_volume_draft(
    *, material_text: str, concept: Concept, llm: Any, visual_style: str = "realistic"
) -> VisualVolume:
    prompt = _VISUAL_VOLUME_PROMPT.format(
        style_directive=_STYLE_DIRECTIVE.get(visual_style, _STYLE_DIRECTIVE["realistic"]),
        tone=concept.tone,
        style=_tone_style_text(concept),
        material_text=material_text,
    )
    try:
        data = await _call_llm_json(llm, prompt, max_tokens=3072, timeout_s=60.0)
    except Exception as e:
        logger.warning("world bible visual volume LLM failed: %s", e)
        data = {}
    cp_raw = data.get("camera_persona") if isinstance(data.get("camera_persona"), dict) else {}
    persona_id = str(cp_raw.get("persona_id") or "").strip()
    if persona_id not in _CAMERA_PERSONA_IDS:
        persona_id = "invisible_cine"  # 未识别值兜底成中性默认,不硬塞可能误导下游的类型
    camera_persona = CameraPersona(
        persona_id=persona_id,
        persona_rationale=str(cp_raw.get("persona_rationale") or "").strip(),
        behavior_derivation_text=str(cp_raw.get("behavior_derivation_text") or "").strip(),
    )
    return VisualVolume(
        style_manifesto=str(data.get("style_manifesto") or "").strip(),
        camera_persona=camera_persona,
        photographic_flaw_aesthetics=[
            str(x).strip()
            for x in (data.get("photographic_flaw_aesthetics") or [])
            if str(x).strip()
        ],
        negative_list=[str(x).strip() for x in (data.get("negative_list") or []) if str(x).strip()],
        assumed_details=[
            str(x).strip() for x in (data.get("assumed_details") or []) if str(x).strip()
        ],
    )


async def _sound_volume_draft(*, material_text: str, concept: Concept, llm: Any) -> SoundVolume:
    prompt = _SOUND_VOLUME_PROMPT.format(
        tone=concept.tone, style=_tone_style_text(concept), material_text=material_text
    )
    try:
        data = await _call_llm_json(llm, prompt, max_tokens=3072, timeout_s=60.0)
    except Exception as e:
        logger.warning("world bible sound volume LLM failed: %s", e)
        data = {}
    return SoundVolume(
        ambient_soundscape_text=str(data.get("ambient_soundscape_text") or "").strip(),
        music_stance_text=str(data.get("music_stance_text") or "").strip(),
        negative_list=[str(x).strip() for x in (data.get("negative_list") or []) if str(x).strip()],
        assumed_details=[
            str(x).strip() for x in (data.get("assumed_details") or []) if str(x).strip()
        ],
    )


async def generate_world_bible_draft(
    *,
    concept: Concept,
    material_text: str,
    design_list: DesignList,
    llm: Any = None,
    visual_style: str = "realistic",
) -> WorldBible:
    """锁定 Concept + 原始素材 + DesignList(仅名字锚定)→ World Bible 草稿。四卷并发生成。

    `visual_style`:影像美学预设(`realistic` 真人实拍写实 / `inkwash` 国风水墨),控制
    style_manifesto 的美学方向(见 `_STYLE_DIRECTIVE`)。默认 `realistic`——短剧产品目标是
    真人写实,2026-07-22 写实度探针坐实这是纯文本杠杆,同 canon 同 provider 就能翻转画风。
    """
    resolved_llm = _resolve_llm(llm)
    char_names = [c.name for c in design_list.characters if c.name]
    scene_names = [s.name for s in design_list.scenes if s.name]

    character_results, world_results, visual, sound = await asyncio.gather(
        asyncio.gather(
            *[
                _character_entry_draft(
                    name=n, material_text=material_text, concept=concept, llm=resolved_llm
                )
                for n in char_names
            ]
        ),
        asyncio.gather(
            *[
                _world_entry_draft(
                    name=n, material_text=material_text, concept=concept, llm=resolved_llm
                )
                for n in scene_names
            ]
        ),
        _visual_volume_draft(
            material_text=material_text,
            concept=concept,
            llm=resolved_llm,
            visual_style=visual_style,
        ),
        _sound_volume_draft(material_text=material_text, concept=concept, llm=resolved_llm),
    )

    return WorldBible(
        characters=list(character_results), world=list(world_results), visual=visual, sound=sound
    )
