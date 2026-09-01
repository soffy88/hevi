"""provider_plugin —— 可编程供应商插件(3O obase 注册面, 差距 B5)。

对标 Toonflow 设置中心写供应商逻辑即时生效(无需改源码/重启), 补 hevi 差距:
加 provider 目前要改代码 + 重建容器。

落点: **能力声明文件**(JSON/YAML, 项目外部可编辑) → 校验 → 注册进 obase 的
ProviderRegistry / hevi 评分层(hevi/providers/scoring.py 的 CapabilityRow)。
即时生效语义: 加载器每次调用重读文件 + mtime 缓存失效, 无需重启。

能力声明文件 schema::

    {
      "providers": [
        {
          "id": "my_stock_clip_api",
          "tool": "video/shot",
          "kind": "stock_video",
          "scores": {"task_fit": 0.7, "output_quality": 0.6, "cost_efficiency": 0.9},
          "meta": {"endpoint": "https://...", "requires_key": true, "docs": "..."}
        }
      ]
    }

安全: 声明只描述能力与评分(不含可执行代码) —— 不引入任意代码执行面; 可执行
逻辑仍走既有 provider 实现(hevi/providers/), 声明只做路由/评分输入。
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib import error, request

import yaml
from pydantic import BaseModel, Field

from hevi.providers.scoring import CapabilityRow, score_candidates_from_capabilities

logger = logging.getLogger(__name__)

_ALLOWED_KINDS = {
    "video", "image", "tts", "asr", "llm", "stock_video", "stock_image", "render", "other"
}


class ProviderDecl(BaseModel):
    id: str
    tool: str  # 任务类别, 如 "video/shot"
    kind: str = "other"
    scores: dict[str, float] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)

    @property
    def capability_row(self) -> CapabilityRow:
        return CapabilityRow(
            provider=self.id,
            tool_name=self.tool,
            scores=self.scores,
            meta=self.meta,
        )


class ProviderPluginFile(BaseModel):
    providers: list[ProviderDecl] = Field(min_length=1)


@dataclass
class PluginCatalog:
    """已加载的插件目录(mtime 缓存, 支持重载)。"""

    source: Path
    mtime: float = 0.0
    decls: list[ProviderDecl] = field(default_factory=list)

    def is_stale(self) -> bool:
        try:
            return self.source.stat().st_mtime > self.mtime
        except OSError:
            return True


# ---------------------------------------------------------------------------
# 加载/校验(纯函数, 可单测)
# ---------------------------------------------------------------------------


def parse_plugin_decl(text: str) -> ProviderPluginFile:
    """JSON/YAML 文本 → ProviderPluginFile(pydantic 校验)。"""
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or "providers" not in data:
        raise ValueError("plugin file must contain a 'providers' list")
    pf = ProviderPluginFile(**data)
    for decl in pf.providers:
        if decl.kind not in _ALLOWED_KINDS:
            raise ValueError(f"unknown provider kind {decl.kind!r}")
        for dim, v in decl.scores.items():
            if not 0.0 <= float(v) <= 1.0:
                raise ValueError(f"score {dim}={v} out of [0,1] for {decl.id}")
    return pf


def load_plugin_file(path: Path) -> ProviderPluginFile:
    return parse_plugin_decl(path.read_text(encoding="utf-8"))


def score_plugins(decls: list[ProviderDecl], tool_name: str) -> list[dict[str, Any]]:
    """插件声明 → 评分结果(复用 A1 评分层, 降序)。

    返回 [{provider, weighted_score, 维度分, meta}] 供路由层/UI 使用。
    """
    rows = [d.capability_row for d in decls if d.tool == tool_name]
    scored = score_candidates_from_capabilities(rows, tool_name)
    out: list[dict[str, Any]] = []
    for s in scored:
        meta = next(
            (d.meta for d in decls if d.id == s.provider and d.tool == tool_name), {}
        )
        item = s.to_dict()
        item["id"] = s.provider  # 声明 id 与评分 provider 同键, 供路由/UI 统一消费
        out.append({**item, "meta": meta})
    return out


# ---------------------------------------------------------------------------
# 目录级加载(带 mtime 缓存)
# ---------------------------------------------------------------------------

_PLUGIN_EXTS = (".yaml", ".yml", ".json")


def _dir_fingerprint(d: Path) -> tuple[float, ...] | None:
    """目录下插件文件集合的 mtime 指纹(排序后), 目录缺失/无插件文件返回 None。"""
    try:
        files = sorted(p for p in d.iterdir() if p.suffix.lower() in _PLUGIN_EXTS)
    except OSError:
        return None
    if not files:
        return None
    try:
        return tuple(f.stat().st_mtime for f in files)
    except OSError:
        return None


def load_catalog(
    path: Path, catalog: PluginCatalog | None = None
) -> PluginCatalog:
    """加载插件目录。mtime 未变则复用缓存(即时生效: 文件改动后下次调用即重载)。

    - path 为文件: 加载单文件;
    - path 为目录: 加载目录下全部 *.yaml/*.yml/*.json 插件文件并合并(按文件名序)。
    - 目录缺失/无插件文件/全部损坏: 返回空目录(不阻断)。
    """
    if path.is_dir():
        return _load_catalog_dir(path, catalog)
    return _load_catalog_file(path, catalog)


def _load_catalog_file(
    path: Path, catalog: PluginCatalog | None = None
) -> PluginCatalog:
    if not path.exists():
        return PluginCatalog(source=path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return PluginCatalog(source=path)
    if catalog is not None and catalog.source == path and not catalog.is_stale():
        return catalog
    try:
        pf = load_plugin_file(path)
    except Exception as exc:
        logger.warning("plugin file load failed (%s): %s", path, exc)
        return PluginCatalog(source=path)
    return PluginCatalog(source=path, mtime=mtime, decls=pf.providers)


def _load_catalog_dir(
    d: Path, catalog: PluginCatalog | None = None
) -> PluginCatalog:
    fp = _dir_fingerprint(d)
    if fp is None:
        return PluginCatalog(source=d)
    # 目录指纹(文件集合 mtime) 未变 → 复用缓存
    if catalog is not None and catalog.source == d and catalog.mtime == fp[-1]:
        return catalog
    decls: list[ProviderDecl] = []
    try:
        files = sorted(p for p in d.iterdir() if p.suffix.lower() in _PLUGIN_EXTS)
    except OSError:
        return PluginCatalog(source=d)
    for f in files:
        try:
            decls.extend(load_plugin_file(f).providers)
        except Exception as exc:
            logger.warning("plugin file load failed (%s): %s", f, exc)
    return PluginCatalog(source=d, mtime=fp[-1], decls=decls)


def register_into_registry(decls: list[ProviderDecl], registry: Any) -> int:
    """把插件声明注册进 obase.ProviderRegistry(能力行登记, 重复 id 覆盖)。

    返回注册数量。registry 需支持 register(provider_id, ...) 或 register_provider;
    对不支持的面, 记录日志并返回 0(不阻断)。
    """
    register = getattr(registry, "register", None) or getattr(registry, "register_provider", None)
    if register is None:
        logger.warning("registry has no register() — skip plugin registration")
        return 0
    count = 0
    for decl in decls:
        try:
            register(decl.id, kind=decl.kind, scores=decl.scores, meta=decl.meta)
            count += 1
        except Exception as exc:
            logger.warning("plugin register failed (%s): %s", decl.id, exc)
    return count


def invoke_declared_provider(
    decl: ProviderDecl,
    payload: dict[str, Any],
    *,
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """Invoke a declared provider through a bounded HTTP or argv boundary.

    A plugin declaration remains data-only, but it can now point at an
    independently managed TypeScript/Python process via ``meta.command`` or
    an HTTP worker via ``meta.endpoint``.  Commands never use a shell and
    must return one JSON object on stdout; HTTP responses follow the same
    contract.  No plugin code is imported into the API process.
    """

    meta = dict(decl.meta or {})
    endpoint = str(meta.get("endpoint") or "").strip()
    if endpoint:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout_s) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, error.URLError) as exc:
            raise RuntimeError(f"plugin endpoint failed: {endpoint}") from exc
        if not isinstance(raw, dict):
            raise ValueError("plugin endpoint must return a JSON object")
        return raw

    command = meta.get("command")
    if isinstance(command, str):
        command = [command]
    if not isinstance(command, list) or not command or not all(isinstance(item, str) and item for item in command):
        raise ValueError(f"provider {decl.id} has no valid meta.endpoint or meta.command")
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"plugin command failed to start: {decl.id}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "plugin command failed").strip()[-500:]
        raise RuntimeError(f"plugin command returned {completed.returncode}: {detail}")
    try:
        raw = json.loads(completed.stdout)
    except ValueError as exc:
        raise ValueError(f"plugin {decl.id} stdout is not JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("plugin command must return a JSON object")
    return raw


__all__ = [
    "PluginCatalog",
    "ProviderDecl",
    "ProviderPluginFile",
    "invoke_declared_provider",
    "load_catalog",
    "load_plugin_file",
    "parse_plugin_decl",
    "register_into_registry",
    "score_plugins",
]
