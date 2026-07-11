"""C4: shot_scorecard — identity-anchored variant selection + omodul contract.

subject_embed is monkeypatched (per-path vectors) so the selection/aggregation logic
is tested deterministically without loading CLIP. Real-embedding selection is verified
manually (same-video 1.0 vs diff 0.799).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import hevi.verdict.scorecard as sc_mod
from hevi.storygraph.schemas import StoryCharacter, StoryRelationship
from hevi.verdict import (
    check_relationship_consistency,
    coarse_diagnosis,
    make_scorecard_consistency_fn,
    shot_scorecard,
)
from hevi.verdict.frame_extract import extract_representative_frame
from hevi.verdict.scorecard import _parse_shot_index


def _png(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n")  # header only; content unused (subject_embed mocked)
    return p


@pytest.fixture
def fake_embed(monkeypatch):
    # map path basename → vector
    table: dict[str, list[float]] = {}

    def _fake(*, image_path, kind="face"):
        return table[Path(image_path).name]

    monkeypatch.setattr(sc_mod, "subject_embed", _fake)
    return table


def test_picks_higher_identity_not_first(tmp_path, fake_embed):
    a, b = _png(tmp_path, "a.png"), _png(tmp_path, "b.png")
    fake_embed["a.png"] = [1.0, 0.0, 0.0]
    fake_embed["b.png"] = [0.0, 1.0, 0.0]
    ref = [1.0, 0.0, 0.0]  # matches a

    # b FIRST — pick-first would wrongly pick b
    sc = shot_scorecard(candidate_frames=[b, a], subject_ref_embedding=ref)
    assert sc.best_index == 1
    assert sc.best_frame.name == "a.png"
    assert sc.identity_score == pytest.approx(1.0)
    assert [round(r["identity"], 3) for r in sc.per_candidate] == [0.0, 1.0]
    assert sc.passed is True


def test_low_identity_emits_hint_and_fails(tmp_path, fake_embed):
    a = _png(tmp_path, "a.png")
    fake_embed["a.png"] = [0.0, 1.0, 0.0]
    ref = [1.0, 0.0, 0.0]  # orthogonal → identity 0.0 < floor
    sc = shot_scorecard(candidate_frames=[a], subject_ref_embedding=ref, identity_floor=0.2)
    assert sc.passed is False
    assert any("身份匹配偏低" in h for h in sc.hints)


def test_no_anchor_picks_first_and_passes(tmp_path, fake_embed):
    a, b = _png(tmp_path, "a.png"), _png(tmp_path, "b.png")
    sc = shot_scorecard(candidate_frames=[a, b], subject_ref_embedding=None)
    assert sc.best_index == 0
    assert sc.passed is True  # no anchor → accept first, no needless retry


def test_empty_candidates_raises():
    with pytest.raises(ValueError):
        shot_scorecard(candidate_frames=[], subject_ref_embedding=[1.0])


# 多区域 identity embedding(HEVI 路线图 Phase2 #34):全图/脸部区域两个向量各比
# 一次,identity 取较高值——不是真人脸检测,没法确定"这帧到底有没有露脸",两个
# 都比、取更像的那个是没有可靠判据时的稳妥退化。


@pytest.fixture
def fake_embed_by_kind(monkeypatch):
    """跟 fake_embed 不同:按 (文件名, kind) 两个维度查表,能模拟"全图不像但
    脸部区域像"这类只有多区域才能分辨的场景。"""
    table: dict[tuple[str, str], list[float]] = {}

    def _fake(*, image_path, kind="face"):
        return table[(Path(image_path).name, kind)]

    monkeypatch.setattr(sc_mod, "subject_embed", _fake)
    return table


