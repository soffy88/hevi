"""SPEC-007 批2:多角色 reference_role 生成端——V2 层第一个真正发起生成请求的代码
(`generation_packet.py` 明确"不接入渲染调用",这条线上原本就空着这一环)。

标杆做法(上一轮已用真钱 $0.72 验证:happyhorse-1.1-r2v,无融合脸,落位跟 SceneStage 对
得上):官方 `[Image N]` 索引语法给每张参考图显式声明角色 + 落位,而不是像 hevi 历史用法
那样把多张图都当"同一角色的不同角度"隐式塞进去。

**明确不碰 V1**:`hevi/tongjian/scene_render_avatar.py:1390-1439`(INC-004 §4.2)的多角色
L4 分支已经是生产代码、有自己的真机验收记录,也调 `happyhorse_1_1_maas_reference_to_video`
但没有 `[Image N]` 声明——这次不去"升级"它,V1/V2 两条线分离是既定原则,不强行合并两条
已经分别验证过的路径。

**空景板不在这个模块生成**:`scene_plate_path` 是外部输入(跟 `canon_paths` 一样由调用方
提供),V1(`generate_scene_assets`)和 V2(`director_pipeline.py::_ensure_subject`)已经
各有一套空景板资产管线,这次不新建第三套,也不去统一前两套。

**style-lock 摸查①落地(2026-07-20,SPEC-007 缺口④)**:G-FINAL 真机撞见跨段画风漂移
(s1 工笔水墨→s7 近卡通,同 canon 同 prompt 骨架)。摸查排查出根因不是 provider 能力问题
(实测确认 happyhorse-1.1-r2v 没有原生 style_reference 参数,裸图风格锚也测不出收敛)——
是"文档优先"架构本身断在了这条生成路径上:`world_bible.visual.style_manifesto`(①里那
一大段水墨渗染/留白构图/暗部色调的详细风格宣言)一直只喂给 `generation_packet.py`(那
模块自己 docstring 写明"不接入渲染调用"),`compile_multirole_prompt` 这条真正发起生成
请求的路径**从头到尾没读过它**——不是"风格词被后面的场景描述稀释",是"从第一段起就
没有风格词,靠参考图碰运气"。这次接上:`world_bible` 存在且有 `style_manifesto` 时,
每段 prompt 里在叙事动作文本前统一插一句风格宣言,零额外 API 调用零额外成本(纯文本,
不新增参考图、不影响计价)。

**系统性断链排查后续(2026-07-20,soffy 定的三批修复,按危害排序)**——排查发现
style_manifesto 不是孤例,同一模式("字段存在、被某个中间 LLM 步骤或 lint 读过,但从没
到达真正花钱的这条生成路径")还有好几处。这次一并接上其中两处(零/低成本的):

1. **`characters[].identity_lock_sentence`**(①,零成本,跟 style_manifesto 同型):每个
   角色的"身份锁定句"(如"自初登场至终幕,许渔夫的身份、衣着、发型、体态与神情纹丝未变
   ……"),原来只喂给 Scene Script 生成的 LLM 当写作指导,从不出现在真实生成 prompt 里。
   现在按角色名匹配 `world_bible.characters`,直接拼进该角色的 `[Image N]` 声明行——跟
   style_manifesto 一样,纯文本、零额外调用。

2. **负面约束**(②,`world_bible.visual.negative_list` + 调用方传入的场级 `no_cut_to`):
   官方文档确认 happyhorse-1.1-r2v **没有 negative_prompt 参数**(跟 style_reference 一样
   查证过,不是猜的),负面约束只能塞进同一条 prompt。但图像/视频生成模型对否定句
   ("绝不出现X")的遵从度弱于正面描述(容易反而画出被否定的内容),直接拼否定句效果存疑
   ——所以先过 `positive_rephrase_negatives`(一次文本 LLM 调用,改写成正面陈述)再拼进
   prompt。**范围说明**:这次只接了 `visual.negative_list`(全局摄影/年代准确性负面清单)
   和调用方传入的 `no_cut_to`(场级禁切清单),**没有接 `world[].negative_list`**(逐地点
   的年代准确性负面清单)——`compile_multirole_prompt`/`generate_multirole_segment` 目前
   没有"当前场景对应哪个地点"这个信号,接了要么瞎猜要么加新参数,这次先不做,留作已知
   缺口记录,不是漏掉不提。

**§6 四个字段的逐条判定**:`no_cut_to`(场级禁切,2026-07-20 接入,走上面的负面约束路径)。
`camera_movement`/`offscreen_trigger`/`beat_description` 曾按"schema 注释写着标签不进
prompt"判为"设计如此、只供 lint",**2026-07-23 soffy 推翻这个判定**:运镜指令从没进过
生成端,正是"每段都由远及近推近"的病根——lint 查得干净(相邻段标签互异),但模型拿不到
"这段该怎么运镜"的指令,只能默认 push-in。这三个字段本质是给模型的**表演指令**,不是校验
标签。现在经 `_performance_directive` 编译成指令块,紧跟 action_text 拼进真实生成 prompt
(camera_movement→运镜方式指令、offscreen_trigger→画外事件指令、beat_description→表演
意图提示);narrative_text 仍是动作的权威描述,这三条是叠加其上的镜头语言,不是替代。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from hevi.director.pipeline_schemas import (
    InitialPosition,
    SceneScriptSegment,
    SceneStage,
    WorldBible,
)
from hevi.video.alibaba_maas_service import _to_data_uri_if_local

logger = logging.getLogger(__name__)

_DURATION_MIN_S = 3
_DURATION_MAX_S = 15

_NEGATIVE_REPHRASE_PROMPT = """把下面这些"画面里不该出现"的负面约束,改写成一段正面
陈述——描述画面应该呈现的样子,不要用"不"/"绝不"/"避免"/"禁止"这类否定词提到被禁止的
内容本身。这不是措辞偏好:图像/视频生成模型对否定句的遵从度弱于正面描述(容易反而画出
被否定的内容),这是在规避这个已知问题。合并写成一段连贯的中文描述,不要逐条罗列或编号。
只输出改写后的正面描述文本,不要解释、不要加引号。

