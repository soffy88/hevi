"""P2-A 验收:Stock acquisition → 重新 resolve → admit 的真实闭环。

真媒体(ffmpeg 现场生成)、真 `validate_media`、真 `check_compatibility`、
真 canonical scorer + selector。**只**替换网络边界(`StockSource`)——
那是 provider 层,不属于本包要验证的链路。

纪律(见 `hevi/creative/autonomous/acquire_stock.py`):
- Acquirer **不宣布成功**,只产出候选;
- 「拿到文件」≠「可以生成」,必须重新 resolve;
- 最终选择只来自 `scorer → selector → ShotResolution`。
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from hevi.creative.autonomous.acquire_stock import (
    StockAssetAcquirer,
    StockItem,
    default_cache_dir,
    materialize_name,
)
from hevi.creative.autonomous.selection import (
    GenerationNotAdmittedError,
    admit_generation,
)
from hevi.production.p0_pipeline import (
    P0_ASSET_DOMAIN,
    P0_SCORER_ID,
    _requirement_for,
    _resolve_with_acquisition,
)
from hevi.production.p7.asset_contract import (
    AssetSemanticRole,
    AssetStatus,
    MediaType,
)
from hevi.production.p7.asset_requirement import AssetRequirement
from hevi.production.shot_readiness import (
    REVIEW_CONFIDENCE_FLOOR,
    AssetCandidateState,
    ShotPreparation,
)
from hevi.providers.facts import ProviderLicenseClass

REPO = Path(__file__).resolve().parents[2]
ACQUIRE_STOCK_SRC = REPO / "hevi" / "creative" / "autonomous" / "acquire_stock.py"
P0_SRC = REPO / "hevi" / "production" / "p0_pipeline.py"

SHOT_ID = "prod-1:shot-0001"


# ── 真媒体(follow tests/p10/test_s2_acquisition.py 的做法:不 mock 探测链)──
def _video(path: Path, *, seconds: float = 4.0, w: int = 1080, h: int = 1920) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc2=size={w}x{h}:rate=24:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, timeout=180, capture_output=True,
    )
    assert path.exists() and path.stat().st_size > 0
    return path


class LocalStockSource:
    """把本地目录当 stock provider。唯一被替换的是网络边界。

    刻意**不**实现排序:返回顺序由调用方决定,便于测试断言
    「选择不是 acquirer 做的」。
    """

    provider_id = "test.stock.local"

    def __init__(self, items: list[StockItem], payloads: dict[str, Path]) -> None:
        self._items = items
        self._payloads = payloads
        self.search_calls: list[tuple[str, str, int]] = []

    async def search(self, query: str, *, media_type: str,
                     limit: int) -> tuple[StockItem, ...]:
        self.search_calls.append((query, media_type, limit))
        return tuple(self._items[:limit])

    async def fetch(self, item: StockItem, destination: Path) -> Path:
        payload = self._payloads[item.external_id]
        destination.write_bytes(payload.read_bytes())
        return destination


def _requirement(query: str = "black hole accretion disk") -> AssetRequirement:
    return AssetRequirement(
        media_type=MediaType.VIDEO,
        semantic_role=AssetSemanticRole.SCENE,
        constraints=(("query", query),),
    )


def _item(external_id: str, title: str, payload: Path, *, license_name: str = "CC0-1.0",
          media_type: str = "VIDEO") -> StockItem:
    return StockItem(external_id=external_id, url=f"https://stock.invalid/{external_id}.mp4",
                     title=title, media_type=media_type, license=license_name)


def _acquirer(tmp_path: Path, items: list[StockItem],
              payloads: dict[str, Path]) -> StockAssetAcquirer:
    return StockAssetAcquirer(LocalStockSource(items, payloads),
                              cache_dir=tmp_path / "cache")


async def _run(acquirer, requirement, candidates=None):
    """生产同款闭环。测试与 `run_p0_production` 调的是同一个函数。"""
    return await _resolve_with_acquisition(SHOT_ID, requirement, list(candidates or []),
                                          acquirer)


# ══ P2-A-01 stock requirement → acquired asset ══
async def test_p2a_01_unresolved_requirement_is_acquired_and_reselected(tmp_path):
    payload = _video(tmp_path / "src.mp4", seconds=5.0)
    item = _item("a1", "black hole accretion disk visualization", payload)
    acquirer = _acquirer(tmp_path, [item], {"a1": payload})
    requirement = _requirement()

    preparation, resolution, note = await _run(acquirer, requirement)

    assert note["attempted"] is True
    assert note["acquired"] == 1
    assert resolution.unresolved_requirement_ids == ()
    assert resolution.selected_requirement_ids == (requirement.requirement_id,)
    assert resolution.ready_for_generation is True

    acquired = [c for c in preparation.candidates if c.asset_ref.startswith(str(tmp_path))]
    assert len(acquired) == 1, "acquirer 必须真的物化出一个本地文件"
    assert Path(acquired[0].asset_ref).is_file()
    assert acquired[0].asset_ref.startswith(str(acquirer.cache_dir))
    # provenance 是 canonical scorer 盖的,不是 acquirer 自封
    assert acquired[0].scored_by == P0_SCORER_ID
    assert acquired[0].confidence >= REVIEW_CONFIDENCE_FLOOR


# ══ P2-A-02 acquired asset 不满足 requirement → REJECTED ══
async def test_p2a_02_incompatible_acquisition_never_becomes_selected(tmp_path):
    # 要求至少 8s,素材只有 2s → check_compatibility 判 duration 不满足
    payload = _video(tmp_path / "short.mp4", seconds=2.0)
    item = _item("a1", "black hole accretion disk", payload)
    acquirer = _acquirer(tmp_path, [item], {"a1": payload})
    requirement = AssetRequirement(
        media_type=MediaType.VIDEO, semantic_role=AssetSemanticRole.SCENE,
        constraints=(("query", "black hole accretion disk"), ("duration", "8.0")))

    _, resolution, note = await _run(acquirer, requirement)

    assert note["attempted"] is True
    assert note["acquired"] == 0, "不兼容的 acquisition 不得进入候选池"
    assert resolution.unresolved_requirement_ids == (requirement.requirement_id,)
    assert resolution.ready_for_generation is False
    with pytest.raises(GenerationNotAdmittedError):
        admit_generation(resolution, [])


async def test_p2a_02_undecidable_constraint_blocks(tmp_path):
    """undecidable(观察不到)不等于通过 —— p7 的 compatible 定义要求两者都干净。"""
    payload = _video(tmp_path / "src.mp4", seconds=5.0)
    item = _item("a1", "black hole accretion disk", payload)
    acquirer = _acquirer(tmp_path, [item], {"a1": payload})
    requirement = AssetRequirement(
        media_type=MediaType.VIDEO, semantic_role=AssetSemanticRole.SCENE,
        constraints=(("query", "black hole"), ("period", "1990s")))

    _, resolution, note = await _run(acquirer, requirement)

    assert note["acquired"] == 0
    assert resolution.ready_for_generation is False


# ══ P2-A-03 provider failure → fail closed ══
class _ExplodingSource(LocalStockSource):
    async def search(self, query: str, *, media_type: str,
                     limit: int) -> tuple[StockItem, ...]:
        raise TimeoutError("provider down")


async def test_p2a_03_provider_failure_fails_closed(tmp_path):
    payload = _video(tmp_path / "src.mp4", seconds=5.0)
    item = _item("a1", "black hole accretion disk", payload)
    acquirer = StockAssetAcquirer(
        _ExplodingSource([item], {"a1": payload}), cache_dir=tmp_path / "cache")
    requirement = _requirement()

    _, resolution, note = await _run(acquirer, requirement)

    assert note["attempted"] is True
    assert note["acquired"] == 0
    assert resolution.unresolved_requirement_ids == (requirement.requirement_id,)
    assert resolution.ready_for_generation is False


class _FailingFetchSource(LocalStockSource):
    async def fetch(self, item: StockItem, destination: Path) -> Path:
        raise ConnectionResetError("download died")


async def test_p2a_03_fetch_failure_fails_closed(tmp_path):
    payload = _video(tmp_path / "src.mp4", seconds=5.0)
    item = _item("a1", "black hole accretion disk", payload)
    acquirer = StockAssetAcquirer(
        _FailingFetchSource([item], {"a1": payload}), cache_dir=tmp_path / "cache")

    _, resolution, note = await _run(acquirer, _requirement())

    assert note["acquired"] == 0
    assert resolution.ready_for_generation is False


class _UndeclaredAcquirer(StockAssetAcquirer):
    """provider 事实从未被声明(catalogue 为空)→ policy 判 unknown_provider。

    复现「provider 没登记」这条真实 fail-closed 分支,不改全局 _SEED。
    """

    def provider_catalogue(self):
        from hevi.providers.facts import ProviderCatalogue

        return ProviderCatalogue(())


async def test_p2a_03_no_provider_selected_fails_closed(tmp_path):
    """provider policy 选不出 provider → 不得退回到「随便拿一个」。"""
    payload = _video(tmp_path / "src.mp4", seconds=5.0)
    item = _item("a1", "black hole accretion disk", payload)
    acquirer = _UndeclaredAcquirer(LocalStockSource([item], {"a1": payload}),
                                   cache_dir=tmp_path / "cache")
    assert acquirer.provider_catalogue().has(acquirer.provider_id) is False

    _, resolution, note = await _run(acquirer, _requirement())

    assert note["attempted"] is True
    assert note["acquired"] == 0
    assert resolution.ready_for_generation is False


# ══ P2-A-04 license 缺失 → 不得 AVAILABLE ══
async def test_p2a_04_missing_license_never_becomes_available(tmp_path):
    payload = _video(tmp_path / "src.mp4", seconds=5.0)
    item = _item("a1", "black hole accretion disk", payload, license_name="")
    acquirer = _acquirer(tmp_path, [item], {"a1": payload})

    proposed = await acquirer.propose(_requirement())

    assert proposed == (), "无 license 的素材不得成为候选"
    # 直接验证 p7 的硬规则确实在起作用(而不是恰好别的条件挡住了)
    with pytest.raises(ValueError, match="AVAILABLE_ASSET_WITHOUT_LICENSE"):
        from hevi.production.p7.evidence import AssetEvidence
        AssetEvidence(asset_id="x", source="stock", status=AssetStatus.AVAILABLE,
                      license="")


async def test_p2a_04_declared_license_class_is_provider_level_fact(tmp_path):
    """provider 级声明与 per-asset 声明是两层,不可互相替代。"""
    payload = _video(tmp_path / "src.mp4", seconds=5.0)
    item = _item("a1", "black hole accretion disk", payload)
    acquirer = StockAssetAcquirer(
        LocalStockSource([item], {"a1": payload}), cache_dir=tmp_path / "cache",
        declared_license_class=ProviderLicenseClass.UNKNOWN)
    assert acquirer.provider_profile().license_class is ProviderLicenseClass.UNKNOWN
    # per-asset license 仍然生效,provider 级 UNKNOWN 不影响 propose
    assert len(await acquirer.propose(_requirement())) == 1


# ══ P2-A-05 invalid media → 不得进入 resolution ══
async def test_p2a_05_invalid_media_never_enters_resolution(tmp_path):
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"this is not a video, ffprobe will reject it")
    item = _item("a1", "black hole accretion disk", corrupt)
    acquirer = _acquirer(tmp_path, [item], {"a1": corrupt})

    proposed = await acquirer.propose(_requirement())

    assert proposed == ()
    _, resolution, note = await _run(acquirer, _requirement())
    assert note["acquired"] == 0
    assert resolution.ready_for_generation is False


# ══ P2-A-06 acquisition 后重新 resolve ══
async def test_p2a_06_re_resolve_is_what_makes_it_selected(tmp_path):
    """关键回归:第一轮 unresolved;acquire 之后必须**重新** resolve 才 selected。

    如果实现偷懒直接用「刚拿到的文件」,那么 `state` 里的 resolution 就不会
    记录这次 re-resolve —— 本测试通过比较两次 resolve 的 shot_id/selected 来钉住。
    """
    payload = _video(tmp_path / "src.mp4", seconds=5.0)
    item = _item("a1", "black hole accretion disk", payload)
    acquirer = _acquirer(tmp_path, [item], {"a1": payload})
    requirement = _requirement()

    # 第一轮:零候选 → 必须 unresolved(不是「安静缺席」)
    # 第一轮:无 acquirer → unresolved(不是「安静缺席」,也不是「悄悄生成」)
    first_prep, first, note0 = await _run(None, requirement)
    assert note0["attempted"] is True and note0["reason"] == "NO_ACQUIRER_CONFIGURED"
    assert first.selected_requirement_ids == ()
    assert first.unresolved_requirement_ids == (requirement.requirement_id,)

    # 第二轮:带上候选 → 同一段代码,selected
    second_prep, second, note = await _run(acquirer, requirement)
    assert note["reason"] == "RE_RESOLVED"
    assert second.selected_requirement_ids == (requirement.requirement_id,)
    assert first_prep.shot_id == second_prep.shot_id == SHOT_ID
    assert second.selected_requirement_ids != first.selected_requirement_ids


async def test_p2a_06_zero_candidate_requirement_reports_unresolved():
    """`required_requirement_ids` 缺席时零候选会安静缺席 —— 那就是没有 fallback 输入。"""
    requirement = _requirement()
    empty = ShotPreparation(shot_id=SHOT_ID, candidates=[], required_asset_refs=[])
    from hevi.creative.autonomous.identity import RequirementBindingSet
    from hevi.creative.autonomous.selection import resolve

    without = resolve(empty, domain=P0_ASSET_DOMAIN,
                      scorer_registry={P0_SCORER_ID: _noop_scorer()},
                      bindings=RequirementBindingSet(()))
    with_ = resolve(empty, domain=P0_ASSET_DOMAIN,
                    scorer_registry={P0_SCORER_ID: _noop_scorer()},
                    bindings=RequirementBindingSet(()),
                    required_requirement_ids=(requirement.requirement_id,))
    assert without.unresolved_requirement_ids == ()
    assert with_.unresolved_requirement_ids == (requirement.requirement_id,)
    assert without.ready_for_generation is False


def _noop_scorer():
    from hevi.production.p0_pipeline import P0_ScienceRelevanceScorer

    return P0_ScienceRelevanceScorer()


# ══ P2-A-07 selected asset 最终来自 ShotResolution ══
async def test_p2a_07_final_asset_comes_from_resolution_not_from_acquirer(tmp_path):
    """两条都合规的素材 → 谁被用由 scorer + selector 决定,不是 acquirer 的顺序。"""
    strong = _video(tmp_path / "accretion.mp4", seconds=5.0)
    weak = _video(tmp_path / "orrery.mp4", seconds=5.0)
    items = [_item("a-strong", "black hole accretion disk", strong),
             _item("a-weak", "star orbit visualization", weak)]
    acquirer = _acquirer(tmp_path, items, {"a-strong": strong, "a-weak": weak})

    proposed = await acquirer.propose(_requirement())
    assert len(proposed) == 2, "acquirer 必须把两条都交上来"

    preparation, resolution, _ = await _run(acquirer, _requirement())
    chosen = admit_generation(resolution, preparation.candidates)
    assert chosen.state is AssetCandidateState.SELECTED
    assert "accretion" in chosen.asset_ref, "canonical scorer 应选相关性更高的那条"
    # 另一条被 canonical selector 标 REJECTED,不是被 acquirer 丢掉
    other = [c for c in preparation.candidates if c is not chosen]
    assert all(c.state is AssetCandidateState.REJECTED for c in other)
    assert all(c.reason for c in other), "拒绝必须留下理由"


# ══ P2-A-08 generation 只能消费 admit_generation() ══
def test_p2a_08_production_gate_reads_resolution_and_admit():
    """generation 只能消费 admit_generation();acquisition 结果不得直通生成。"""
    src = P0_SRC.read_text(encoding="utf-8")
    assert "admit_generation(resolution, preparation.candidates)" in src
    assert "ready_for_generation" in src
    assert "_resolve_with_acquisition(" in src, "生产必须走 P2-A 闭环"
    # 闭环内部:拿到 acquired 之后必须重新 resolve,不能直接返回
    seam = src[src.index("async def _resolve_with_acquisition"):
               src.index("def _shot_preparation")]
    assert seam.count("_resolve_shot(") == 2, "闭环必须 resolve 两次(初次 + re-resolve)"
    assert "_resolve_shot(preparation, requirement)" in seam
    # gate 只记录,不决定
    assert "if not resolution.ready_for_generation:" in src


# ══ Invariant:Acquirer NEVER selects the final production asset ══
def test_invariant_acquirer_module_defines_no_selection():
    """AST 守卫:`acquire_stock.py` 不得出现任何挑选/排序/评分形态。"""
    src = ACQUIRE_STOCK_SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned_calls = {"max", "min", "sorted", "nlargest", "nsmallest"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in banned_calls, (
                f"ACQUIRER_SELECTS: acquire_stock.py 不得调用 {node.func.id}")
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"sort", "pop", "remove"}, (
                f"ACQUIRER_MUTATES_ORDER: {node.attr}")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = node.name.lower()
            for token in ("select", "pick", "best", "rank", "top", "choose", "score",
                          "fitness", "relevan"):
                assert token not in name, f"ACQUIRER_SELECTS: 命名含 {token!r} 的 {node.name}"


def test_invariant_acquirer_is_not_an_acquirer_protocol_impl():
    """`propose` 返回全部候选;类**不**声称实现单值 `Acquirer` 协议。"""
    from hevi.creative.autonomous.resolver import Acquirer

    assert not hasattr(StockAssetAcquirer, "acquire"), (
        "StockAssetAcquirer 不应实现 Acquirer.acquire —— 单值返回本身就是选择")
    assert "acquire" not in StockAssetAcquirer.__dict__
    src = ACQUIRE_STOCK_SRC.read_text(encoding="utf-8")
    assert "class StockAssetAcquirer" in src
    # 协议本身仍在,但本类不继承它
    assert "StockAssetAcquirer(Acquirer)" not in src
    assert Acquirer is not None


async def test_invariant_propose_returns_every_viable_candidate(tmp_path):
    """`propose` 不排序、不截断成「一个赢家」,并保持 provider 原始顺序。"""
    payloads = {}
    items = []
    for i in range(3):
        path = _video(tmp_path / f"asset-{i}.mp4", seconds=5.0)
        payloads[f"a{i}"] = path
        items.append(_item(f"a{i}", f"black hole accretion disk variant {i}", path))
    acquirer = _acquirer(tmp_path, items, payloads)

    proposed = await acquirer.propose(_requirement(), limit=5)

    assert [n.candidate.candidate_id for n in proposed] == [
        f"local:{materialize_name(it)}" for it in items]


# ══ 物化约定 ══
def test_materialize_name_is_descriptive_and_collision_free():
    a = StockItem(external_id="1", url="https://x.invalid/a.mp4", title="Black Hole Disk")
    b = StockItem(external_id="2", url="https://x.invalid/b.mp4", title="Black Hole Disk")
    assert materialize_name(a).endswith(".mp4")
    assert materialize_name(a).startswith("black-hole-disk-")
    assert materialize_name(a) != materialize_name(b), "同标题不同 URL 不得撞车"


def test_default_cache_dir_follows_material_cache_dir(monkeypatch):
    monkeypatch.setenv("MATERIAL_CACHE_DIR", "/tmp/p2a-cache")
    assert default_cache_dir() == Path("/tmp/p2a-cache")
    monkeypatch.delenv("MATERIAL_CACHE_DIR")
    assert default_cache_dir() == Path("data/material_cache")


def test_requirement_identity_is_canonical_p7():
    """acquisition 的输入必须是 canonical p7 requirement,不是自造字符串。"""
    from hevi.production.p0_pipeline import VisualIntent

    intent = VisualIntent(
        intent_id="vi-1", timeline_lock_id="tl-1", narration_segment="black hole",
        start_s=0.0, end_s=1.0, required_entities=(), required_concepts=("black hole",),
        visual_purpose="p", motion_purpose="m")
    assert _requirement_for(intent).requirement_id == "VIDEO/SCENE"
    assert _requirement().requirement_id == "VIDEO/SCENE"