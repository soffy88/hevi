"""动态供应商加载器 - 从 YAML 配置文件热加载 AI providers。

支持运行时添加/删除/重载 provider,无需重启服务。

YAML 配置示例 (hevi/configs/providers/my_llm.yaml):
```yaml
category: llm
name: my_custom_llm
adapter: openai_compatible
config:
  base_url: https://api.example.com/v1
  api_key: ${MY_API_KEY}  # 环境变量插值
  model: gpt-4
  temperature: 0.7
enabled: true
priority: 10
```

支持的 adapter 类型:
- openai_compatible: OpenAI 兼容 API
- dashscope: 阿里云 DashScope
- httpx: 通用 HTTP 调用
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from obase.provider_registry import ProviderRegistry

logger = logging.getLogger(__name__)

# 配置文件目录
DEFAULT_CONFIG_DIR = Path("hevi/configs/providers")

# 环境变量插值正则: ${VAR_NAME} or ${VAR_NAME:-default}
ENV_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


def interpolate_env_vars(value: Any) -> Any:
    """递归插值 YAML 配置中的环境变量。

    支持 ${VAR} 和 ${VAR:-default} 语法。
    """
    if isinstance(value, str):
        def replace_env(match: re.Match) -> str:
            var_name = match.group(1)
            default_val = match.group(2)
            env_val = os.getenv(var_name)
            if env_val is not None:
                return env_val
            if default_val is not None:
                return default_val
            logger.warning(f"Environment variable {var_name} not found and no default provided")
            return match.group(0)  # 保持原样

        return ENV_VAR_PATTERN.sub(replace_env, value)
    elif isinstance(value, dict):
        return {k: interpolate_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [interpolate_env_vars(item) for item in value]
    else:
        return value


def create_openai_compatible_adapter(config: dict[str, Any]) -> Any:
    """创建 OpenAI 兼容的 LLM adapter。

    返回一个 callable,签名: (messages: list, **kwargs) -> dict
    """
    import httpx

    base_url = config["base_url"].rstrip("/")
    api_key = config.get("api_key", "")
    default_model = config.get("model", "gpt-3.5-turbo")
    default_temperature = config.get("temperature", 0.7)
    default_max_tokens = config.get("max_tokens", 4096)
    timeout = config.get("timeout", 120.0)

    class OpenAICompatibleAdapter:
        def __init__(self, **kwargs: Any):
            messages = kwargs.get("messages", [])
            model = kwargs.get("model", default_model)
            temperature = kwargs.get("temperature", default_temperature)
            max_tokens = kwargs.get("max_tokens", default_max_tokens)

            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            try:
                response = httpx.post(
                    f"{base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                data = response.json()

                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    self._resp = {
                        "content": content,
                        "usage": data.get("usage", {}),
                        "model": model,
                    }
                else:
                    self._resp = {"content": "", "usage": {}, "model": model}

            except Exception as e:
                logger.error(f"OpenAI compatible API call failed: {e}")
                self._resp = {"content": "", "error": str(e), "model": model}

        def __await__(self) -> Any:
            async def _dummy() -> dict[str, Any]:
                return self._resp
            return _dummy().__await__()

        def get(self, key: str, default: Any = None) -> Any:
            return self._resp.get(key, default)

    return OpenAICompatibleAdapter


def create_dashscope_adapter(config: dict[str, Any]) -> Any:
    """创建 DashScope adapter (复用 registry.py 中的实现)。"""
    import httpx

    api_key = config.get("api_key", os.getenv("DASHSCOPE_API_KEY", ""))
    default_model = config.get("model", "qwen-plus")
    default_temperature = config.get("temperature", 0.7)
    default_max_tokens = config.get("max_tokens", 4096)

    class DashScopeAdapter:
        def __init__(self, **kwargs: Any):
            messages = kwargs.get("messages", [])
            model = kwargs.get("model", default_model)
            temperature = kwargs.get("temperature", default_temperature)
            max_tokens = kwargs.get("max_tokens", default_max_tokens)

            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            try:
                response = httpx.post(
                    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=120.0,
                )
                data = response.json()

                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
                    self._resp = {
                        "content": content,
                        "usage": data.get("usage", {}),
                    }
                else:
                    self._resp = {"content": "", "usage": {}}

            except Exception as e:
                logger.error(f"DashScope API call failed: {e}")
                self._resp = {"content": "", "error": str(e)}

        def __await__(self) -> Any:
            async def _dummy() -> dict[str, Any]:
                return self._resp
            return _dummy().__await__()

        def get(self, key: str, default: Any = None) -> Any:
            return self._resp.get(key, default)

    return DashScopeAdapter


# Adapter 工厂注册表
ADAPTER_FACTORIES = {
    "openai_compatible": create_openai_compatible_adapter,
    "dashscope": create_dashscope_adapter,
}


def load_provider_from_yaml(yaml_path: Path) -> tuple[str, str, Any] | None:
    """从单个 YAML 文件加载 provider。

    Returns:
        (category, name, callable) 或 None (如果加载失败或禁用)
    """
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if not config:
            logger.warning(f"Empty config file: {yaml_path}")
            return None

        # 插值环境变量
        config = interpolate_env_vars(config)

        # 检查是否启用
        if not config.get("enabled", True):
            logger.info(f"Provider disabled: {yaml_path.stem}")
            return None

        category = config.get("category")
        name = config.get("name", yaml_path.stem)
        adapter_type = config.get("adapter")
        adapter_config = config.get("config", {})

        if not category or not adapter_type:
            logger.error(f"Missing category or adapter in {yaml_path}")
            return None

        # 获取 adapter 工厂
        factory = ADAPTER_FACTORIES.get(adapter_type)
        if not factory:
            logger.error(f"Unknown adapter type '{adapter_type}' in {yaml_path}")
            return None

        # 创建 callable
        callable_provider = factory(adapter_config)

        logger.info(f"Loaded provider: {category}/{name} from {yaml_path}")
        return (category, name, callable_provider)

    except Exception as e:
        logger.error(f"Failed to load provider from {yaml_path}: {e}")
        return None


def load_all_providers(config_dir: Path | None = None) -> int:
    """从配置目录加载所有 provider YAML 文件。

    Returns:
        成功加载的 provider 数量
    """
    config_dir = config_dir or DEFAULT_CONFIG_DIR

    if not config_dir.exists():
        logger.info(f"Provider config directory not found: {config_dir}")
        return 0

    loaded_count = 0

    for yaml_file in sorted(config_dir.glob("*.yaml")):
        result = load_provider_from_yaml(yaml_file)
        if result:
            category, name, callable_provider = result
            try:
                ProviderRegistry.register(category, name, callable_provider, replace=True)
                loaded_count += 1
            except Exception as e:
                logger.error(f"Failed to register provider {category}/{name}: {e}")

    logger.info(f"Loaded {loaded_count} providers from {config_dir}")
    return loaded_count


def reload_all_providers(config_dir: Path | None = None) -> int:
    """重载所有 YAML providers (先清除再加载)。

    注意:这只会重载 YAML 配置的 providers,不会影响代码中硬编码的 providers。
    """
    # TODO: 如果需要清除 YAML providers,需要维护一个已加载列表
    # 目前简单实现为直接重新加载 (replace=True)
    return load_all_providers(config_dir)


def list_yaml_providers(config_dir: Path | None = None) -> list[dict[str, Any]]:
    """列出所有 YAML 配置的 providers (不加载,只读取元数据)。"""
    config_dir = config_dir or DEFAULT_CONFIG_DIR

    if not config_dir.exists():
        return []

    providers = []

    for yaml_file in sorted(config_dir.glob("*.yaml")):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            if config:
                providers.append({
                    "name": config.get("name", yaml_file.stem),
                    "category": config.get("category", "unknown"),
                    "adapter": config.get("adapter", "unknown"),
                    "enabled": config.get("enabled", True),
                    "priority": config.get("priority", 0),
                    "config_file": str(yaml_file),
                })
        except Exception as e:
            logger.warning(f"Failed to read provider config {yaml_file}: {e}")

    return providers