负面约束清单:
{items}"""


async def positive_rephrase_negatives(negative_items: list[str], *, llm: Any = None) -> str:
    """负面约束(`world_bible.visual.negative_list`/`no_cut_to` 这类)→ 一段正面描述文本,
    供直接拼进生成 prompt——happyhorse-1.1-r2v 没有 negative_prompt 通道(官方文档已确认,
    不是猜的),负面约束只能塞进同一条 prompt 里跟其它指令抢注意力,这里改写成正面描述规避
    "模型对否定句遵从度弱"这个已知问题。

    `negative_items` 全空 → 空字符串,不调用 LLM。LLM 不可用/调用失败 → best-effort 退化:
    直接把原始负面短语拼接成一句提示塞回去(还是老的否定句措辞问题,但至少约束的内容没有
    整个消失)——不阻断真实付费视频生成,这条改写是增强层,不是硬门槛。"""
    items = [x for x in negative_items if x]
    if not items:
        return ""
    if llm is None:
        from hevi.director.design_list import _resolve_llm

        llm = _resolve_llm(None)
    try:
        prompt = _NEGATIVE_REPHRASE_PROMPT.format(items="\n".join(f"- {x}" for x in items))
        obj = llm(messages=[{"role": "user", "content": prompt}], max_tokens=400)
        resp = await obj if hasattr(obj, "__await__") else obj
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        text = str(content).strip()
        if text:
            return text
        raise ValueError("LLM 返回空文本")
    except Exception as e:
        logger.warning("负面约束正面化改写失败,退化为直接拼接原始负面短语: %s", e)
        return "务必避免以下内容:" + "；".join(items)


_SOFTEN_PROMPT = """下面这段视频生成提示词触发了内容审核(可能因血腥/危险/未成年受害等直白措辞)。
请把它改写得更含蓄委婉,**保留原本的情节含义、人物、动作走向和画面主体**,只把容易触发审核的
直白表述换成隐晦、诗意或侧写的说法(例如把直接的溺水/受伤/死亡描写,改成通过环境、水面、神情、
氛围来暗示)。不要删掉情节,不要改变谁在做什么,只改措辞的直白程度。只输出改写后的提示词本身,
不要解释、不要加引号。

