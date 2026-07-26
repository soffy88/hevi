"""通鉴 V2 一集编排入口(SPEC-005-V2 固化,2026-07-24)。

**一个入口跑完通鉴一集**:文言原文 → 成片。不靠脚本手动串(镜像 V2 转正的 `run_v2_produce`)。

流程(SPEC-005 架构:讲解主干 + 演绎插段):
  L0-L5 前端(chapter_ir→event_units→constitution→script→timeline→shotlist→character_bible,
           全程显式 qwen_cloud——tongjian 默认 llm("default")=本地 ollama 返回全空,见 memory)
  → 桥接(`tongjian_v2_bridge`:drama 过滤 + 生成**共用 world_bible**)
  → 按 shotlist 叙事序分组(contiguous drama 插段 / narration 讲解镜)
     - drama 插段 → produce_v2 写实(每个 contiguous 插段一次 run,组内连续、跨插段不串连续性)
     - narration 讲解镜 → `v2_jiangjie` qwen-image 写实静帧
  → `v2_assembly` 跨栈装配(音频归一 + 可 seek 拼接,叙事序)

★★ 跨栈接缝能接上的根本(写进代码,见 `v2_jiangjie` docstring):**讲解段与演绎段共用同一份
`world_bible`**(考据 negatives + historical directive)。canon/空景板/讲解静帧的负面与画风锚都从这
同一份 world_bible 读——两栈同源同调,才没有"讲解插画 vs 演绎照片"的硬切落差。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from hevi.director.tongjian_v2_bridge import (
    _is_drama_shot,
    build_v2_inputs_from_tongjian,
    build_v2_scene_script_set,
    character_id_to_name,
)
from hevi.tongjian.v2_assembly import assemble_episode
from hevi.tongjian.v2_jiangjie import render_jiangjie_clip

# 演绎段定妆照取景框(时代/画风靠 world_bible,这里只定"写实定妆照"通用框)
_CANON_FRAMING = (
    "写实历史正剧定妆照,真人演员,平静中性表情,正面半身像,"
    "画面中只有一个人物、绝不出现第二个人,"
    "自然柔光,纯色中性摄影棚背景,写实肤色正常五官比例"
)

# 演绎镜 loaded 估价(立木实测 $1.21/镜;廷辩双人口型更难,取 1.3 作熔断预估)
_EST_USD_PER_DRAMA_SHOT = 1.3


class BudgetPauseError(RuntimeError):
    """成本熔断(LSXC-EP0-CHARTER §4):累计花费 + 下一演绎插段预估将超帽 → **在烧这段之前**暂停。
    不自动烧下一段、不自动静默停;报已花 + 列剩余镜,交人工决定(抬帽续跑 / 收工)。"""

    def __init__(
        self, *, spent: float, cap: float, remaining_shots: list[str], done_clips: list[str]
    ):
        self.spent = spent
        self.cap = cap
        self.remaining_shots = remaining_shots
        self.done_clips = done_clips  # 已出的分段(人工决定续跑时可续,不白烧)
        super().__init__(
            f"成本熔断:已花 ${spent:.2f} / 帽 ${cap:.2f};还剩 {len(remaining_shots)} 镜未烧,等人工"
        )


def group_shots_by_kind(shotlist: Any, script: Any) -> list[tuple[str, list[Any]]]:
    """按 shotlist 叙事序分组:**同一 scene_id 的**连续 drama 镜合成一个 ('drama', [shots]) 插段;
    每个 narration 镜单独 ('narration', [shot])。过场镜(is_transition)丢弃。纯函数,可测。

    ★ 在 scene_id 边界断开 drama 插段(不跨场并):不同场是不同设定/时空,不该共享 produce_v2 的连续性
    链、location、空景板——一个插段=单一场,per-scene 的 location/plate/校色基准才对齐(2026-07-24:立木
    E004 室外市集 → E005 室内垦草令 若并成一段,E005 会套 E004 的室外板)。

    drama/narration 判定复用桥接器的 `_is_drama_shot`(单一真源,避免和 produce_v2 过滤分叉)。"""
    lines_by_id = {ln.line_id: ln for ln in script.lines}
    groups: list[tuple[str, list[Any]]] = []
    for shot in shotlist.shots:
        if shot.is_transition:
            continue
        kind = "drama" if _is_drama_shot(shot, lines_by_id) else "narration"
        same_scene = groups and groups[-1][1][-1].scene_id == shot.scene_id
        if kind == "drama" and groups and groups[-1][0] == "drama" and same_scene:
            groups[-1][1].append(shot)
        else:
            groups.append((kind, [shot]))
    return groups


# 对比性描述词——canon 定妆照里出现这些会诱导 qwen-image 把"对比对象"也画进画面(2026-07-25
# 正反打试跑实证:李斯 appearance 写"与王绾明显区分"→ canon 渲成两个人,身份基准坏)。canon 是
# 单人定妆照,只留本人特征,凡含对比词的分句一律剔除。
_COMPARATIVE_MARKERS = ("区分", "区别", "不同于", "有别于", "对比", "相比", "相较", "不像", "而非")


def _strip_comparative(appearance: str) -> str:
    """剔除 appearance 里的对比性分句(按中英逗号/、/;切分,丢掉含对比词的分句)。"""
    import re

    parts = re.split(r"[,,、;;]", appearance)
    kept = [p for p in parts if p.strip() and not any(m in p for m in _COMPARATIVE_MARKERS)]
    return ",".join(s.strip() for s in kept)


async def _ensure_canon(
    *,
    names: set[str],
    appearance: dict[str, str],
    world_bible: Any,
    out_dir: Path,
    image_gen_fn: Any,
) -> dict[str, str]:
    """演绎段角色定妆照(qwen-image,负面用**共用 world_bible** 的考据 negatives)。name→path。
    seed 由角色名 sha256 派生(同名同脸,跨进程稳定)。appearance 里的对比性描述("与X区分")会剔除,
    否则 qwen-image 把对比对象也画进 canon(单人定妆照渲成两人,身份基准坏)。"""
    neg = ",".join(getattr(world_bible.visual, "negative_list", []) or []) if world_bible else ""
    out_dir.mkdir(parents=True, exist_ok=True)
    refs: dict[str, str] = {}
    for nm in sorted(names):
        p = out_dir / f"canon_{nm}.png"
        seed = int(hashlib.sha256(nm.encode()).hexdigest(), 16) % (2**31)
        appr = _strip_comparative(appearance.get(nm, ""))[:200]
        await image_gen_fn(
            prompt=f"{_CANON_FRAMING},{nm},{appr}",
            output_path=p,
            seed=seed,
            negative_prompt=neg,
        )
        refs[nm] = str(p)
    return refs


async def _render_drama_insert(
    *,
    shots: list[Any],
    script: Any,
    id_to_name: dict[str, str],
    design_list: Any,
    world_bible: Any,
    subject_ref_paths: dict[str, str],
    scene_plate: str,
    location: str,
    voices: dict[str, str],
    run_dir: Path,
    llm: Any,
    gen_fn: Any,
    ratio: str = "16:9",
) -> tuple[Path, dict]:
    """一个 contiguous drama 插段 → produce_v2 写实块(组内连续)。返回(块成片, config_json)。"""
    from hevi.director.pipeline_schemas import Screenplay, ScreenplayScene
    from hevi.director.produce_v2 import run_v2_produce
    from hevi.tongjian.schemas import ShotList

    sss = build_v2_scene_script_set(
        script=script, shot_list=ShotList(shots=shots), id_to_name=id_to_name, drama_only=True
    )
    screenplay = Screenplay(
        scenes=[
            ScreenplayScene(
                scene_no=sc.scene_ref, location=location, characters_present=sc.characters_present
            )
            for sc in sss.scripts
        ]
    )

    class _Repo:
        def __init__(self):
            self.state: dict = {"shots": []}

        async def update_task(self, t, d):
            self.state.update(d)
            return True

        async def delete_shots(self, t):
            self.state["shots"] = []

        async def create_shot_state(self, d):
            self.state["shots"].append(d)

    repo = _Repo()
    run_dir.mkdir(parents=True, exist_ok=True)
    await run_v2_produce(
        task_repo=repo,
        task_id=run_dir.name,
        screenplay=screenplay,
        design_list=design_list,
        world_bible=world_bible,
        scene_script_set=sss,
        subject_ref_paths=subject_ref_paths,
        scene_ref_paths={location: scene_plate},
        voice_by_speaker=voices,
        run_dir=run_dir,
        progress_cb=None,
        gen_fn=gen_fn,
        llm=llm,
        ratio=ratio,
    )
    return Path(repo.state["result_video_path"]), repo.state.get("config_json", {})


def _narration_text(shot: Any, lines_by_id: dict[str, Any]) -> str:
    return " ".join(lines_by_id[lid].text for lid in shot.line_ids if lid in lines_by_id)


def _clip_tier(shots: list[Any], kind: str, lines_by_id: dict[str, Any]) -> tuple[str, str]:
    """一个 clip 的三档置信标注(频道诚信内核,§3.1)。优先用 shot 显式 `provenance_tier`;否则默认规则:
    演绎段(表演/面容艺术加工)→演绎;讲解段(场景/背景复原推断)→推演。有 quote_id(真实引语)的
    对白升为实录。cite 用 shot.source_cite。判定规则可后续细化,这里先给自动默认(替代剪辑期人工)。"""
    for sh in shots:
        tier = getattr(sh, "provenance_tier", "") or ""
        if tier:
            return tier, getattr(sh, "source_cite", "") or ""
    # 默认:drama 有真实引语对白 → 实录;否则演绎;narration → 推演
    if kind == "drama":
        has_quote = any(
            (ln := lines_by_id.get(lid)) is not None and getattr(ln, "quote_id", None)
            for sh in shots
            for lid in sh.line_ids
        )
        return ("实录", "") if has_quote else ("演绎", "")
    return "推演", ""


async def produce_tongjian_v2_episode(
    *,
    source_name: str,
    raw_text: str,
    output_path: Path,
    location: str,
    concept: Any = None,
    llm: Any = None,
    gen_fn: Any = None,
    image_gen_fn: Any = None,
    tts_fn: Any = None,
    voice_by_speaker: dict[str, str] | None = None,
    budget_usd: float | None = None,
    landscape: bool = True,
    intro_theme: str = "",
) -> dict[str, Any]:
    """通鉴一集全程入口。返回 {final_video, actual_usd, n_drama, n_narration, l5_by_insert, ...}。

    昂贵子调用(front-end LLM / produce_v2 gen_fn / qwen-image / edge_tts)均可注入替身供测试;
    None 时用各自默认真实实现。`llm` 必须能解析到 qwen_cloud(见模块 docstring)。"""
    from hevi.director.pipeline_schemas import Concept
    from hevi.tongjian.chapter_ir import extract_chapter_ir
    from hevi.tongjian.character_bible import generate_character_bible
    from hevi.tongjian.constitution import build_constitution
    from hevi.tongjian.script import build_script
    from hevi.tongjian.shotlist import build_shotlist
    from hevi.tongjian.voiceover import build_voiceover

    # tts_fn 前端 build_voiceover(G3 门)要用;canon/plate/讲解的 image_gen_fn 留给 back-half 兜底。
    if tts_fn is None:
        from hevi.audio.edge_tts_custom import edge_tts_synthesize_smart

        tts_fn = edge_tts_synthesize_smart
    concept = concept or Concept(theme=source_name, tone="庄重厚重", style="历史正剧")
    run_dir = output_path.parent
    run_dir.mkdir(parents=True, exist_ok=True)

    # ── L0-L5 前端 ──
    chapter_ir = await extract_chapter_ir(source_name=source_name, raw_text=raw_text, llm=llm)
    constitution, _g1 = await build_constitution(chapter_ir, llm=llm)
    script, _g2 = await build_script(
        constitution, chapter_ir, llm=llm, dramatize=True, raw_text=raw_text
    )
    bible = await generate_character_bible(script, chapter_ir, constitution, llm=llm)
    id_to_name = character_id_to_name(bible)
    voices = voice_by_speaker or {c.name: "zh-CN-YunjianNeural" for c in bible.characters}
    timeline, _g3 = await build_voiceover(
        script,
        constitution,
        output_dir=run_dir / "audio",
        tts_fn=tts_fn,
        voice_by_speaker={
            cid: voices.get(id_to_name.get(cid, cid), "zh-CN-YunxiNeural") for cid in id_to_name
        },
    )
    shotlist, _g4 = await build_shotlist(timeline, script, bible, llm=llm)

    return await render_tongjian_v2_backhalf(
        script=script,
        shotlist=shotlist,
        character_bible=bible,
        raw_text=raw_text,
        output_path=output_path,
        location=location,
        concept=concept,
        llm=llm,
        gen_fn=gen_fn,
        image_gen_fn=image_gen_fn,
        tts_fn=tts_fn,
        voice_by_speaker=voices,
        budget_usd=budget_usd,
        landscape=landscape,
        intro_theme=intro_theme,
    )


async def render_tongjian_v2_backhalf(
    *,
    script: Any,
    shotlist: Any,
    character_bible: Any,
    raw_text: str,
    output_path: Path,
    location: str | dict[str, str],
    concept: Any = None,
    llm: Any = None,
    gen_fn: Any = None,
    image_gen_fn: Any = None,
    tts_fn: Any = None,
    voice_by_speaker: dict[str, str] | None = None,
    design_list: Any = None,
    world_bible: Any = None,
    budget_usd: float | None = None,
    landscape: bool = True,
    intro_theme: str = "",
) -> dict[str, Any]:
    """V2 后半(桥接→分组→演绎/讲解渲染→装配)。**HTTP 入口从这里进**——前端(L0-L5)在路由侧
    已跑完且经人工审核,不在这里重跑(重跑会覆盖审核过的剧本、白烧 LLM)。全程入口
    `produce_tongjian_v2_episode` 也复用本函数。返回 {final_video, actual_usd, n_drama_inserts,
    n_narration, l5_by_insert}。

    `design_list`/`world_bible`:**都传**则复用前端已产/人审过的那份(考据 gold 不重生成),跳过桥接;
    任一为 None 则由桥接从 `raw_text` 现生成。★ 无论哪条路径,演绎段与讲解段拿到的都是**同一份**
    world_bible(见下)。

    ★★ `world_bible` 是**演绎段与讲解段的唯一共用真源**:canon/空景板/讲解静帧的考据 negatives 与
    historical directive 全从这份读——跨栈接缝能接上的根本(见模块 docstring)。"""
    from hevi.director.pipeline_schemas import Concept
    from hevi.image.qwen_image_service import qwen_image_generate

    if image_gen_fn is None:
        image_gen_fn = qwen_image_generate
    if tts_fn is None:
        from hevi.audio.edge_tts_custom import edge_tts_synthesize_smart

        tts_fn = edge_tts_synthesize_smart
    _loc_theme = "/".join(location.values()) if isinstance(location, dict) else location
    concept = concept or Concept(theme=_loc_theme, tone="庄重厚重", style="历史正剧")
    # 画幅:横屏(默认,历史正剧观感)=1280×720/16:9;竖屏=720×1280/9:16。qwen-image canon/空景板
    # 默认已是 1280×720 横屏,横屏路无需改;竖屏才需另传 size(暂未接,当前只做横屏/竖屏切 ratio+装配)。
    vid_w, vid_h, vid_ratio = (1280, 720, "16:9") if landscape else (720, 1280, "9:16")
    id_to_name = character_id_to_name(character_bible)
    voices = voice_by_speaker or {c.name: "zh-CN-YunjianNeural" for c in character_bible.characters}
    run_dir = output_path.parent
    run_dir.mkdir(parents=True, exist_ok=True)

    # ── 桥接:drama 过滤 + 共用 world_bible(人审 gold 已传则复用,不重生成)──
    if design_list is None or world_bible is None:
        design_list, _sss_all, world_bible = await build_v2_inputs_from_tongjian(
            script=script,
            shot_list=shotlist,
            character_bible=character_bible,
            material_text=raw_text,
            concept=concept,
            llm=llm,
        )

    # ── 演绎段资产:canon(共用 world_bible 考据 negatives)+ 空景板 ──
    lines_by_id = {ln.line_id: ln for ln in script.lines}
    groups = group_shots_by_kind(shotlist, script)
    drama_names = {
        id_to_name.get(cid, cid)
        for kind, shots in groups
        if kind == "drama"
        for sh in shots
        for cid in sh.characters
    }
    appearance = {c.name: c.appearance for c in character_bible.characters}
    subject_ref_paths = await _ensure_canon(
        names=drama_names,
        appearance=appearance,
        world_bible=world_bible,
        out_dir=run_dir / "canon",
        image_gen_fn=image_gen_fn,
    )

    # 空景板按 location 去重生成(多设定剧集:室内朝堂/室外市集本就该用各自的板,否则影调/构图
    # 被单板拉平,削弱 per-scene 校色的意义)。`location` 可传 str(全片一处)或 {scene_id: str}。
    from hevi.director.shot_recipes import palace_scale_directive

    plate_neg = ",".join(getattr(world_bible.visual, "negative_list", []) or [])
    style_dir = getattr(world_bible.visual, "style_render_directive", "") or ""
    # 宏伟场景(宫殿/朝堂/大殿/城墙/庙宇)空景板叠加纵深仰拍尺度卡,治"大殿不宏伟"(配方卡真源)。
    _MONUMENTAL = ("宫", "殿", "朝堂", "城墙", "城门", "庙", "陵", "阙")
    plate_cache: dict[str, str] = {}

    async def _plate_for(loc: str) -> str:
        if loc not in plate_cache:
            p = run_dir / f"scene_plate_{len(plate_cache)}.png"
            scale = palace_scale_directive() if any(k in loc for k in _MONUMENTAL) else ""
            await image_gen_fn(
                prompt=f"写实历史正剧电影空景,{loc},无人,自然天光,{style_dir}{scale}",
                output_path=p,
                seed=7 + len(plate_cache),
                negative_prompt=plate_neg,
            )
            plate_cache[loc] = str(p)
        return plate_cache[loc]

    def _loc_for(scene_id: str) -> str:
        return (
            location.get(scene_id, next(iter(location.values())))
            if isinstance(location, dict)
            else location
        )

    # ── 逐组渲染(叙事序:drama 插段→produce_v2,narration→讲解静帧)──
    episode_clips: list[Path] = []
    episode_tiers: list[tuple[str, str]] = []  # 每 clip 的 (置信档, 出处),装配时烧角标
    total_usd = 0.0
    l5_by_insert: list[dict] = []
    drama_idx = narr_idx = 0

    # 开头点主题(§用户要求):片头一个讲解镜口播主题(如"今天,我们回到栎阳变法的现场…")。
    # intro_theme 为空则不加(默认由 concept 兜底一句)。
    intro = intro_theme or f"今天,我们回到{_loc_theme}的现场,看看那段真实发生过的历史。"
    if intro.strip():
        first_loc = _loc_for(groups[0][1][0].scene_id) if groups else _loc_theme
        intro_clip = await render_jiangjie_clip(
            visual_prompt=f"历史正剧开场空景,{first_loc}",
            narration_text=intro,
            world_bible=world_bible,
            out_dir=run_dir / "jiangjie",
            clip_id="intro",
            drift_sign=1,
            image_gen_fn=image_gen_fn,
            tts_fn=tts_fn,
            width=vid_w,
            height=vid_h,
        )
        episode_clips.append(intro_clip)
        episode_tiers.append(("推演", ""))
    for gi, (kind, shots) in enumerate(groups):
        if kind == "drama":
            # ── $80 熔断:在烧这段之前查帽。会超就暂停,不烧、不静默停,报已花 + 列剩余镜。──
            est_next = len(shots) * _EST_USD_PER_DRAMA_SHOT
            if budget_usd is not None and total_usd + est_next > budget_usd:
                remaining = [s.shot_id for _, ss in groups[gi:] for s in ss]
                raise BudgetPauseError(
                    spent=round(total_usd, 3),
                    cap=budget_usd,
                    remaining_shots=remaining,
                    done_clips=[str(c) for c in episode_clips],
                )
            loc = _loc_for(shots[0].scene_id)
            clip, cfg = await _render_drama_insert(
                shots=shots,
                script=script,
                id_to_name=id_to_name,
                design_list=design_list,
                world_bible=world_bible,
                subject_ref_paths=subject_ref_paths,
                scene_plate=await _plate_for(loc),
                location=loc,
                voices=voices,
                run_dir=run_dir / f"yanyi_{drama_idx}",
                llm=llm,
                gen_fn=gen_fn,
                ratio=vid_ratio,
            )
            episode_clips.append(clip)
            episode_tiers.append(_clip_tier(shots, "drama", lines_by_id))
            total_usd += float(cfg.get("actual_usd") or 0.0)
            l5_by_insert.append(
                {
                    "insert": drama_idx,
                    "l5": cfg.get("l5_checklist"),
                    "retake": cfg.get("retake_candidates"),
                }
            )
            drama_idx += 1
        else:
            shot = shots[0]
            clip = await render_jiangjie_clip(
                visual_prompt=shot.visual_prompt or "",
                narration_text=_narration_text(shot, lines_by_id),
                world_bible=world_bible,
                out_dir=run_dir / "jiangjie",
                clip_id=f"narr_{narr_idx}",
                drift_sign=1 if narr_idx % 2 == 0 else -1,
                image_gen_fn=image_gen_fn,
                tts_fn=tts_fn,
                width=vid_w,
                height=vid_h,
            )
            episode_clips.append(clip)
            episode_tiers.append(_clip_tier(shots, "narration", lines_by_id))
            narr_idx += 1

    final = assemble_episode(
        clips=episode_clips, output_path=output_path, width=vid_w, height=vid_h, tiers=episode_tiers
    )
    return {
        "final_video": str(final),
        "actual_usd": round(total_usd, 3),
        "n_drama_inserts": drama_idx,
        "n_narration": narr_idx,
        "l5_by_insert": l5_by_insert,
    }
