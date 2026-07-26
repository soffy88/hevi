"""通鉴 V2 固化管线测试(SPEC-005-V2 固化,2026-07-24)。

覆盖:①叙事序分组(纯,确定性)②讲解静帧 prompt/negatives 取自 world_bible ③**固化核心不变量:
讲解段与演绎段共用同一份 world_bible → 两栈拿到的考据 negatives 逐字一致**(接缝能接上的根本,见
v2_episode / v2_jiangjie docstring)④后半编排端到端接线(昂贵调用全替身,验计数/交错序/成本汇总)。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hevi.tongjian import v2_episode
from hevi.tongjian.schemas import (
    CharacterBible,
    CharacterBibleEntry,
    Script,
    ScriptLine,
    Shot,
    ShotCamera,
    ShotList,
)
from hevi.tongjian.v2_episode import (
    BudgetPauseError,
    _ensure_canon,
    group_shots_by_kind,
    render_tongjian_v2_backhalf,
)
from hevi.tongjian.v2_jiangjie import _jiangjie_negatives, _jiangjie_prompt

_NEGS = ["砖砌拱券", "明清冠服", "马镫", "纸张"]


def _wb() -> Any:
    """演绎/讲解共用的假 world_bible:只需 .visual.negative_list + .style_render_directive。"""
    return SimpleNamespace(
        visual=SimpleNamespace(
            negative_list=list(_NEGS),
            style_render_directive="史诗历史正剧摄影,自然天光与火把光源",
        )
    )


def _bible() -> CharacterBible:
    return CharacterBible(
        characters=[
            CharacterBibleEntry(character_id="c1", name="人物甲", appearance="锐利中年男子")
        ]
    )


def _script() -> Script:
    return Script(
        lines=[
            ScriptLine(line_id="n0", type="narration", text="秦孝公求贤。"),
            ScriptLine(line_id="d1", type="dialogue", speaker="c1", text="治世不一道。"),
            ScriptLine(line_id="d2", type="dialogue", speaker="c1", text="便国不法古。"),
            ScriptLine(line_id="n1", type="narration", text="孝公善之。"),
            ScriptLine(line_id="d3", type="dialogue", speaker="c1", text="立木南门。"),
            ScriptLine(line_id="n2", type="narration", text="卒定变法之令。"),
        ]
    )


def _shotlist() -> ShotList:
    """narration / drama×2 / narration / drama×1 / narration —— 分组应得 2 演绎插段 + 3 讲解镜。"""
    return ShotList(
        shots=[
            Shot(
                shot_id="s_n0",
                line_ids=["n0"],
                scene_id="A",
                visual_prompt="宫门求贤榜",
                camera=ShotCamera(),
            ),
            Shot(
                shot_id="s_d1",
                line_ids=["d1"],
                scene_id="A",
                characters=["c1"],
                camera=ShotCamera(),
            ),
            Shot(
                shot_id="s_d2",
                line_ids=["d2"],
                scene_id="A",
                characters=["c1"],
                camera=ShotCamera(),
            ),
            Shot(
                shot_id="s_n1",
                line_ids=["n1"],
                scene_id="A",
                visual_prompt="孝公颔首",
                camera=ShotCamera(),
            ),
            Shot(
                shot_id="s_d3",
                line_ids=["d3"],
                scene_id="B",
                characters=["c1"],
                camera=ShotCamera(),
            ),
            Shot(
                shot_id="s_n2",
                line_ids=["n2"],
                scene_id="B",
                visual_prompt="变法令布告",
                camera=ShotCamera(),
            ),
        ]
    )


# ── ① 叙事序分组 ────────────────────────────────────────────────────────────
def test_group_merges_contiguous_drama_and_keeps_narration_singletons() -> None:
    groups = group_shots_by_kind(_shotlist(), _script())
    kinds = [(k, [s.shot_id for s in shots]) for k, shots in groups]
    assert kinds == [
        ("narration", ["s_n0"]),
        ("drama", ["s_d1", "s_d2"]),  # 相邻演绎镜合成一个插段
        ("narration", ["s_n1"]),
        ("drama", ["s_d3"]),
        ("narration", ["s_n2"]),
    ]


def test_group_splits_contiguous_drama_at_scene_boundary() -> None:
    """相邻 drama 镜但 scene_id 不同 → 不并成一段(各自设定/时空,不共享 produce_v2 链/地点/板)。"""
    script = Script(
        lines=[
            ScriptLine(line_id="d1", type="dialogue", speaker="c1", text="立木南门。"),
            ScriptLine(line_id="d2", type="dialogue", speaker="c1", text="颁垦草令。"),
        ]
    )
    shots = ShotList(
        shots=[
            Shot(
                shot_id="s_a",
                line_ids=["d1"],
                scene_id="E004",
                characters=["c1"],
                camera=ShotCamera(),
            ),
            Shot(
                shot_id="s_b",
                line_ids=["d2"],
                scene_id="E005",
                characters=["c1"],
                camera=ShotCamera(),
            ),
        ]
    )
    groups = group_shots_by_kind(shots, script)
    assert [(k, [s.shot_id for s in ss]) for k, ss in groups] == [
        ("drama", ["s_a"]),  # E004
        ("drama", ["s_b"]),  # E005 —— 跨场断开,不与 E004 并
    ]


def test_group_drops_transition_shots() -> None:
    script = Script(lines=[ScriptLine(line_id="n0", type="narration", text="t")])
    shots = ShotList(
        shots=[
            Shot(shot_id="s_n0", line_ids=["n0"], scene_id="A", camera=ShotCamera()),
            Shot(shot_id="s_t", line_ids=[], scene_id="A", is_transition=True, camera=ShotCamera()),
        ]
    )
    groups = group_shots_by_kind(shots, script)
    assert [k for k, _ in groups] == ["narration"]  # 过场镜丢弃


# ── ② 讲解静帧 prompt/negatives 取自 world_bible ────────────────────────────
def test_jiangjie_prompt_appends_world_bible_directive() -> None:
    p = _jiangjie_prompt("宫门求贤榜", _wb())
    assert "宫门求贤榜" in p
    assert "史诗历史正剧摄影" in p  # 画风锚来自 world_bible.style_render_directive


def test_jiangjie_negatives_are_world_bible_negative_list() -> None:
    assert _jiangjie_negatives(_wb()) == ",".join(_NEGS)


def test_jiangjie_negatives_empty_when_no_world_bible() -> None:
    assert _jiangjie_negatives(None) == ""


# ── ③ 固化核心不变量:两栈共用 world_bible → 考据 negatives 逐字一致 ──────────
@pytest.mark.asyncio
async def test_shared_world_bible_negatives_reach_both_yanyi_and_jiangjie(tmp_path: Path) -> None:
    """演绎段 canon 与讲解段静帧必须从同一份 world_bible 拿到**逐字相同**的考据 negatives——这是
    跨栈接缝能接上的根本(v2_jiangjie docstring 里写死的结论),用测试钉住,防它再断链。"""
    wb = _wb()
    seen: list[str] = []

    async def _capture_img(
        *, prompt: str, output_path: Path, seed: int, negative_prompt: str
    ) -> None:
        seen.append(negative_prompt)

    # 演绎段 canon 路径拿到的 negatives
    await _ensure_canon(
        names={"人物甲"},
        appearance={"人物甲": "锐利中年男子"},
        world_bible=wb,
        out_dir=tmp_path / "canon",
        image_gen_fn=_capture_img,
    )
    canon_neg = seen[-1]
    # 讲解段静帧路径拿到的 negatives
    jiangjie_neg = _jiangjie_negatives(wb)

    assert canon_neg == jiangjie_neg == ",".join(_NEGS)  # 同源同调,不是两套手写词


# ── ④ 后半编排端到端接线(昂贵调用全替身)──────────────────────────────────
@pytest.mark.asyncio
async def test_backhalf_wires_full_flow(tmp_path: Path, monkeypatch: Any) -> None:
    wb = _wb()

    async def _fake_bridge(**kwargs: Any) -> tuple[Any, Any, Any]:
        return object(), None, wb  # (design_list, sss_all, world_bible)

    async def _fake_run_v2_produce(
        *, task_repo: Any, task_id: Any, run_dir: Path, **kw: Any
    ) -> None:
        vid = Path(run_dir) / "final.mp4"
        vid.parent.mkdir(parents=True, exist_ok=True)
        vid.write_bytes(b"x")
        await task_repo.update_task(
            task_id, {"result_video_path": str(vid), "config_json": {"actual_usd": 5.0}}
        )

    jiangjie_calls: list[str] = []

    async def _fake_jiangjie(*, clip_id: str, out_dir: Path, world_bible: Any, **kw: Any) -> Path:
        assert world_bible is wb  # 讲解段拿到的正是共用那份
        jiangjie_calls.append(clip_id)
        p = Path(out_dir) / f"{clip_id}.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    assembled: dict[str, Any] = {}

    def _fake_assemble(*, clips: list[Path], output_path: Path, **kw: Any) -> Path:
        assembled["clips"] = list(clips)
        return output_path

    async def _noop_img(*, prompt: str, output_path: Path, seed: int, negative_prompt: str) -> None:
        pass

    monkeypatch.setattr(v2_episode, "build_v2_inputs_from_tongjian", _fake_bridge)
    monkeypatch.setattr(v2_episode, "render_jiangjie_clip", _fake_jiangjie)
    monkeypatch.setattr(v2_episode, "assemble_episode", _fake_assemble)
    monkeypatch.setattr("hevi.director.produce_v2.run_v2_produce", _fake_run_v2_produce)

    result = await render_tongjian_v2_backhalf(
        script=_script(),
        shotlist=_shotlist(),
        character_bible=_bible(),
        raw_text="原文",
        output_path=tmp_path / "ep.mp4",
        location="栎阳",
        image_gen_fn=_noop_img,
    )

    assert result["n_drama_inserts"] == 2
    assert result["n_narration"] == 3
    assert result["actual_usd"] == 10.0  # 2 插段 × $5,按段汇总
    assert jiangjie_calls == ["narr_0", "narr_1", "narr_2"]
    # 装配 clip 顺序 = 叙事序(讲解/演绎交错):讲→演→讲→演→讲,共 5 段
    assert len(assembled["clips"]) == 5


@pytest.mark.asyncio
async def test_backhalf_per_scene_location_and_injected_assets(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """多设定剧集:location 传 {scene_id: 地点} → 每场用各自空景板 + 各自 produce_v2 location;
    且传入人审 design_list/world_bible 时跳过桥接(复用考据 gold,不重生成)。"""
    wb = _wb()
    bridge_called = {"n": 0}

    async def _fake_bridge(**kwargs: Any) -> tuple[Any, Any, Any]:
        bridge_called["n"] += 1
        return object(), None, wb

    screenplay_locs: list[str] = []

    async def _fake_run_v2_produce(
        *, task_repo: Any, task_id: Any, run_dir: Path, screenplay: Any, **kw: Any
    ) -> None:
        screenplay_locs.append(screenplay.scenes[0].location)
        vid = Path(run_dir) / "final.mp4"
        vid.parent.mkdir(parents=True, exist_ok=True)
        vid.write_bytes(b"x")
        await task_repo.update_task(
            task_id, {"result_video_path": str(vid), "config_json": {"actual_usd": 1.0}}
        )

    async def _fake_jiangjie(*, clip_id: str, out_dir: Path, **kw: Any) -> Path:
        p = Path(out_dir) / f"{clip_id}.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    plate_prompts: list[str] = []

    async def _capture_img(
        *, prompt: str, output_path: Path, seed: int, negative_prompt: str
    ) -> None:
        if "空景" in prompt:
            plate_prompts.append(prompt)

    monkeypatch.setattr(v2_episode, "build_v2_inputs_from_tongjian", _fake_bridge)
    monkeypatch.setattr(v2_episode, "render_jiangjie_clip", _fake_jiangjie)
    monkeypatch.setattr(
        v2_episode, "assemble_episode", lambda *, clips, output_path, **kw: output_path
    )
    monkeypatch.setattr("hevi.director.produce_v2.run_v2_produce", _fake_run_v2_produce)

    await render_tongjian_v2_backhalf(
        script=_script(),
        shotlist=_shotlist(),
        character_bible=_bible(),
        raw_text="原文",
        output_path=tmp_path / "ep.mp4",
        location={"A": "室内朝堂", "B": "室外市集"},  # s_d1/s_d2 在场 A,s_d3 在场 B
        image_gen_fn=_capture_img,
        design_list=object(),
        world_bible=wb,  # 注入考据 gold
    )

    assert bridge_called["n"] == 0, "传了 design_list+world_bible 应跳过桥接"
    assert screenplay_locs == ["室内朝堂", "室外市集"], "每场演绎用各自 location"
    # 两个不同 location → 两张不同空景板(去重生成)
    assert len(set(plate_prompts)) == 2


# ── ⑤ $80 熔断:超帽前暂停,不烧不停,报已花 + 列剩余镜 ────────────────────────
@pytest.mark.asyncio
async def test_backhalf_budget_pause_before_overspend(tmp_path: Path, monkeypatch: Any) -> None:
    """累计 + 下一插段预估将超帽 → 在烧那段之前抛 BudgetPauseError(已花/剩余镜),不继续烧。"""
    wb = _wb()

    async def _fake_bridge(**kwargs: Any) -> tuple[Any, Any, Any]:
        return object(), None, wb

    async def _fake_run(*, task_repo: Any, task_id: Any, run_dir: Path, **kw: Any) -> None:
        vid = Path(run_dir) / "final.mp4"
        vid.parent.mkdir(parents=True, exist_ok=True)
        vid.write_bytes(b"x")
        await task_repo.update_task(
            task_id, {"result_video_path": str(vid), "config_json": {"actual_usd": 5.0}}
        )

    async def _fake_jiangjie(*, clip_id: str, out_dir: Path, **kw: Any) -> Path:
        p = Path(out_dir) / f"{clip_id}.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    async def _noop_img(*, prompt: str, output_path: Path, seed: int, negative_prompt: str) -> None:
        pass

    monkeypatch.setattr(v2_episode, "build_v2_inputs_from_tongjian", _fake_bridge)
    monkeypatch.setattr(v2_episode, "render_jiangjie_clip", _fake_jiangjie)
    monkeypatch.setattr(
        v2_episode, "assemble_episode", lambda *, clips, output_path, **kw: output_path
    )
    monkeypatch.setattr("hevi.director.produce_v2.run_v2_produce", _fake_run)

    # 帽 $4:插段0(2镜 est 2.6)可烧→花掉 $5;插段1(1镜 est 1.3)前查 5+1.3>4 → 熔断
    with pytest.raises(BudgetPauseError) as ei:
        await render_tongjian_v2_backhalf(
            script=_script(),
            shotlist=_shotlist(),
            character_bible=_bible(),
            raw_text="原文",
            output_path=tmp_path / "ep.mp4",
            location="栎阳",
            image_gen_fn=_noop_img,
            design_list=object(),
            world_bible=wb,
            budget_usd=4.0,
        )
    err = ei.value
    assert err.spent == 5.0  # 只烧了插段0
    assert err.cap == 4.0
    assert err.remaining_shots == ["s_d3", "s_n2"]  # 从熔断那组起的所有剩余镜
    assert len(err.done_clips) >= 1  # 已出的分段保留,续跑不白烧


@pytest.mark.asyncio
async def test_backhalf_no_budget_runs_all(tmp_path: Path, monkeypatch: Any) -> None:
    """budget_usd=None(不设帽)→ 不触发熔断,照常跑完。"""
    wb = _wb()

    async def _fake_bridge(**kwargs: Any) -> tuple[Any, Any, Any]:
        return object(), None, wb

    async def _fake_run(*, task_repo: Any, task_id: Any, run_dir: Path, **kw: Any) -> None:
        vid = Path(run_dir) / "final.mp4"
        vid.parent.mkdir(parents=True, exist_ok=True)
        vid.write_bytes(b"x")
        await task_repo.update_task(
            task_id, {"result_video_path": str(vid), "config_json": {"actual_usd": 5.0}}
        )

    async def _fake_jiangjie(*, clip_id: str, out_dir: Path, **kw: Any) -> Path:
        p = Path(out_dir) / f"{clip_id}.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        return p

    async def _noop_img(*, prompt: str, output_path: Path, seed: int, negative_prompt: str) -> None:
        pass

    monkeypatch.setattr(v2_episode, "build_v2_inputs_from_tongjian", _fake_bridge)
    monkeypatch.setattr(v2_episode, "render_jiangjie_clip", _fake_jiangjie)
    monkeypatch.setattr(
        v2_episode, "assemble_episode", lambda *, clips, output_path, **kw: output_path
    )
    monkeypatch.setattr("hevi.director.produce_v2.run_v2_produce", _fake_run)

    result = await render_tongjian_v2_backhalf(
        script=_script(),
        shotlist=_shotlist(),
        character_bible=_bible(),
        raw_text="原文",
        output_path=tmp_path / "ep.mp4",
        location="栎阳",
        image_gen_fn=_noop_img,
        design_list=object(),
        world_bible=wb,
        budget_usd=None,
    )
    assert result["n_drama_inserts"] == 2  # 两段都烧了


# ── 修:canon appearance 剔除对比性描述(防单人定妆照渲成两人)─────────────────
def test_strip_comparative_removes_contrast_clauses() -> None:
    from hevi.tongjian.v2_episode import _strip_comparative

    got = _strip_comparative("秦廷尉,玄端朝服,精悍锐利瘦长脸,须髯修剪,与王绾明显区分")
    assert "王绾" not in got and "区分" not in got  # 对比分句被剔除
    assert "玄端朝服" in got and "须髯修剪" in got  # 本人特征保留
    # 无对比词则原样(逗号归一)
    assert _strip_comparative("玄色深衣,束发冠") == "玄色深衣,束发冠"
