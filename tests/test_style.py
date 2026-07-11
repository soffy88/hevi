"""StylePack 版本化测试(§3 L2)。"""

from __future__ import annotations

import pytest

from hevi.style.style_service import StylePackService, resolve_style


def test_resolve_style_merges_base_and_overrides():
    pack = {
        "base_preset": "电影感",
        "overrides_json": {"color_grade": "warm gold", "negative": "no text"},
    }
    r = resolve_style(pack)
    assert "cinematic" in r["style"]  # 继承内置预设
    assert r["color_grade"] == "warm gold"  # 覆盖生效
    assert r["negative"] == "no text"


def test_resolve_style_ignores_non_style_keys():
    pack = {"base_preset": "科普", "overrides_json": {"color_grade": "x", "evil": "y"}}
    r = resolve_style(pack)
    assert r["color_grade"] == "x" and "evil" not in r


# ── capture_source 根变量结构(HEVI 路线图 Phase3 #38)──────────────────────────


def test_resolve_style_derives_defaults_from_capture_source():
    """没有 base_preset/显式覆盖时,capture_source 派生的 camera/lighting/negative
    也该出现在最终结果里——这是"单一根变量派生默认值"的核心行为。"""
    pack = {"base_preset": "", "overrides_json": {"capture_source": "2000s_home_dv"}}
    r = resolve_style(pack)
    assert "camcorder" in r["camera"]
    assert "negative" in r
    assert "capture_source" not in r  # 元字段本身不该混进最终输出


def test_capture_source_defaults_lose_to_base_preset():
    """优先级:capture_source < base_preset——两者都提供 camera 时 base_preset 赢。"""
    pack = {
        "base_preset": "电影感",
        "overrides_json": {"capture_source": "2000s_home_dv"},
    }
    r = resolve_style(pack)
    assert "camcorder" not in r["camera"]  # 没有被 capture_source 覆盖
    assert "dolly" in r["camera"]  # 电影感预设的值


def test_capture_source_defaults_lose_to_explicit_override():
    """优先级:base_preset < 显式 overrides——三者都给 camera 时显式覆盖赢。"""
    pack = {
        "base_preset": "电影感",
        "overrides_json": {"capture_source": "2000s_home_dv", "camera": "custom camera move"},
    }
    r = resolve_style(pack)
    assert r["camera"] == "custom camera move"


def test_resolve_style_unknown_capture_source_degrades_gracefully():
    pack = {"base_preset": "科普", "overrides_json": {"capture_source": "不存在的设备"}}
    r = resolve_style(pack)
    assert "camera" in r  # 来自 base_preset,没有因为 capture_source 未知而报错


@pytest.mark.asyncio
async def test_create_pack_stores_capture_source():
    repo = _FakeRepo()
    svc = StylePackService(repo)
    pack = await svc.create_pack(
        name="p", base_preset="电影感", overrides={"capture_source": "vhs_tape"}
    )
    assert pack["overrides_json"]["capture_source"] == "vhs_tape"


class _FakeRepo:
    def __init__(self):
        self.saved = None

    async def create(self, data):
        self.saved = {**data, "id": "p1"}
        return self.saved

    async def get(self, pid):
        return self.saved

    async def update(self, pid, updates):
        self.saved = {**self.saved, **updates}
        return self.saved


@pytest.mark.asyncio
async def test_create_pack_validates_base_preset():
    svc = StylePackService(_FakeRepo())
    with pytest.raises(ValueError):
        await svc.create_pack(name="p", base_preset="不存在的预设")


@pytest.mark.asyncio
async def test_update_overrides_bumps_version():
    repo = _FakeRepo()
    svc = StylePackService(repo)
    await svc.create_pack(name="p", base_preset="电影感", overrides={"camera": "static"})
    assert repo.saved["version"] == 1
    updated = await svc.update_overrides("p1", overrides={"color_grade": "cold"})
    assert updated["version"] == 2  # 改风格 → 新版本
    assert updated["overrides_json"] == {"camera": "static", "color_grade": "cold"}  # 合并
