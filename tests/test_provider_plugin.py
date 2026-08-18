"""provider plugin 测试 —— 可编程供应商能力声明(差距 B5)。

覆盖: JSON/YAML 解析/校验(kind/分数域)/评分复用/目录 mtime 缓存即时生效/
注册进 registry(假 registry)/坏文件降级。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.providers.plugin_config import (
    ProviderDecl,
    load_catalog,
    load_plugin_file,
    parse_plugin_decl,
    register_into_registry,
    score_plugins,
)

VALID_YAML = """
providers:
  - id: my_stock_clip_api
    tool: video/shot
    kind: stock_video
    scores: {task_fit: 0.7, output_quality: 0.6, cost_efficiency: 0.9}
    meta: {endpoint: "https://example.com", requires_key: true}
  - id: my_tts_engine
    tool: tts/narration
    kind: tts
    scores: {task_fit: 0.8, latency: 0.9}
"""

VALID_JSON = """
{
  "providers": [
    {"id": "json_provider", "tool": "video/shot", "kind": "video",
     "scores": {"task_fit": 0.5}, "meta": {}}
  ]
}
"""


class TestParse:
    def test_parse_yaml(self) -> None:
        pf = parse_plugin_decl(VALID_YAML)
        assert len(pf.providers) == 2
        assert pf.providers[0].id == "my_stock_clip_api"
        assert pf.providers[0].kind == "stock_video"
        assert pf.providers[0].scores["task_fit"] == 0.7

    def test_parse_json(self) -> None:
        pf = parse_plugin_decl(VALID_JSON)
        assert pf.providers[0].id == "json_provider"

    def test_missing_providers_key_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_plugin_decl("kind: video\n")

    def test_empty_providers_rejected(self) -> None:
        with pytest.raises(ValueError):
            parse_plugin_decl("providers: []\n")

    @pytest.mark.parametrize(
        "kind",
        ["video", "image", "tts", "asr", "llm", "stock_video", "stock_image", "render", "other"],
    )
    def test_allowed_kinds(self, kind: str) -> None:
        pf = parse_plugin_decl(f"providers:\n  - id: p1\n    tool: x\n    kind: {kind}\n")
        assert pf.providers[0].kind == kind

    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown provider kind"):
            parse_plugin_decl("providers:\n  - id: p1\n    tool: x\n    kind: hacker\n")

    def test_score_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="out of \\[0,1\\]"):
            parse_plugin_decl(
                "providers:\n  - id: p1\n    tool: x\n    scores: {task_fit: 1.5}\n"
            )

    def test_capability_row_projection(self) -> None:
        decl = ProviderDecl(id="p1", tool="video/shot", kind="video", scores={"task_fit": 0.6})
        row = decl.capability_row
        assert row.provider == "p1"
        assert row.tool_name == "video/shot"
        assert row.scores == {"task_fit": 0.6}


class TestCatalog:
    def test_load_file(self, tmp_path: Path) -> None:
        f = tmp_path / "providers.yaml"
        f.write_text(VALID_YAML, encoding="utf-8")
        pf = load_plugin_file(f)
        assert len(pf.providers) == 2

    def test_catalog_mtime_cache_and_reload(self, tmp_path: Path) -> None:
        f = tmp_path / "providers.yaml"
        f.write_text(VALID_YAML, encoding="utf-8")
        c1 = load_catalog(f)
        assert len(c1.decls) == 2
        # 未变更 → 复用缓存(同对象)
        c2 = load_catalog(f, c1)
        assert c2 is c1
        # 变更 mtime + 内容 → 重载
        f.write_text(
            "providers:\n  - id: new_one\n    tool: video/shot\n    kind: video\n",
            encoding="utf-8",
        )
        import os

        os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 10))
        c3 = load_catalog(f, c1)
        assert c3 is not c1
        assert [d.id for d in c3.decls] == ["new_one"]

    def test_missing_file_degrades(self, tmp_path: Path) -> None:
        cat = load_catalog(tmp_path / "nope.yaml")
        assert cat.decls == []

    def test_corrupt_file_degrades(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.yaml"
        f.write_text("{{{ not yaml", encoding="utf-8")
        cat = load_catalog(f)
        assert cat.decls == []


class TestCatalogDir:
    """目录级加载: 多文件合并 + mtime 指纹缓存 + 坏文件降级。"""

    def test_dir_loads_all_plugin_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.yaml").write_text(
            "providers:\n  - id: from_a\n    tool: video/shot\n    kind: video\n",
            encoding="utf-8",
        )
        (tmp_path / "b.json").write_text(
            '{"providers": [{"id": "from_b", "tool": "tts/narration", "kind": "tts"}]}',
            encoding="utf-8",
        )
        # 非插件后缀文件忽略
        (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
        cat = load_catalog(tmp_path)
        assert {d.id for d in cat.decls} == {"from_a", "from_b"}

    def test_dir_mtime_cache_and_reload(self, tmp_path: Path) -> None:
        (tmp_path / "a.yaml").write_text(
            "providers:\n  - id: v1\n    tool: x\n    kind: video\n",
            encoding="utf-8",
        )
        import os

        c1 = load_catalog(tmp_path)
        assert c1.decls[0].id == "v1"
        # 未变更 → 复用缓存
        assert load_catalog(tmp_path, c1) is c1
        # 新文件加入 → 指纹变化 → 重载
        (tmp_path / "b.yaml").write_text(
            "providers:\n  - id: v2\n    tool: x\n    kind: video\n",
            encoding="utf-8",
        )
        os.utime(tmp_path / "b.yaml", (0, 0))
        c2 = load_catalog(tmp_path, c1)
        assert c2 is not c1
        assert {d.id for d in c2.decls} == {"v1", "v2"}

    def test_dir_with_bad_file_degrades_partially(self, tmp_path: Path) -> None:
        (tmp_path / "good.yaml").write_text(
            "providers:\n  - id: good\n    tool: x\n    kind: video\n",
            encoding="utf-8",
        )
        (tmp_path / "bad.yaml").write_text("not yaml at all", encoding="utf-8")
        cat = load_catalog(tmp_path)
        assert [d.id for d in cat.decls] == ["good"]

    def test_empty_dir_degrades(self, tmp_path: Path) -> None:
        cat = load_catalog(tmp_path)
        assert cat.decls == []


class TestScorePlugins:
    def test_score_filters_by_tool_and_sorts(self) -> None:
        pf = parse_plugin_decl(VALID_YAML)
        scored = score_plugins(pf.providers, "video/shot")
        # 只有 stock_clip 匹配 video/shot
        assert len(scored) == 1
        assert scored[0]["provider"] == "my_stock_clip_api"
        assert scored[0]["meta"]["endpoint"] == "https://example.com"
        assert "weighted_score" in scored[0]

    def test_score_empty_when_no_match(self) -> None:
        pf = parse_plugin_decl(VALID_YAML)
        assert score_plugins(pf.providers, "render/3d") == []


class FakeRegistry:
    """记录注册调用的假 registry(模拟 obase.ProviderRegistry 注册面)。"""

    def __init__(self) -> None:
        self.registered: list[tuple] = []

    def register(self, provider_id: str, **kwargs: object) -> None:
        self.registered.append((provider_id, kwargs))


class RegistryNoRegister:
    """无 register 方法的 registry(不阻断路径)。"""


class TestRegister:
    def test_register_all_decls(self) -> None:
        pf = parse_plugin_decl(VALID_YAML)
        reg = FakeRegistry()
        n = register_into_registry(pf.providers, reg)
        assert n == 2
        ids = {r[0] for r in reg.registered}
        assert ids == {"my_stock_clip_api", "my_tts_engine"}
        kwargs = dict(reg.registered[0][1])
        assert kwargs["kind"] == "stock_video"
        assert kwargs["scores"]["task_fit"] == 0.7

    def test_duplicate_id_overwrites(self) -> None:
        decls = [
            ProviderDecl(id="dup", tool="x", kind="video", scores={"task_fit": 0.3}),
            ProviderDecl(id="dup", tool="x", kind="video", scores={"task_fit": 0.9}),
        ]
        reg = FakeRegistry()
        n = register_into_registry(decls, reg)
        assert n == 2
        assert reg.registered[-1][1]["scores"]["task_fit"] == 0.9

    def test_registry_without_register_degrades(self) -> None:
        assert register_into_registry([], RegistryNoRegister()) == 0
        decls = [ProviderDecl(id="p1", tool="x", kind="video")]
        assert register_into_registry(decls, RegistryNoRegister()) == 0

    def test_register_failure_does_not_block(self) -> None:
        class FlakyRegistry(FakeRegistry):
            def register(self, provider_id: str, **kwargs: object) -> None:
                if provider_id == "bad":
                    raise RuntimeError("boom")
                super().register(provider_id, **kwargs)

        decls = [
            ProviderDecl(id="bad", tool="x", kind="video"),
            ProviderDecl(id="good", tool="x", kind="video"),
        ]
        reg = FlakyRegistry()
        n = register_into_registry(decls, reg)
        assert n == 1
        assert [r[0] for r in reg.registered] == ["good"]
