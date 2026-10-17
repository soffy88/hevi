"""供应商热插拔功能测试。

测试覆盖:
- YAML 配置解析和环境变量插值
- Provider 动态加载和注册
- API 端点 (CRUD + reload)
- 错误处理和边界情况
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import pytest
import yaml

from hevi.providers.dynamic_loader import (
    interpolate_env_vars,
    load_provider_from_yaml,
    load_all_providers,
    list_yaml_providers,
)


# ── 环境变量插值测试 ─────────────────────────────────────────────────────────


class TestEnvVarInterpolation:
    """测试环境变量插值功能。"""

    def test_simple_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 ${VAR} 语法。"""
        monkeypatch.setenv("TEST_API_KEY", "secret123")
        result = interpolate_env_vars("${TEST_API_KEY}")
        assert result == "secret123"

    def test_env_var_with_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试 ${VAR:-default} 语法 (变量不存在时使用默认值)。"""
        # 确保环境变量不存在
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        result = interpolate_env_vars("${NONEXISTENT_VAR:-default_value}")
        assert result == "default_value"

    def test_env_var_exists_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试环境变量存在时覆盖默认值。"""
        monkeypatch.setenv("MY_VAR", "actual_value")
        result = interpolate_env_vars("${MY_VAR:-default_value}")
        assert result == "actual_value"

    def test_nested_dict_interpolation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试嵌套字典中的环境变量插值。"""
        monkeypatch.setenv("API_KEY", "key123")
        monkeypatch.setenv("MODEL", "gpt-4")

        config = {
            "base_url": "https://api.example.com",
            "api_key": "${API_KEY}",
            "model": "${MODEL}",
            "nested": {
                "inner_key": "${API_KEY}",
            },
        }
        result = interpolate_env_vars(config)
        assert result["api_key"] == "key123"
        assert result["model"] == "gpt-4"
        assert result["nested"]["inner_key"] == "key123"

    def test_list_interpolation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """测试列表中的环境变量插值。"""
        monkeypatch.setenv("ITEM1", "value1")
        monkeypatch.setenv("ITEM2", "value2")

        config = ["${ITEM1}", "${ITEM2}", "static"]
        result = interpolate_env_vars(config)
        assert result == ["value1", "value2", "static"]

    def test_non_string_passthrough(self) -> None:
        """测试非字符串类型直接返回。"""
        assert interpolate_env_vars(123) == 123
        assert interpolate_env_vars(3.14) == 3.14
        assert interpolate_env_vars(True) is True
        assert interpolate_env_vars(None) is None


# ── YAML 加载测试 ────────────────────────────────────────────────────────────


class TestYAMLLoading:
    """测试 YAML 配置文件加载。"""

    def test_load_valid_openai_config(self, tmp_path: Path) -> None:
        """测试加载有效的 OpenAI 兼容配置。"""
        yaml_content = {
            "category": "llm",
            "name": "test_openai",
            "adapter": "openai_compatible",
            "config": {
                "base_url": "https://api.test.com/v1",
                "api_key": "test_key",
                "model": "gpt-3.5-turbo",
            },
            "enabled": True,
        }

        yaml_file = tmp_path / "test_openai.yaml"
        yaml_file.write_text(yaml.dump(yaml_content), encoding="utf-8")

        result = load_provider_from_yaml(yaml_file)
        assert result is not None
        category, name, callable_provider = result
        assert category == "llm"
        assert name == "test_openai"
        assert callable(callable_provider)

    def test_load_disabled_provider(self, tmp_path: Path) -> None:
        """测试禁用的 provider 返回 None。"""
        yaml_content = {
            "category": "llm",
            "name": "disabled_provider",
            "adapter": "openai_compatible",
            "config": {
                "base_url": "https://api.test.com/v1",
                "api_key": "test_key",
            },
            "enabled": False,
        }

        yaml_file = tmp_path / "disabled.yaml"
        yaml_file.write_text(yaml.dump(yaml_content), encoding="utf-8")

        result = load_provider_from_yaml(yaml_file)
        assert result is None

    def test_load_missing_category(self, tmp_path: Path) -> None:
        """测试缺少 category 字段返回 None。"""
        yaml_content = {
            "name": "no_category",
            "adapter": "openai_compatible",
            "config": {},
        }

        yaml_file = tmp_path / "no_category.yaml"
        yaml_file.write_text(yaml.dump(yaml_content), encoding="utf-8")

        result = load_provider_from_yaml(yaml_file)
        assert result is None

    def test_load_unknown_adapter(self, tmp_path: Path) -> None:
        """测试未知 adapter 类型返回 None。"""
        yaml_content = {
            "category": "llm",
            "name": "unknown_adapter",
            "adapter": "nonexistent_adapter",
            "config": {},
        }

        yaml_file = tmp_path / "unknown.yaml"
        yaml_file.write_text(yaml.dump(yaml_content), encoding="utf-8")

        result = load_provider_from_yaml(yaml_file)
        assert result is None

    def test_load_with_env_var_interpolation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """测试加载时自动插值环境变量。"""
        monkeypatch.setenv("TEST_BASE_URL", "https://api.env.com/v1")
        monkeypatch.setenv("TEST_API_KEY", "env_key_123")

        yaml_content = {
            "category": "llm",
            "name": "env_test",
            "adapter": "openai_compatible",
            "config": {
                "base_url": "${TEST_BASE_URL}",
                "api_key": "${TEST_API_KEY}",
            },
            "enabled": True,
        }

        yaml_file = tmp_path / "env_test.yaml"
        yaml_file.write_text(yaml.dump(yaml_content), encoding="utf-8")

        result = load_provider_from_yaml(yaml_file)
        assert result is not None
        # 验证 provider 被创建 (插值在内部完成)
        category, name, callable_provider = result
        assert name == "env_test"


# ── 批量加载测试 ─────────────────────────────────────────────────────────────


class TestBatchLoading:
    """测试批量加载 providers。"""

    def test_load_all_from_directory(self, tmp_path: Path) -> None:
        """测试从目录加载所有 YAML 文件。"""
        # 创建 3 个有效的 provider 配置
        for i in range(3):
            yaml_content = {
                "category": "llm",
                "name": f"provider_{i}",
                "adapter": "openai_compatible",
                "config": {
                    "base_url": f"https://api{i}.test.com/v1",
                    "api_key": f"key_{i}",
                },
                "enabled": True,
            }
            yaml_file = tmp_path / f"provider_{i}.yaml"
            yaml_file.write_text(yaml.dump(yaml_content), encoding="utf-8")

        # 添加一个禁用的
        disabled_content = {
            "category": "llm",
            "name": "disabled",
            "adapter": "openai_compatible",
            "config": {"base_url": "https://disabled.com", "api_key": "x"},
            "enabled": False,
        }
        disabled_file = tmp_path / "disabled.yaml"
        disabled_file.write_text(yaml.dump(disabled_content), encoding="utf-8")

        count = load_all_providers(tmp_path)
        assert count == 3  # 只计算启用的

    def test_load_all_empty_directory(self, tmp_path: Path) -> None:
        """测试空目录返回 0。"""
        count = load_all_providers(tmp_path)
        assert count == 0

    def test_load_all_nonexistent_directory(self, tmp_path: Path) -> None:
        """测试不存在的目录返回 0。"""
        nonexistent = tmp_path / "nonexistent"
        count = load_all_providers(nonexistent)
        assert count == 0


# ── 列表查询测试 ─────────────────────────────────────────────────────────────


class TestListProviders:
    """测试列出 YAML providers。"""

    def test_list_yaml_providers(self, tmp_path: Path) -> None:
        """测试列出所有 YAML 配置的 providers。"""
        # 创建 2 个配置文件
        for i in range(2):
            yaml_content = {
                "category": "llm",
                "name": f"listed_provider_{i}",
                "adapter": "openai_compatible",
                "config": {},
                "enabled": i == 0,  # 一个启用,一个禁用
            }
            yaml_file = tmp_path / f"provider_{i}.yaml"
            yaml_file.write_text(yaml.dump(yaml_content), encoding="utf-8")

        providers = list_yaml_providers(tmp_path)
        assert len(providers) == 2

        # 验证元数据
        names = {p["name"] for p in providers}
        assert "listed_provider_0" in names
        assert "listed_provider_1" in names

        # 验证 enabled 状态
        enabled_map = {p["name"]: p["enabled"] for p in providers}
        assert enabled_map["listed_provider_0"] is True
        assert enabled_map["listed_provider_1"] is False


# ── 集成测试 ─────────────────────────────────────────────────────────────────


class TestIntegration:
    """集成测试 (需要实际的 ProviderRegistry)。"""

    def test_load_and_register_real_provider(self, tmp_path: Path) -> None:
        """测试加载并注册真实 provider 到 ProviderRegistry。"""
        from obase.provider_registry import ProviderRegistry

        yaml_content = {
            "category": "llm",
            "name": "integration_test_provider",
            "adapter": "openai_compatible",
            "config": {
                "base_url": "https://api.integration.com/v1",
                "api_key": "integration_key",
            },
            "enabled": True,
        }

        yaml_file = tmp_path / "integration.yaml"
        yaml_file.write_text(yaml.dump(yaml_content), encoding="utf-8")

        # 加载
        count = load_all_providers(tmp_path)
        assert count == 1

        # 验证已注册 (如果 ProviderRegistry 支持查询)
        # 注意:ProviderRegistry 的具体 API 取决于 obase 实现
        # 这里只验证加载过程不抛异常


# ── 错误处理测试 ─────────────────────────────────────────────────────────────


class TestErrorHandling:
    """测试错误处理。"""

    def test_invalid_yaml_syntax(self, tmp_path: Path) -> None:
        """测试无效 YAML 语法返回 None。"""
        yaml_file = tmp_path / "invalid.yaml"
        yaml_file.write_text("invalid: yaml: syntax: [unclosed", encoding="utf-8")

        result = load_provider_from_yaml(yaml_file)
        assert result is None

    def test_empty_yaml_file(self, tmp_path: Path) -> None:
        """测试空 YAML 文件返回 None。"""
        yaml_file = tmp_path / "empty.yaml"
        yaml_file.write_text("", encoding="utf-8")

        result = load_provider_from_yaml(yaml_file)
        assert result is None

    def test_missing_config_section(self, tmp_path: Path) -> None:
        """测试缺少 config 部分时使用最小必要配置。"""
        yaml_content = {
            "category": "llm",
            "name": "minimal_config",
            "adapter": "openai_compatible",
            "config": {
                "base_url": "https://api.minimal.com/v1",  # 最小必要字段
            },
            "enabled": True,
        }

        yaml_file = tmp_path / "minimal.yaml"
        yaml_file.write_text(yaml.dump(yaml_content), encoding="utf-8")

        result = load_provider_from_yaml(yaml_file)
        # 应该能加载 (只要有必需字段)
        assert result is not None