def test_identity_combines_whole_and_face_takes_max(tmp_path, fake_embed_by_kind):
    """背影/侧身镜头:全图向量(kind=style)跟参考图很像(同场景/同衣着),但脸部
    区域裁到的是头发/背景,不像参考脸——combined 应该拿全图分,不能因为脸部区域
    凑巧算出低分就整体判定身份不符。"""
    a = _png(tmp_path, "a.png")
    fake_embed_by_kind[("a.png", "style")] = [1.0, 0.0]  # 全图:像
    fake_embed_by_kind[("a.png", "face")] = [0.0, 1.0]  # 脸部区域:不像(背影裁到头发)
    ref_whole = [1.0, 0.0]
    ref_face = [1.0, 0.0]  # 参考图的脸部区域本该也像"脸"(不影响本测试的关键对比)

    sc = shot_scorecard(
        candidate_frames=[a],
        subject_ref_embedding=ref_whole,
        subject_ref_embedding_face=ref_face,
        identity_floor=0.5,
    )
    assert sc.identity_score == pytest.approx(1.0)  # 取全图那份高分,不是脸部区域的 0
    assert sc.passed is True


def test_identity_combines_face_wins_when_whole_is_ambiguous(tmp_path, fake_embed_by_kind):
    """反过来:全图向量因为背景/服装接近但脸不是本人而模糊,脸部区域向量更准确
    地分辨出"不是这个人"——combined 该拿脸部区域的高分场景一样能正确识别出高分。"""
    a = _png(tmp_path, "a.png")
    fake_embed_by_kind[("a.png", "style")] = [0.6, 0.8]
    fake_embed_by_kind[("a.png", "face")] = [1.0, 0.0]
    ref_whole = [1.0, 0.0]
    ref_face = [1.0, 0.0]

    sc = shot_scorecard(
        candidate_frames=[a],
        subject_ref_embedding=ref_whole,
        subject_ref_embedding_face=ref_face,
    )
    assert sc.identity_score == pytest.approx(1.0)  # 脸部区域向量给出的满分被采纳


def test_identity_works_with_only_face_embedding(tmp_path, fake_embed_by_kind):
    """只传了脸部区域参考向量(没有全图向量)时也该正常工作,不要求两者都有。"""
    a = _png(tmp_path, "a.png")
    fake_embed_by_kind[("a.png", "style")] = [0.0, 0.0]  # 没有全图锚,这个不会被比对
    fake_embed_by_kind[("a.png", "face")] = [1.0, 0.0]
    sc = shot_scorecard(
        candidate_frames=[a], subject_ref_embedding=None, subject_ref_embedding_face=[1.0, 0.0]
    )
    assert sc.identity_score == pytest.approx(1.0)
    assert sc.passed is True


async def test_consistency_fn_matches_omodul_contract(tmp_path, fake_embed):
    a, b = _png(tmp_path, "a.png"), _png(tmp_path, "b.png")
    fake_embed["a.png"] = [1.0, 0.0]
    fake_embed["b.png"] = [0.2, 0.98]
    fn = make_scorecard_consistency_fn([1.0, 0.0])
    res = await fn(mllm=None, candidate_frames=[b, a], reference=None, criteria=None)
    assert res.best_frame.name == "a.png"  # identity winner
    assert isinstance(res.passed, bool)
    assert res.scorecard.best_index == 1


def test_frame_extract_passes_images_through(tmp_path):
    img = _png(tmp_path, "frame.png")
    out = extract_representative_frame(img, tmp_path / "out.png")
    assert out == img  # image input returned as-is, no decode


# shot_verdict 扩展(HEVI 路线图 Phase1):consistency_fn 打分即被 omodul 丢弃大半信息,
# 需要按 candidate 文件名反解 shot index、把完整 Scorecard 旁路收进 capture 字典。


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("shot_0000_v0.mp4", 0),
        ("shot_0007_v1.mp4", 7),
        ("shot_0123_v0.mp4", 123),
        ("not_a_shot_file.mp4", None),
    ],
)
def test_parse_shot_index(name, expected):
    assert _parse_shot_index(Path(f"/tmp/{name}")) == expected


async def test_consistency_fn_captures_scorecard_by_shot_index(tmp_path, fake_embed):
    # candidate 文件名必须匹配 omodul 的 shot_{idx:04d}_v{variant}.mp4 约定才能被反解。
    a = tmp_path / "shot_0003_v0.mp4"
    b = tmp_path / "shot_0003_v1.mp4"
    a.write_bytes(b"\x89PNG\r\n")
    b.write_bytes(b"\x89PNG\r\n")
    fake_embed["shot_0003_v0.mp4"] = [1.0, 0.0]
    fake_embed["shot_0003_v1.mp4"] = [0.2, 0.98]

    capture: dict[int, sc_mod.Scorecard] = {}
    fn = make_scorecard_consistency_fn([1.0, 0.0], capture=capture)
    res = await fn(mllm=None, candidate_frames=[a, b], reference=None, criteria=None)

    assert 3 in capture
    assert capture[3] is res.scorecard


