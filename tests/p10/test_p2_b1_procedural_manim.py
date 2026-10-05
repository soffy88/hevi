"""P2-B1 验收:ProceduralAcquirer + Manim 把 B0 的语义带进真实 acquisition。

链路(生产与测试走**同一段** p0 代码 `_resolve_with_acquisition`):

```text
unresolved requirement → ProceduralAcquirer.propose() → Manim → real artifact
→ substitute_kind → validate_media → check_compatibility → candidate
→ resolve() → ShotResolution.selected
```

真 Manim 渲染(0.2s/片 @ low quality)、真 `validate_media`、真
`check_compatibility`、真 canonical scorer + selector。

三条必须证明的语义(来自 B0,这里是它们第一次在生产 acquisition 上被检验):

1. ``forbidden_substitutes=["generic_stars"]`` + 渲出通用星空 → **rejected**
2. ``forbidden_substitutes=["title_card_only"]`` + 渲出解释性示意画面 → **accepted**
3. 缺 ``substitute_kind`` → **rejected**
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hevi.creative.autonomous.acquire_procedural import (
    PROCEDURAL_MOTION_GRAPHICS,
    ProceduralAcquirer,
    ProceduralRecipe,
    slugify,
)
from hevi.creative.autonomous.procedural_manim import (
    DEFAULT_PROCEDURAL_RECIPES,
    EXPLANATORY_MOTION_GRAPHICS,
    GENERIC_STARS,
    ManimBackend,
)
from hevi.creative.autonomous.selection import (
    GenerationNotAdmittedError,
    admit_generation,
)
from hevi.production.p0_pipeline import _resolve_with_acquisition
from hevi.production.p7.asset_contract import AssetSemanticRole, MediaType
from hevi.production.p7.asset_requirement import AssetRequirement

REPO = Path(__file__).resolve().parents[2]
PROCEDURAL_SRC = REPO / "hevi" / "creative" / "autonomous" / "acquire_procedural.py"
SHOT_ID = "prod-1:shot-0001"

#: 真 manim 每片 ~0.2s;整文件仍需渲染多片,故 module 级只渲一次并复用。
BACKEND = ManimBackend()


def _req(forbidden: tuple[str, ...] = (), *, query: str = "accretion disk",
         duration: str = "2.0") -> AssetRequirement:
    constraints: list[tuple[str, str]] = [("query", query), ("duration", duration)]
    if forbidden:
        constraints.append(("forbidden_substitutes", ",".join(forbidden)))
    return AssetRequirement(media_type=MediaType.VIDEO,
                            semantic_role=AssetSemanticRole.SCENE,
                            constraints=tuple(constraints))


def _acquirer(tmp_path: Path, recipes=DEFAULT_PROCEDURAL_RECIPES) -> ProceduralAcquirer:
    return ProceduralAcquirer(BACKEND, recipes, cache_dir=tmp_path / "cache")


async def _run(acquirer_chain, requirement, candidates=None):
    """接受单个 acquirer、`None`,或有序 tuple —— 与生产同一段代码。"""
    if acquirer_chain is None:
        chain: tuple = ()
    elif isinstance(acquirer_chain, tuple):
        chain = acquirer_chain
    else:
        chain = (acquirer_chain,)
    return await _resolve_with_acquisition(SHOT_ID, requirement,
                                          list(candidates or []), chain)


def _kinds(normalized) -> set[str]:
    out = set()
    for item in normalized:
        for outcome in item.compatibility.outcomes:
            if outcome.key == "forbidden_substitutes":
                out.add(str(outcome.observed))
    return out


# ══ 证明 1:forbidden=["generic_stars"] + 渲出通用星空 → rejected ══
async def test_p2b1_01_generic_stars_rejected_when_forbidden(tmp_path):
    """禁止星空 → 星空**不得**进入候选池;另一条配方不受连累。"""
    acquirer = _acquirer(tmp_path)
    requirement = _req(("generic_stars",))

    proposed = await acquirer.propose(requirement)

    assert proposed, "解释性配方仍应可用 —— 禁止星空不该连累它"
    kinds = _kinds(proposed)
    assert "generic_stars" not in kinds, (
        f"被禁止的替代物不得进入候选池,但 kinds={kinds}")
    assert kinds == {"motion_graphics"}


async def test_p2b1_01_generic_stars_is_blocked_at_the_seam(tmp_path):
    """星空被拒的**判定**发生在 canonical seam,不是被某个过滤列表拦掉的。

    直接渲星空 + `normalize_local_asset` → `check_compatibility` 必须判 blocked。
    证明它不是「恰好没进 propose」,而是明确被拒。
    """
    from hevi.creative.autonomous.acquire import normalize_local_asset

    acquirer = _acquirer(tmp_path)
    requirement = _req(("generic_stars",))
    rendered = await acquirer._backend.render(
        source_code=str(GENERIC_STARS.build_source(requirement, "stars")),
        output_path=tmp_path / "stars.mp4", duration_s=2.0,
        width=640, height=360, fps=15)
    assert Path(rendered).is_file(), "必须是真实落盘的画面"

    normalized = normalize_local_asset(
        requirement, Path(rendered), source="manim:generic_stars",
        license_name="HEVI-GENERATED",
        observed_extra={"substitute_kind": "generic_stars"})

    assert normalized.compatibility.blocked_keys == ("forbidden_substitutes",)
    assert normalized.compatibility.compatible is False
    assert normalized.usable is False
    assert normalized.evidence.status.name == "BLOCKED"
    # 文件本身是好的 —— 被拒是因为**种类**,不是因为渲染失败
    assert "probe_valid=True" in normalized.evidence.validation


async def test_p2b1_01_rejected_star_never_reaches_resolution(tmp_path):
    """只有星空配方 + 禁止星空 → 整条链 fail closed,不得出现 selected。"""
    acquirer = _acquirer(tmp_path, recipes=(GENERIC_STARS,))
    requirement = _req(("generic_stars",))

    preparation, resolution, note = await _run(acquirer, requirement)

    assert note["acquired"] == 0, "被禁止的素材不得进入候选池"
    assert note["reason"] == "ACQUIRED_NOTHING_USABLE"
    assert resolution.unresolved_requirement_ids == (requirement.requirement_id,)
    assert resolution.selected_requirement_ids == ()
    assert resolution.ready_for_generation is False
    with pytest.raises(GenerationNotAdmittedError):
        admit_generation(resolution, preparation.candidates)


# ══ 证明 2:forbidden=["title_card_only"] + 解释性示意画面 → accepted ══
async def test_p2b1_02_explanatory_motion_graphics_accepted_when_not_forbidden(tmp_path):
    acquirer = _acquirer(tmp_path)
    requirement = _req(("title_card_only",))

    proposed = await acquirer.propose(requirement)

    explanatory = [n for n in proposed
                   if "motion_graphics" in {str(o.observed)
                                            for o in n.compatibility.outcomes}]
    assert explanatory, "解释性配方必须真实产出"
    for item in explanatory:
        assert item.compatibility.blocked_keys == ()
        assert item.compatibility.undecidable_keys == ()
        assert item.compatibility.compatible is True
        assert item.usable is True
        assert Path(item.candidate.asset_ref).is_file(), "必须是真实落盘的文件"


async def test_p2b1_02_accepted_reaches_shot_resolution_selected(tmp_path):
    """完整闭环:accepted 的候选最终由 canonical scorer → selector 选中。"""
    acquirer = _acquirer(tmp_path, recipes=(EXPLANATORY_MOTION_GRAPHICS,))
    requirement = _req(("title_card_only",), query="black hole accretion disk")

    preparation, resolution, note = await _run(acquirer, requirement)

    assert note["acquired"] == 1
    assert note["reason"] == "RE_RESOLVED"
    assert resolution.unresolved_requirement_ids == ()
    assert resolution.selected_requirement_ids == (requirement.requirement_id,)
    assert resolution.ready_for_generation is True

    chosen = admit_generation(resolution, preparation.candidates)
    assert chosen.state.name == "SELECTED"
    assert Path(chosen.asset_ref).is_file()
    assert chosen.scored_by, "canonical scorer 必须盖章,否则 selector 不认"


# ══ 证明 3:缺 substitute_kind → rejected ══
async def test_p2b1_03_missing_substitute_kind_is_rejected(tmp_path):
    """B0 的 fail-closed 在真实 acquisition 上生效:不自报就进不了候选。"""
    acquirer = _acquirer(tmp_path)
    requirement = _req(("generic_stars",))

    # 绕过自报:直接把 observed_extra 抽掉,模拟「Acquirer 忘了申报」
    from hevi.creative.autonomous import acquire_procedural as procedural_module

    original = procedural_module.normalize_local_asset

    def without_self_report(*args, **kwargs):
        kwargs.pop("observed_extra", None)
        return original(*args, **kwargs)

    procedural_module.normalize_local_asset = without_self_report
    try:
        proposed = await acquirer.propose(requirement)
        _, resolution, _ = await _run(acquirer, requirement)
    finally:
        procedural_module.normalize_local_asset = original

    assert proposed == (), "不自报 substitute_kind 的素材不得成为候选"
    assert resolution.ready_for_generation is False, (
        "缺自报 → 不可判定 → 全链 fail closed")
    assert resolution.unresolved_requirement_ids == (requirement.requirement_id,)


async def test_p2b1_03_undecidable_is_distinct_from_blocked(tmp_path):
    """缺自报 = 不可判定,不是「阻塞」—— 但 compatible 同为 False。"""
    acquirer = _acquirer(tmp_path)
    requirement = _req(("generic_stars",))
    from hevi.creative.autonomous.acquire import normalize_local_asset

    rendered = await acquirer._backend.render(
        source_code=str(EXPLANATORY_MOTION_GRAPHICS.build_source(requirement, "x")),
        output_path=tmp_path / "raw.mp4", duration_s=2.0, width=640, height=360, fps=15)

    silent = normalize_local_asset(requirement, Path(rendered), license_name="X")
    assert silent.compatibility.undecidable_keys == ("forbidden_substitutes",)
    assert silent.compatibility.blocked_keys == ()
    assert silent.compatibility.compatible is False


# ══ substitute_kind 诚实性 ══
async def test_p2b1_04_substitute_kind_is_independent_of_the_forbidden_list(tmp_path):
    """**核心防作弊**:同一 recipe,无论 requirement 禁什么,kind 恒定。

    否则 acquirer 就成了「看约束挑标签」的角色,自己给自己发通行证。

    在 seam 上逐配方验证(`propose` 会过滤掉被禁的候选,看不到它们)。
    """
    from hevi.creative.autonomous.acquire import normalize_local_asset

    acquirer = _acquirer(tmp_path)
    for recipe, expected_kind in ((EXPLANATORY_MOTION_GRAPHICS, "motion_graphics"),
                                 (GENERIC_STARS, "generic_stars")):
        rendered = await acquirer._backend.render(
            source_code=str(recipe.build_source(_req(), "probe")),
            output_path=tmp_path / f"{recipe.recipe_id}.mp4",
            duration_s=2.0, width=640, height=360, fps=15)
        seen = set()
        for forbidden in (("generic_stars",), ("motion_graphics",),
                          ("generic_stars", "motion_graphics"), ("title_card_only",),
                          ("generic_stars", "title_card_only", "large_explanatory_text")):
            normalized = normalize_local_asset(
                _req(forbidden), Path(rendered), source=f"manim:{recipe.recipe_id}",
                license_name="HEVI-GENERATED",
                observed_extra={"substitute_kind": recipe.substitute_kind})
            observed = [str(o.observed) for o in normalized.compatibility.outcomes
                        if o.key == "forbidden_substitutes"]
            seen.update(observed or ["<absent>"])
        assert seen == {expected_kind}, (
            f"{recipe.recipe_id}: substitute_kind 随禁止清单变化了 → {seen}")


def test_p2b1_04_recipe_source_builder_cannot_read_the_forbidden_list():
    """配方源码生成器**不得**读 requirement 的禁止清单。"""
    for recipe in (EXPLANATORY_MOTION_GRAPHICS, GENERIC_STARS):
        target = recipe.build_source
        assert target is not None
        src = __import__("inspect").getsource(target)
        assert "forbidden_substitutes" not in src, (
            f"RECIPE_GAMES_THE_CONSTRAINT: {recipe.recipe_id} 的源码生成器读了禁止清单")


# ══ 能力边界(只支持一种能力) ══
def test_p2b1_05_only_motion_graphics_capability():
    assert PROCEDURAL_MOTION_GRAPHICS == "motion_graphics"
    acquirer = ProceduralAcquirer(BACKEND, DEFAULT_PROCEDURAL_RECIPES)
    assert acquirer.supports("motion_graphics") is True
    for other in ("t2v", "i2v", "explainer", "captions", "html_render", ""):
        assert acquirer.supports(other) is False, f"第一版不得支持 {other!r}"


async def test_p2b1_05_unsupported_capability_fails_closed_at_construction(tmp_path):
    """第一版只支持一种能力 —— 声明别的一律构造失败,不静默降级。"""
    for capability in ("blender", "t2v", "explainer", "motion_graphics_3d", ""):
        with pytest.raises(ValueError, match="PROCEDURAL_CAPABILITY_UNSUPPORTED"):
            ProceduralAcquirer(BACKEND, DEFAULT_PROCEDURAL_RECIPES, capability=capability)


def test_p2b1_05_provider_policy_mode_matches_manim_limits():
    """mode 必须对上 `PROVIDER_LIMITS.modes` —— 实测 t2v 会被拒。"""
    from hevi.provider_policy.policy import PROVIDER_LIMITS

    policy = ProceduralAcquirer(BACKEND, DEFAULT_PROCEDURAL_RECIPES).provider_policy()
    limits = PROVIDER_LIMITS["manim"]
    assert policy.mode in limits.modes, (
        f"mode={policy.mode!r} 不在 manim 的 modes={set(limits.modes)} —— policy 会拒")


def test_p2b1_05_reuses_the_existing_global_catalogue():
    """`manim` 已在册;重复 register 会抛 DUPLICATE,所以不得新建 catalogue。"""
    from hevi.providers.facts import PROVIDER_CATALOGUE

    catalogue = ProceduralAcquirer(BACKEND, DEFAULT_PROCEDURAL_RECIPES).provider_catalogue()
    assert catalogue is PROVIDER_CATALOGUE
    assert catalogue.has("manim")


# ══ Acquirer 不选择 ══
def test_p2b1_06_procedural_module_defines_no_selection():
    src = PROCEDURAL_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"max", "min", "sorted", "nlargest", "nsmallest"}, (
                f"ACQUIRER_SELECTS: {node.func.id}")
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"sort", "pop", "remove"}, f"ACQUIRER_SELECTS: {node.attr}"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name.lower()
            for token in ("select", "pick", "best", "rank", "top", "choose", "score",
                          "fitness", "relevan"):
                assert token not in name, f"ACQUIRER_SELECTS: {node.name}"


def test_p2b1_06_is_not_an_acquirer_protocol_impl():
    from hevi.creative.autonomous.resolver import Acquirer

    assert not hasattr(ProceduralAcquirer, "acquire"), (
        "ProceduralAcquirer 不应实现 Acquirer.acquire —— 单值返回本身就是选择")
    assert "class ProceduralAcquirer(Acquirer)" not in PROCEDURAL_SRC.read_text(
        encoding="utf-8")
    assert Acquirer is not None


async def test_p2b1_06_selection_comes_from_canonical_scorer_not_recipe_order(tmp_path):
    """两条配方都合规时,谁被用由 scorer 决定,不是配方顺序。"""
    acquirer = _acquirer(tmp_path)
    requirement = _req(("title_card_only",), query="black hole accretion disk")

    preparation, resolution, _ = await _run(acquirer, requirement)
    assert len(preparation.candidates) == 2
    chosen = admit_generation(resolution, preparation.candidates)
    assert chosen.state.name == "SELECTED"
    others = [c for c in preparation.candidates if c is not chosen]
    assert len(others) == 1
    assert others[0].state.name == "REJECTED"
    assert others[0].reason, "被拒必须留下理由"


# ══ 有序链 ══
async def test_p2b1_07_chain_stops_when_canonical_says_resolved(tmp_path):
    """第一个 acquirer 满足后,第二个**不得**被调用 —— 由 resolution 决定。"""
    first = _acquirer(tmp_path, recipes=(EXPLANATORY_MOTION_GRAPHICS,))
    second = _acquirer(tmp_path / "second", recipes=(GENERIC_STARS,))

    _, resolution, note = await _run((first, second), _req(("title_card_only",)))

    assert resolution.ready_for_generation is True
    assert note["rounds"] == 1, "只跑了一轮"
    assert [t["provider_id"] for t in note["tiers"]] == ["manim"], "第二个不该被调用"


async def test_p2b1_07_chain_falls_through_when_first_yields_nothing(tmp_path):
    """第一个产不出可用候选 → 继续下一个。"""
    blocked = _acquirer(tmp_path, recipes=(GENERIC_STARS,))
    good = _acquirer(tmp_path / "second", recipes=(EXPLANATORY_MOTION_GRAPHICS,))

    _, resolution, note = await _run((blocked, good), _req(("generic_stars",)))

    assert note["tiers"] == [
        {"provider_id": "manim", "acquired": 0},
        {"provider_id": "manim", "acquired": 1},
    ], "两轮都跑了,第一个 0 第二个 1"
    assert resolution.ready_for_generation is True


async def test_p2b1_07_empty_chain_fails_closed(tmp_path):
    _, resolution, note = await _run((), _req())
    assert note["reason"] == "NO_ACQUIRER_CONFIGURED"
    assert resolution.ready_for_generation is False


# ══ recipe 取值校验 ══
@pytest.mark.parametrize("kind", ["", "Motion_Graphics", "motion graphics", "motion-graphics"])
def test_p2b1_08_recipe_rejects_malformed_substitute_kind(kind):
    with pytest.raises(ValueError, match="SUBSTITUTE_KIND|PROCEDURAL_RECIPE_WITHOUT"):
        ProceduralRecipe(recipe_id="r", substitute_kind=kind,
                         build_source=lambda rq, s: "")


def test_p2b1_08_slugify_is_filename_safe():
    assert slugify("Black Hole: Accretion Disk!") == "black-hole-accretion-disk"
    assert slugify("???") == ""