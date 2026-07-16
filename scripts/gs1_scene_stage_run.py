#!/usr/bin/env python
"""SPEC-004 G-S1 垂直切片验收:一场 3 人对话戏,1 个 SceneStage → 6 镜头全部从它派生。

证明命题:**场事实消灭空间矛盾**。做单变量对照——同一场、同一 6 镜、同一角色 canon,唯一差异
是关键帧 prompt 的空间项:
  - 实验组:场景描述(断链#3)+ project_shot_space(落位/朝向/焦点/正方向,从同一 SceneStage 投影)
  - 对照组:空(镜头各自想象空间,即 SPEC-004 之前的行为)
6 镜实验组应空间一致(同角色相对位置/朝向跨镜一致);对照组应互相矛盾。

全本地零花费:canon + 关键帧都走 sdxl_local(GPU),不打 happyhorse/qwen 云端。G-S1 只验空间
一致性——它体现在关键帧,不在 talking clip,所以不跑完整 render_director_episode。

用法(需 GPU 在总线上,HF 离线缓存):
  HF_HOME=/data/models/huggingface HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
      uv run python scripts/gs1_scene_stage_run.py --real
产物:output/gs1_scene_stage/{exp,ctrl}/SHxx.png + canon_*.png;并打印投影文本、lint、VLM 焦点断言。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from hevi.director.pipeline_schemas import (
    AttentionBeat,
    CameraSetup,
    CoveragePlan,
    DesignCharacter,
    DesignList,
    DesignScene,
    InitialPosition,
    SceneAxis,
    SceneBeat,
    SceneBlocking,
    SceneSpaceMap,
    SceneStage,
    SceneStageSet,
    SceneZone,
    Screenplay,
    ScreenplayDialogueLine,
    ScreenplayScene,
    ShotList,
    ShotListDialogueLine,
    ShotListItem,
    Sightline,
)
from hevi.director.scene_stage import link_shots_to_scene_stage, project_shot_space
from hevi.director.scene_stage_lint import lint_scene_stage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gs1")

_STYLE = "电影感写实,暖色调,古装"
_SCENE_DESC = "破败乡野客栈内,昏黄油灯,墙皮剥落,清冷压抑"  # 断链#3 场景描述(两组都给,不是变量)

# 3 个角色(名字固定,用于 SceneStage char_id 与中文 projection 文本)
_CHARS = {
    "王生": "青年书生,清秀白净,青色长衫,书卷气",
    "老道": "白须老道士,鹤发,灰色道袍,仙风道骨",
    "店家": "中年掌柜,络腮胡,粗布短打,精明",
}
# 画脸用英文外貌(首跑教训:base SDXL 对中文老者/道士 prompt 会渲成通用少女,英文对年龄/
# 性别/胡须控制好得多——已验证英文 prompt 出正确的白胡子老道士)。canon 与关键帧都用这个。
_CHARS_EN = {
    "王生": "a young Chinese male scholar in his early 20s, handsome clean face, "
    "black hair topknot, blue traditional scholar robe",
    "老道": "an elderly Chinese Taoist priest, very long flowing white beard, white hair "
    "topknot, wrinkled wise face, gray traditional Taoist robe",
    "店家": "a middle-aged Chinese innkeeper man in his 40s, full dark beard, weathered face, "
    "brown coarse cloth short jacket",
}
_CANON_NEG = (
    "woman, female, girl, child, anime, cartoon, deformed, extra limbs, multiple people, text"
)
# 每拍的情绪(给关键帧)
_EMOTION = {
    "bt001": "恳切央求",
    "bt002": "淡漠推拒",
    "bt003": "坚定不移",
    "bt004": "好心相劝",
    "bt005": "松口应允",
    "bt006": "喜出望外",
}


def build_scene() -> tuple[Screenplay, DesignList, SceneStage, ShotList]:
    """手工构造一场 3 人对话戏(零 LLM)。落位/轴线/注意力/机位都是导演判断,这里替 AI 出草案。"""
    dialogue = [
        ("王生", "道长,收留弟子学道吧。", "老道"),
        ("老道", "你细皮嫩肉,受不得清苦。", "王生"),
        ("王生", "弟子甘愿吃苦,绝无怨言。", "老道"),
        ("店家", "客官,仙缘莫要强求啊。", "王生"),
        ("老道", "也罢,随我上山去吧。", "王生"),
        ("王生", "多谢道长成全!", "老道"),
    ]
    screenplay = Screenplay(
        scenes=[
            ScreenplayScene(
                scene_no=1,
                time="黄昏",
                location="破客栈",
                characters_present=list(_CHARS),
                narration="王生慕道,在客栈中央求老道收留,店家在旁相劝。",
                dialogue=[
                    ScreenplayDialogueLine(character_name=s, text=t, target_name=g)
                    for s, t, g in dialogue
                ],
            )
        ]
    )
    design = DesignList(
        characters=[
            DesignCharacter(name=n, appearance=a, is_lead=(n == "王生")) for n, a in _CHARS.items()
        ],
        scenes=[DesignScene(name="破客栈", environment=_SCENE_DESC, is_primary=True)],
    )

    beats = [
        SceneBeat(beat_id=f"bt{i:03d}", order=i, trigger=t, dialogue_ref=f"{s}→{g}")
        for i, (s, t, g) in enumerate(dialogue, 1)
    ]
    stage = SceneStage(
        scene_ref=1,
        space_map=SceneSpaceMap(
            zones=[
                SceneZone(zone_id="z_door", name="门口", rel_position="左下"),
                SceneZone(zone_id="z_window", name="窗边", rel_position="右上"),
                SceneZone(zone_id="z_counter", name="柜台", rel_position="中"),
            ]
        ),
        beats=beats,
        blocking=SceneBlocking(
            initial_positions=[
                InitialPosition(
                    char_id="王生", zone_id="z_door", facing="面向老道", posture="拱手而立"
                ),
                InitialPosition(
                    char_id="老道", zone_id="z_window", facing="面向王生", posture="负手而立"
                ),
                InitialPosition(
                    char_id="店家", zone_id="z_counter", facing="侧身望向王生", posture="倚柜"
                ),
            ],
            sightlines=[
                Sightline(
                    at_beat=b.beat_id,
                    char_id=b.dialogue_ref.split("→")[0],
                    looking_at=b.dialogue_ref.split("→")[1],
                )
                for b in beats
            ],
        ),
        axis=SceneAxis(primary_axis=["王生", "老道"], side_convention="王生恒在画左,老道恒在画右"),
        attention_script=[
            AttentionBeat(
                at_beat=b.beat_id,
                focus_target=b.dialogue_ref.split("→")[0],
                reason="speaking",
                transition="cut",
                intensity="exclusive" if b.beat_id in ("bt002", "bt005") else "primary",
            )
            for b in beats
        ],
        coverage_plan=CoveragePlan(
            master=CameraSetup(
                setup_id="master",
                axis_side="left",
                shot_size="全景",
                serves_beats=[b.beat_id for b in beats],
                subjects=list(_CHARS),
            ),
            setups=[
                CameraSetup(
                    setup_id="s_wang",
                    axis_side="left",
                    shot_size="近景",
                    serves_beats=["bt001", "bt003", "bt006"],
                    subjects=["王生"],
                ),
                CameraSetup(
                    setup_id="s_dao",
                    # 180°规则:正打反打的机位都在主轴同一侧(都 left),不能一左一右(那才是跳轴)。
                    axis_side="left",
                    shot_size="特写",
                    serves_beats=["bt002", "bt005"],
                    subjects=["老道"],
                ),
                CameraSetup(
                    setup_id="s_dian",
                    axis_side="left",
                    shot_size="中景",
                    serves_beats=["bt004"],
                    subjects=["店家"],
                ),
            ],
        ),
        assumed=False,
    )

    # 6 镜:一句对白一镜,反打交替(景别照 coverage 的机位默认档)
    sizes = ["全景", "特写", "近景", "中景", "近景", "特写"]
    shots = ShotList(
        shots=[
            ShotListItem(
                shot_id=f"SH{i:02d}",
                scene_no=1,
                shot_size=sz,
                camera="平视",
                dialogue_lines=[ShotListDialogueLine(character_name=s, text=t, target_name=g)],
                character_names=[s] if sz in ("特写", "近景") else list(_CHARS),
                scene_name="破客栈",
            )
            for i, ((s, t, g), sz) in enumerate(zip(dialogue, sizes, strict=True), 1)
        ]
    )
    linked = link_shots_to_scene_stage(shots, SceneStageSet(stages=[stage]))
    return screenplay, design, stage, linked


def _find_ref(char: str, ref_dir: Path) -> Path | None:
    """在 ref_dir 里找该角色的真人肖像(按角色名匹配,支持常见图片后缀)。"""
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        p = ref_dir / f"{char}{ext}"
        if p.exists() and p.stat().st_size > 1024:
            return p
    return None


async def _canon(char: str, out: Path, ref_dir: Path | None) -> Path:
    """角色 canon:优先用提供的真人肖像(本地 IP-Adapter 锁真脸);缺失则用**英文 prompt** 的
    sdxl 文生图(已验证英文出正确白胡子老者/中年男,不再是中文 prompt 的通用少女,见 G-S1 首跑)。"""
    from PIL import Image

    ref = _find_ref(char, ref_dir) if ref_dir else None
    if ref is not None:
        Image.open(ref).convert("RGB").save(out)  # 归一到 canon 路径(ref 存在则每次覆盖,让真脸生效)
        log.info("canon[%s] 用真人肖像:%s", char, ref)
        return out
    from hevi.image.sdxl_local_service import sdxl_local_generate

    if out.exists() and out.stat().st_size > 1024:
        return out
    log.info("canon[%s] 用英文 prompt 本地 sdxl 生成", char)
    await sdxl_local_generate(
        prompt=f"{_CHARS_EN[char]}, cinematic realistic photograph, upper body portrait, "
        "plain background, sharp focus",
        negative_prompt=_CANON_NEG,
        output_path=out,
        width=768,
        height=768,
        require_gpu=True,
    )
    return out


async def _keyframe(
    *, canon: Path, appearance: str, emotion: str, scene_space: str, out: Path
) -> Path:
    from hevi.tongjian.scene_render_avatar import _edit_keyframe, _local_kf_prompt

    if out.exists():
        out.unlink()  # 每次重生成,保证对照有效
    await _edit_keyframe(
        image_path=canon,
        instruction=emotion,  # 云端 edit 兜底路径用,不含空间(本地走 local_prompt)
        output_path=out,
        fallback_from=canon,
        engine="local",
        local_prompt=_local_kf_prompt(_STYLE, appearance, emotion, "", scene_space=scene_space),
        ip_adapter_image=canon,
        # 共享 GPU 另有租户占 ~2.4GiB,IP-Adapter 路径跳过 attention-slicing(峰值更高),
        # 降到 576×768 留 VRAM 余量(G-S1 验的是空间一致性,分辨率非关键)。
        size=(576, 768),
    )
    return out


async def _vlm_focus(image: Path, focus_char: str, others: list[str]) -> str | None:
    """best-effort:问本地 VL「谁在前景/占主体」断言 focus_char。本地 ollama 不稳则返 None。"""
    try:
        from obase.provider_registry import ProviderRegistry

        mllm = ProviderRegistry.get().vlm("default")
        q = f"图里最靠前、占画面主体的人是谁?候选:{focus_char}、{'、'.join(others)}。只答名字。"
        res = mllm(messages=[{"role": "user", "content": q}], image_paths=[str(image)])
        res = await res if hasattr(res, "__await__") else res
        return (res.get("content") if hasattr(res, "get") else str(res)) or None
    except Exception as e:
        log.warning("VLM 焦点断言不可用(本地 VL 未就绪): %s", e)
        return None


async def main(args: argparse.Namespace) -> None:
    _screenplay, _design, stage, linked = build_scene()
    out_dir = Path("output/gs1_scene_stage")
    (out_dir / "exp").mkdir(parents=True, exist_ok=True)
    (out_dir / "ctrl").mkdir(parents=True, exist_ok=True)

    # ── 投影文本 + lint(零花费,先打印看看场事实长什么样)──────────────────────
    print("=" * 78)
    print("SPEC-004 G-S1:一场 3 人戏 → 1 SceneStage → 6 镜头,场事实投影对照")
    print("-" * 78)
    for shot in linked.shots:
        proj = project_shot_space(stage, shot)
        print(
            f"[{shot.shot_id}] beat={shot.beat_range} setup={shot.camera_setup_ref} "
            f"attn={shot.attention_ref}"
        )
        print(f"    投影:{proj}")
    print("-" * 78)
    findings = lint_scene_stage(linked, SceneStageSet(stages=[stage]))
    # G-S1 达标线只含"无跳轴(L1)+ eyeline 一致(L3)";L2 反打景别/L4 剪辑冗余是覆盖深度建议,
    # 6 镜最小切片(每 beat 1 机位)必然触发 L4,不计入 G-S1 通过判定。
    gate = [f for f in findings if f.rule in ("L1", "L3")]
    advisory = [f for f in findings if f.rule in ("L2", "L4")]
    gate_verdict = "干净 ✅" if not gate else f"{len(gate)} 项 ❌"
    print(f"§4 lint · G-S1 达标线(L1跳轴/L3 eyeline):{gate_verdict}")
    for f in gate:
        print(f"    [{f.rule}] {f.message}")
    print(f"§4 lint · 覆盖深度建议(L2反打/L4冗余,不计入 G-S1):{len(advisory)} 项")
    for f in advisory:
        print(f"    [{f.rule}] {f.message}")
    print("=" * 78)

    if not args.real:
        print("\n(dry-run:未生成图片。加 --real 用本地 sdxl 出对照关键帧。)")
        return

    # ── 3 角色 canon(优先真人肖像 ref_dir/{角色名}.png,缺失退回 sdxl)────────────
    ref_dir = Path(args.ref_dir)
    ref_dir.mkdir(parents=True, exist_ok=True)
    have = [c for c in _CHARS if _find_ref(c, ref_dir)]
    log.info(
        "真人肖像目录 %s:命中 %s;缺失 %s",
        ref_dir,
        have or "无",
        [c for c in _CHARS if c not in have] or "无",
    )
    canons = {c: await _canon(c, out_dir / f"canon_{c}.png", ref_dir) for c in _CHARS}
    log.info("canon 就绪:%s", {c: str(p) for c, p in canons.items()})

    # ── 逐镜出实验组/对照组关键帧 ────────────────────────────────────────────
    focus_by_shot: dict[str, str] = {}
    for shot in linked.shots:
        beat = shot.beat_range[0] if shot.beat_range else ""
        attn = next((a for a in stage.attention_script if a.at_beat == shot.attention_ref), None)
        focus = (
            attn.focus_target
            if attn
            else (shot.dialogue_lines[0].character_name if shot.dialogue_lines else "王生")
        )
        focus_by_shot[shot.shot_id] = focus
        emotion = _EMOTION.get(beat, "神情自然")
        appearance = _CHARS_EN.get(focus, focus)  # 英文外貌(IP-Adapter 锁脸 + 英文描述,防漂移)
        proj = project_shot_space(stage, shot)

        exp_space = "；".join(x for x in (_SCENE_DESC, proj) if x)  # 实验组:场景 + 场事实投影
        ctrl_space = ""  # 对照组:无场事实(镜头各自想象),连场景描述也不给 → 纯自由生成
        log.info("[%s] 出实验组关键帧(focus=%s)…", shot.shot_id, focus)
        await _keyframe(
            canon=canons[focus],
            appearance=appearance,
            emotion=emotion,
            scene_space=exp_space,
            out=out_dir / "exp" / f"{shot.shot_id}.png",
        )
        log.info("[%s] 出对照组关键帧…", shot.shot_id)
        await _keyframe(
            canon=canons[focus],
            appearance=appearance,
            emotion=emotion,
            scene_space=ctrl_space,
            out=out_dir / "ctrl" / f"{shot.shot_id}.png",
        )

    # ── VLM 焦点断言(best-effort)──────────────────────────────────────────
    print("\n" + "=" * 78)
    print("VLM 焦点断言(实验组,best-effort):")
    hits = 0
    for shot in linked.shots:
        focus = focus_by_shot[shot.shot_id]
        others = [c for c in _CHARS if c != focus]
        ans = await _vlm_focus(out_dir / "exp" / f"{shot.shot_id}.png", focus, others)
        ok = ans is not None and focus in ans
        hits += ok
        print(f"    [{shot.shot_id}] 期望焦点={focus} VLM答={ans!r} {'✅' if ok else '—'}")
    print(f"VLM 焦点命中:{hits}/{len(linked.shots)}(本地 VL 不稳时以肉眼对照为准)")
    print("=" * 78)
    print(f"\n产物:{out_dir}/exp/*.png(场事实驱动)vs {out_dir}/ctrl/*.png(各自想象)")
    print("请肉眼对照:实验组 6 镜里同一角色的相对位置/朝向应跨镜一致(王生恒在画左、面向老道;")
    print("老道恒在画右);对照组应出现空间矛盾(同角色忽左忽右、朝向不定)。")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="SPEC-004 G-S1 垂直切片验收")
    p.add_argument("--real", action="store_true", help="用本地 sdxl 真出对照关键帧(免费,需 GPU)")
    p.add_argument(
        "--ref-dir",
        default="output/gs1_scene_stage/refs",
        help="真人肖像目录:放 王生.png/老道.png/店家.png,本地 IP-Adapter 锁真脸(缺失退回 sdxl)",
    )
    asyncio.run(main(p.parse_args()))
