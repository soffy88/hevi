"""S25：节点执行器插件契约（**仅内部设计**，不开放市场）。

目标：以后要接第三方节点时，有明确的边界，而不是把任意 Python 塞进执行器。

* 一个插件声明 ``id`` / ``version`` / ``node_types`` / ``permissions`` /
  ``timeout_s`` / ``input_schema`` / ``output_schema``；
* 权限是白名单（``fs.read``/``fs.write``/``net``/``gpu``/``paid_generation``），
  没有声明的权限 = 没有；
* ``timeout_s`` 上限 300；``paid_generation`` 必须同时声明 ``cost_estimate``，
  否则拒绝注册（钱必须能提前算）；
* 校验是纯函数，不加载/执行插件代码。

风险（写进报告，不在本轮对外）：插件能读工作区文件、能发网络请求；即使白名单
也需要进程隔离、资源限制与审计日志。本轮只定契约与校验，不接第三方。
"""

from __future__ import annotations

from typing import Any

PLUGIN_SCHEMA = "hevi.canvas.plugin.v1"
PERMISSIONS = frozenset({"fs.read", "fs.write", "net", "gpu", "paid_generation"})
MAX_TIMEOUT_S = 300


class PluginContractError(ValueError):
    pass


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise PluginContractError(message)


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """校验插件清单；通过后返回规范化副本（不改原对象）。"""
    _require(isinstance(manifest, dict), "manifest 必须是对象")
    _require(manifest.get("schema") == PLUGIN_SCHEMA, f"schema 必须是 {PLUGIN_SCHEMA}")
    plugin_id = str(manifest.get("id") or "").strip()
    _require(bool(plugin_id), "缺少 id")
    _require(
        all(ch.isalnum() or ch in "-_." for ch in plugin_id),
        "id 只能用字母、数字、- _ .",
    )
    version = str(manifest.get("version") or "").strip()
    _require(bool(version), "缺少 version")
    node_types = manifest.get("node_types") or []
    _require(isinstance(node_types, list) and node_types, "node_types 必须是非空数组")
    allowed_types = {"text", "image", "video", "audio", "script", "segment", "asset"}
    _require(set(map(str, node_types)) <= allowed_types, "node_types 只能声明现有 7 类节点")
    perms = manifest.get("permissions") or []
    _require(isinstance(perms, list), "permissions 必须是数组")
    unknown = set(map(str, perms)) - PERMISSIONS
    _require(not unknown, f"未知权限：{', '.join(sorted(unknown))}")
    timeout = manifest.get("timeout_s", 60)
    _require(isinstance(timeout, (int, float)) and 0 < float(timeout) <= MAX_TIMEOUT_S, "timeout_s 必须在 1–300 之间")
    if "paid_generation" in perms:
        _require(bool(manifest.get("cost_estimate")), "声明 paid_generation 必须提供 cost_estimate")
    for key in ("input_schema", "output_schema"):
        schema = manifest.get(key)
        _require(isinstance(schema, dict) and schema.get("type") == "object", f"{key} 必须是 object 类型 JSON Schema")
    return {
        "schema": PLUGIN_SCHEMA,
        "id": plugin_id,
        "version": version,
        "node_types": list(map(str, node_types)),
        "permissions": sorted(set(map(str, perms))),
        "timeout_s": float(timeout),
        "cost_estimate": manifest.get("cost_estimate"),
        "input_schema": manifest["input_schema"],
        "output_schema": manifest["output_schema"],
        "display_name": str(manifest.get("display_name") or plugin_id),
    }


def contract_doc() -> dict[str, Any]:
    """给内部文档/接口用的契约摘要（不是可执行代码）。"""
    return {
        "schema": PLUGIN_SCHEMA,
        "permissions": sorted(PERMISSIONS),
        "max_timeout_s": MAX_TIMEOUT_S,
        "paid_generation_requires_cost_estimate": True,
        "status": "internal_only",
        "risk": [
            "插件可读取工作区允许目录内的文件；需要进程隔离与挂载白名单。",
            "net 权限可外联；需要出站域名白名单与审计日志。",
            "paid_generation 会产生真实费用；注册前必须能报价，执行前必须再确认。",
            "本轮不接第三方、不开放市场、不注册外部服务。",
        ],
    }