async def test_consistency_fn_without_capture_is_noop(tmp_path, fake_embed):
    a = tmp_path / "shot_0001_v0.mp4"
    b = tmp_path / "shot_0001_v1.mp4"
    a.write_bytes(b"\x89PNG\r\n")
    b.write_bytes(b"\x89PNG\r\n")
    fake_embed["shot_0001_v0.mp4"] = [1.0, 0.0]
    fake_embed["shot_0001_v1.mp4"] = [0.2, 0.98]

    fn = make_scorecard_consistency_fn([1.0, 0.0])  # capture=None (default)
    res = await fn(mllm=None, candidate_frames=[a, b], reference=None, criteria=None)
    assert res.best_frame.name == "shot_0001_v0.mp4"  # capture=None 不影响正常选优逻辑


def test_coarse_diagnosis_flags_identity_mismatch_only():
    failed = sc_mod.Scorecard(best_frame=Path("x.mp4"), best_index=0, passed=False)
    passed = sc_mod.Scorecard(best_frame=Path("x.mp4"), best_index=0, passed=True)
    assert coarse_diagnosis(failed) == "参考图角色错配"
    assert coarse_diagnosis(passed) is None


# Tier1(HEVI 路线图 Phase1 #33):只在 Tier0(身份分)报警时才触发本地 VLM 质检。


class _FakeMLLM:
    """模拟 local_qwen_vl_adapter 的调用约定:await mllm(messages=..., image_paths=...)。"""

    def __init__(self, content: str):
        self.content = content
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {"content": self.content}


async def test_vlm_score_frame_returns_none_without_mllm(tmp_path):
    score, violations = await sc_mod._vlm_score_frame(tmp_path / "f.png", None)
    assert score is None
    assert violations == []


async def test_vlm_score_frame_parses_pass_and_fail():
    ok_mllm = _FakeMLLM('{"passes": true, "violations": []}')
    score, violations = await sc_mod._vlm_score_frame(Path("f.png"), ok_mllm)
    assert score == 1.0 and violations == []

    bad_mllm = _FakeMLLM('{"passes": false, "violations": ["手部畸变"]}')
    score, violations = await sc_mod._vlm_score_frame(Path("f.png"), bad_mllm)
    assert score == 0.3 and violations == ["手部畸变"]


async def test_vlm_score_frame_swallows_malformed_response():
    score, violations = await sc_mod._vlm_score_frame(Path("f.png"), _FakeMLLM("not json"))
    assert score is None
    assert violations == []


async def test_consistency_fn_triggers_vlm_only_when_identity_fails(tmp_path, fake_embed):
    a = _png(tmp_path, "a.png")
    fake_embed["a.png"] = [0.0, 1.0, 0.0]  # 跟 ref 正交 → identity 低,Tier0 报警
    mllm = _FakeMLLM('{"passes": false, "violations": ["肢体畸变"]}')

    fn = make_scorecard_consistency_fn([1.0, 0.0, 0.0], identity_floor=0.2)
    res = await fn(mllm=mllm, candidate_frames=[a], reference=None, criteria=None)

    assert res.passed is False
    assert len(mllm.calls) == 1  # Tier0 报警 → 真触发了 VLM
    assert res.scorecard.vlm_score == 0.3
    assert res.scorecard.vlm_violations == ["肢体畸变"]
    assert any("VLM 质检" in h for h in res.scorecard.hints)


async def test_consistency_fn_skips_vlm_when_identity_passes(tmp_path, fake_embed):
    a = _png(tmp_path, "a.png")
    fake_embed["a.png"] = [1.0, 0.0, 0.0]  # 跟 ref 一致 → identity 高,不报警
    mllm = _FakeMLLM('{"passes": false, "violations": ["不该被调用"]}')

    fn = make_scorecard_consistency_fn([1.0, 0.0, 0.0], identity_floor=0.2)
    res = await fn(mllm=mllm, candidate_frames=[a], reference=None, criteria=None)

    assert res.passed is True
    assert len(mllm.calls) == 0  # 没报警 → 不该花钱跑 VLM
    assert res.scorecard.vlm_score is None  # 没跑,不是 0