原提示词:
{text}"""


async def _soften_for_moderation(text: str, *, llm: Any = None) -> str:
    """审核安全模式:把触发 green-net 的动作文本软化改写(去血腥/危险/未成年受害直白措辞,保留
    情节)。一次文本 LLM 调用;失败/空 → 原样返回(不阻断,降级重试是增强不是硬门槛)。"""
    if not text:
        return text
    if llm is None:
        from hevi.director.design_list import _resolve_llm

        llm = _resolve_llm(None)
    try:
        obj = llm(
            messages=[{"role": "user", "content": _SOFTEN_PROMPT.format(text=text)}], max_tokens=600
        )
        resp = await obj if hasattr(obj, "__await__") else obj
        content = resp.get("content") if hasattr(resp, "get") else str(resp)
        softened = str(content).strip()
        return softened or text
    except Exception as e:
        logger.warning("审核软化改写失败,用原文: %s", e)
        return text


def requires_multirole_reference(character_names: list[str]) -> bool:
    """§1 第8b 步的路由判据本体——2 个以上角色同框才走这条 reference_role 路径,单角色
    走既有的常规链式生成(那条至今仍停在 scratchpad,不在这次范围内)。"""
    return len(character_names) >= 2


def _blocking_by_char(scene_stage: SceneStage) -> dict[str, InitialPosition]:
    return {p.char_id: p for p in scene_stage.blocking.initial_positions}


def _identity_lock_sentence(world_bible: WorldBible | None, name: str) -> str:
    if world_bible is None:
        return ""
    entry = next((c for c in world_bible.characters if c.name == name), None)
    return entry.identity_lock_sentence if entry else ""


def compile_multirole_prompt(
    *,
    action_text: str,
    scene_stage: SceneStage,
    character_names: list[str],
    scene_plate_path: Path | None,
    continuity_reference_path: Path | None = None,
    world_bible: WorldBible | None = None,
    negative_constraints_text: str = "",
    performance_directive_text: str = "",
) -> str:
    """`[Image N]` 角色声明编译——每张参考图在 prompt 里被显式声明角色 + 落位,落位数据
    取自真实 `SceneStage.blocking.initial_positions`(按 `character_names` 顺序过滤),
    某角色没有 blocking 数据时姿态/朝向留空,不报错、不编造。

    `continuity_reference_path`:链式生成的段间条件传递——上一段真实末帧,不是角色 canon
    也不是空景板,独立声明("这一段的开头必须紧接这张图里的状态往下演"),顺序排在空景板
    之后、角色 canon 之前。

    `world_bible`(style-lock,见模块 docstring):**2026-07-23 画风锁双改**——①位置:从原来的
    prompt 中段(实测 34% 位置、被后续 action/运镜/双脸规则盖过)移到 prompt 最末,利用生成模型
    对尾部的 recency 权重;②形态:进 prompt 的是 `visual.style_render_directive`(30-50 字可执行
    渲染指令),不是 `style_manifesto`(357 字抽象散文,模型执行不了);directive 为空(老 world_bible)
    → 回退用 manifesto。补画风优先级/一致性声明治写实↔插画摆动。同时按角色名匹配
    `characters[].identity_lock_sentence` 拼进各自 `[Image N]` 行。`world_bible` 为 None 或
    两个风格字段都空 → 原样不插,零行为变化。

    `negative_constraints_text`(系统性断链排查②):调用方已经用
    `positive_rephrase_negatives` 改写好的正面描述文本,直接拼进 prompt——这个函数本身
    不做改写(改写要调 LLM,这个函数保持同步纯函数,改写放在 `generate_multirole_segment`
    里做)。空字符串 → 原样不插。

    `performance_directive_text`(2026-07-23,§6 运镜/表演指令接入生成端):调用方用
    `_performance_directive` 从 segment 的 camera_movement/offscreen_trigger/
    beat_description 编译好的指令块,紧跟在 action_text 之后拼进 prompt。空字符串 → 原样
    不插。"""
    blocking = _blocking_by_char(scene_stage)
    lines: list[str] = []
    idx = 1
    if scene_plate_path is not None:
        lines.append(
            f"[Image {idx}] 是这场戏的空景参考图(画面里没有人),只用来锁定场景环境/机位"
            "氛围,不要照搬这张图里的构图,画面里必须出现下面声明的人物。"
        )
        idx += 1
    if continuity_reference_path is not None:
        lines.append(
            f"[Image {idx}] 是上一段结尾的真实画面(保持空间/动作连续性用),这一段的开头"
            "必须紧接这张图里的人物位置、姿态、构图往下演,不要另起一个不相关的开场。"
            "画面里的人物身份仍以下面声明的各角色参考图为准,这张图只用来对空间/动作连续性。"
        )
        idx += 1
    for name in character_names:
        pos = blocking.get(name)
        posture = pos.posture if pos else ""
        facing = pos.facing if pos else ""
        detail = f"姿态:{posture},朝向:{facing}。" if (posture or facing) else ""
        lock_sentence = _identity_lock_sentence(world_bible, name)
        lines.append(
            f"[Image {idx}] 是{name}的身份参考图,只用来锁定{name}本人的长相和服装,"
            f"不要把{name}的容貌特征套到画面里的其他人物身上。画面中{name}的{detail}"
            + (lock_sentence if lock_sentence else "")
        )
        idx += 1
    if negative_constraints_text:
        lines.append(f"【画面必须呈现的效果(替代负面约束的正面描述)】{negative_constraints_text}")
    lines.append(action_text)
    if performance_directive_text:
        lines.append(performance_directive_text)
    if len(character_names) >= 2:
        lines.append(
            "两个人物必须是各自独立、可清楚区分的两张脸,不要融合成同一张脸,"
            "不要把两人的服装/发型混到一起。"
        )
    # 画风锁 text-layer 迭代(2026-07-23):①位置——从 prompt 中段(实测 34% 位置、被后续
    # 动作/运镜/双脸规则盖过)移到**最末**,利用生成模型对尾部的 recency 权重;②形态——进 prompt
    # 的是 `style_render_directive`(30-50 字可执行渲染指令),不是 `style_manifesto`(357 字抽象
    # 艺术散文,模型执行不了)。directive 为空(老 world_bible 没这字段)→ 回退用 manifesto,
    # 零行为倒退。再补画风优先级/一致性声明,治"写实↔插画摆动"。
    if world_bible is not None:
        style_lock = world_bible.visual.style_render_directive or world_bible.visual.style_manifesto
        if style_lock:
            lines.append(
                f"【整体美术风格·全片统一,这一帧必须严格遵守(优先级高于上面动作细节的清晰度)】"
                f"{style_lock}"
                f"——再强调一次:上面所有动作、运镜、人物都必须在这个画风下渲染,画风在全片每一段"
                f"之间保持完全一致,不要在写实照片感和插画/卡通感之间摇摆。"
            )
    return "\n".join(lines)


def build_reference_images(
    *,
    scene_plate_path: Path | None,
    canon_paths: dict[str, Path],
    character_names: list[str],
    continuity_reference_path: Path | None = None,
) -> list[str]:
    """按 `compile_multirole_prompt` 同样的编号规则组出 `reference_images` 列表——两个
    函数的图片顺序必须严格对应(空景板 → 连续性参考 → 角色按 `character_names` 顺序)。"""
    refs: list[str] = []
    if scene_plate_path is not None:
        refs.append(_to_data_uri_if_local(str(scene_plate_path)))
    if continuity_reference_path is not None:
        refs.append(_to_data_uri_if_local(str(continuity_reference_path)))
    for name in character_names:
        canon = canon_paths.get(name)
        if canon is not None:
            refs.append(_to_data_uri_if_local(str(canon)))
    return refs


def _action_text(segment: SceneScriptSegment) -> str:
    text = segment.narrative_text
    for d in segment.dialogue:
        target = f"对{d.target_name}" if d.target_name else ""
        text += f"。台词:{d.character_name}{target}说:'{d.text}'"
    return text


def _performance_directive(segment: SceneScriptSegment) -> str:
    """把 `SceneScriptSegment` 的表演/运镜指令字段(camera_movement/offscreen_trigger/
    beat_description)编译成给生成模型的显式指令块。这三个字段此前只供 lint 校验、从不进
    真实 prompt——2026-07-23 判为设计错误:运镜指令没进过生成端,正是"每段都由远及近推近"
    的病根(lint 查得干净,模型却拿不到"这段该怎么运镜"的指令)。现在编译进 prompt——
    narrative_text 仍是动作的权威描述,这里是叠加其上的镜头语言/画外事件/节拍意图。字段
    为空则不发对应行。"""
    lines: list[str] = []
    if segment.camera_movement:
        lines.append(
            f"【本段运镜】镜头运动方式:{segment.camera_movement}。"
            "严格按这个运镜方式拍这一段,不要默认使用由远及近的推近(push-in)。"
        )
        # 摇/摇向声源弱实现修正(2026-07-23,④):基线实测这类段几乎没摇(光流 0.65/1.57)——
        # 措辞太泛,模型当静态拍了。补一句明确的摇镜幅度/方向指令。
        if "摇" in segment.camera_movement:
            lines.append(
                "【运镜强化】这一段镜头必须有明显可见的摇镜运动:机位基本不动、镜头绕轴转向"
                "(向画外声源/触发方向水平摇过去),摇动幅度要肉眼可辨,不是几乎静止的微动——"
                "让观众清楚感到镜头在'转头看向'那个方向。"
            )
        # 强运动×身份互斥(2026-07-23 修正,soffy 定):上一版让大运动段"强制中景+脸清晰"是
        # 在跟 provider 物理边界对着干——A/B 实证 s9/s10/s11 大运动段照样掉身份(与守恒律同源:
        # 镜头动得猛,主角在帧里必然糊/变形,认不出)。改成**互斥**:大运动段不承担身份识别任务
        # ——不安排主角面部特写、不要求认脸,身份交给前后静态段建立。别再试图在运动里锁脸。
        if any(k in segment.camera_movement for k in ("横移", "跟随", "摇")):
            lines.append(
                "【本段构图(强运动段免认脸)】这是横移/跟随/摇类大运动镜头,不要给主角安排面部特写、"
                "不追求这一段里认出人脸——主角可以背身/侧身/中远景带过,重点放在运动本身和环境/动作上;"
                "人物身份的清晰识别由这一段前后的静态段负责,不要为了锁脸牺牲运镜。"
            )
    if segment.offscreen_trigger:
        lines.append(
            f"【画外事件】本段有来自画面之外的触发:{segment.offscreen_trigger}。"
            "在画面里表现出人物对这个画外事件的反应。"
        )
    if segment.beat_description:
        lines.append(f"【本段表演意图/戏剧节拍】{segment.beat_description}")
    return "\n".join(lines)


async def generate_multirole_segment(
    *,
    scene_stage: SceneStage,
    segment: SceneScriptSegment,
    character_names: list[str],
    canon_paths: dict[str, Path],
    scene_plate_path: Path | None,
    output_path: Path,
    continuity_reference_path: Path | None = None,
    world_bible: WorldBible | None = None,
    no_cut_to: list[str] | None = None,
    location_negative_list: list[str] | None = None,
    resolution: str = "720P",
    ratio: str = "9:16",
    seed: int | None = None,
    gen_fn: Any = None,
    rephrase_llm: Any = None,
    moderation_safe: bool = False,
) -> Path:
    """生产入口:从 `segment` 拼动作文本,从 `scene_stage` 取落位,编译 prompt + 组参考图,
    调用生成。`gen_fn` 默认 `happyhorse_1_1_maas_reference_to_video`,显式参数注入供测试
    替身(跟 `segment_qc.py::segment_qc` 的 `tts_fn` 同一个约定,不用 `unittest.mock.patch`
    打模块补丁)。`continuity_reference_path`:链式生成时上一段的真实末帧,第一段传 None。
    `world_bible`:style-lock 摸查①落地 + 系统性断链排查①②,见模块 docstring和
    `compile_multirole_prompt`。`no_cut_to`:调用方传入该场景的 `SceneScript.no_cut_to`
    (场级,同一场所有段共用),没有就不传,不强制要求。`rephrase_llm`:`positive_rephrase_
    negatives` 的显式依赖注入,None 用其默认解析(同 `tts_fn`/`gen_fn` 约定)。
    `location_negative_list`(2026-07-23,补断链):这段所在地点的 `world[].negative_list`
    (逐地点年代准确性负面清单)——此前是已知缺口(`compile_multirole_prompt` 没有"当前场景对应
    哪个地点"信号)。现在由调用方(produce_v2 有 scene_ref→location→world 条目映射)解析后传入,
    并入负面约束一起正面化改写。None/空 → 不影响。
    `moderation_safe`(2026-07-23,内容审核自动预案):green-net(`DataInspectionFailed`)拦截后的
    降级重试模式——**丢掉全部负面约束**(负面清单把 prompt 撑长、且逐条列"现代物/危险物"本身就
    容易触发审核误判)+ **把动作文本软化改写**(去血腥/危险/未成年受害的直白措辞,保留情节含义)。
    调用方 produce_v2 在这类失败时置 True 重试一次。"""
    if gen_fn is None:
        from hevi.video.alibaba_maas_service import happyhorse_1_1_maas_reference_to_video

        gen_fn = happyhorse_1_1_maas_reference_to_video

    if moderation_safe:
        negative_items: list[str] = []  # 降负面强度:审核安全模式丢掉全部负面
    else:
        negative_items = list(world_bible.visual.negative_list) if world_bible is not None else []
        negative_items += no_cut_to or []
        negative_items += location_negative_list or []
    negative_constraints_text = (
        await positive_rephrase_negatives(negative_items, llm=rephrase_llm)
        if negative_items
        else ""
    )

    action_text = _action_text(segment)
    if moderation_safe:
        action_text = await _soften_for_moderation(action_text, llm=rephrase_llm)
    prompt = compile_multirole_prompt(
        action_text=action_text,
        scene_stage=scene_stage,
        character_names=character_names,
        scene_plate_path=scene_plate_path,
        continuity_reference_path=continuity_reference_path,
        world_bible=world_bible,
        negative_constraints_text=negative_constraints_text,
        performance_directive_text=_performance_directive(segment),
    )
    reference_images = build_reference_images(
        scene_plate_path=scene_plate_path,
        canon_paths=canon_paths,
        character_names=character_names,
        continuity_reference_path=continuity_reference_path,
    )
    duration = min(
        max(round(segment.t_end_s - segment.t_start_s), _DURATION_MIN_S), _DURATION_MAX_S
    )

    return await gen_fn(
        prompt=prompt,
        reference_images=reference_images,
        output_path=output_path,
        duration=duration,
        resolution=resolution,
        ratio=ratio,
        seed=seed,
    )
