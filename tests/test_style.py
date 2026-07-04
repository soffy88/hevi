"""StylePack 版本化测试(§3 L2)。"""

from __future__ import annotations

import pytest

from hevi.style.style_service import StylePackService, resolve_style


def test_resolve_style_merges_base_and_overrides():
    pack = {"base_preset": "电影感", "overrides_json": {"color_grade": "warm gold", "negative": "no text"}}
    r = resolve_style(pack)
    assert "cinematic" in r["style"]  # 继承内置预设
    assert r["color_grade"] == "warm gold"  # 覆盖生效
    assert r["negative"] == "no text"


def test_resolve_style_ignores_non_style_keys():
    pack = {"base_preset": "科普", "overrides_json": {"color_grade": "x", "evil": "y"}}
    r = resolve_style(pack)
    assert r["color_grade"] == "x" and "evil" not in r


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