async def test_consistency_fn_skips_vlm_without_mllm_kwarg(tmp_path, fake_embed):
    a = _png(tmp_path, "a.png")
    fake_embed["a.png"] = [0.0, 1.0, 0.0]  # 报警,但这次没传 mllm

    fn = make_scorecard_consistency_fn([1.0, 0.0, 0.0], identity_floor=0.2)
    res = await fn(candidate_frames=[a], reference=None, criteria=None)

    assert res.passed is False
    assert res.scorecard.vlm_score is None


async def test_consistency_fn_respects_enable_vlm_tier1_false(tmp_path, fake_embed):
    a = _png(tmp_path, "a.png")
    fake_embed["a.png"] = [0.0, 1.0, 0.0]  # 报警
    mllm = _FakeMLLM('{"passes": false, "violations": ["不该被调用"]}')

    fn = make_scorecard_consistency_fn([1.0, 0.0, 0.0], identity_floor=0.2, enable_vlm_tier1=False)
    res = await fn(mllm=mllm, candidate_frames=[a], reference=None, criteria=None)

    assert len(mllm.calls) == 0
    assert res.scorecard.vlm_score is None


# ── check_relationship_consistency (SPEC-001 §5, Tier0 跨集关系一致性守护) ──

_CHARACTERS = [
    StoryCharacter(char_id="C001", name="王生", aliases=["王七"]),
    StoryCharacter(char_id="C002", name="师兄", aliases=[]),
]


def _enemies_relationship(evolution: list[dict] | None = None) -> StoryRelationship:
    return StoryRelationship(
        from_char="C001",
        to_char="C002",
        relation_type="仇敌",
        valence=-0.8,
        evolution=evolution or [],
    )


def test_relationship_consistency_flags_warm_address_for_enemies():
    result = check_relationship_consistency(
        dialogue_texts=["王生对师兄说:亲爱的,好久不见。"],
        relationships=[_enemies_relationship()],
        characters=_CHARACTERS,
        episode_event_ids=["E003"],
    )
    assert result["passed"] is False
    assert "C001->C002" in result["drifts"][0]


def test_relationship_consistency_passes_when_address_matches_valence():
    result = check_relationship_consistency(
        dialogue_texts=["王生怒视师兄:你这混账,休想再犯!"],
        relationships=[_enemies_relationship()],
        characters=_CHARACTERS,
        episode_event_ids=["E003"],
    )
    assert result["passed"] is True
    assert result["drifts"] == []


def test_relationship_consistency_ignores_change_happening_this_episode():
    """关系突变的 evolution 记录落在本集自己的事件上——那是剧情本身,不是漂移。"""
    rel = _enemies_relationship(
        evolution=[{"event_id": "E002", "relation_type": "和解", "valence": 0.6}]
    )
    result = check_relationship_consistency(
        dialogue_texts=["王生对师兄说:亲爱的,好久不见。"],
        relationships=[rel],
        characters=_CHARACTERS,
        episode_event_ids=["E001", "E002"],
    )
    assert result["passed"] is True


def test_relationship_consistency_uses_evolution_state_from_earlier_episode():
    """关系已在更早的集里(E002)和解,本集(E005)台词延续友好称呼——不该报漂移。"""
    rel = _enemies_relationship(
        evolution=[{"event_id": "E002", "relation_type": "和解", "valence": 0.6}]
    )
    result = check_relationship_consistency(
        dialogue_texts=["王生对师兄说:亲爱的,好久不见。"],
        relationships=[rel],
        characters=_CHARACTERS,
        episode_event_ids=["E005"],
    )
    assert result["passed"] is True


def test_relationship_consistency_skips_when_characters_do_not_co_occur():
    result = check_relationship_consistency(
        dialogue_texts=["王生独自赶路,心中忐忑。"],
        relationships=[_enemies_relationship()],
        characters=_CHARACTERS,
        episode_event_ids=["E001"],
    )
    assert result["passed"] is True
    assert result["drifts"] == []
