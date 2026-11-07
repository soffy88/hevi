"""MCP bridge contract, fake harness (``qa.mcp_bridge_contract``).

Fake-level contract harness for a newline-delimited JSON-RPC 2.0
bridge of the kind described in the Infinite Creation review
(see ``INFINITE_CREATION_ATTRIBUTION.md``). It speaks the
protocol shape -- ``initialize``, ``tools/list`` and
``tools/call`` frames -- against canned, deterministic answers,
and it speaks nothing else: there is no stdio server here, no
agent runtime is launched, and no external tool is ever called.
Every ``tools/call`` answer is marked ``executed_here: false``;
the harness certifies the shape of the conversation, never that
work happened on the other side.

Tool names and schemas below are written for this contract.
They restate the reviewed bridge's tool surface in the house's
own wording; no tool implementation from the reviewed project
is copied, and the harness must never be wired to a real
runtime without a separate decision.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "hevi-mcp-bridge-contract"

_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "get_project",
        "description": "Return the project record for the bridged session (contract only).",
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
    },
    {
        "name": "save_context",
        "description": "Record a context entry for the bridged session (contract only).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "entry": {"type": "object"},
            },
            "required": ["project_id", "entry"],
        },
    },
    {
        "name": "set_storyboard",
        "description": "Accept a storyboard plan for the bridged session (contract only).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "storyboard": {"type": "object"},
            },
            "required": ["project_id", "storyboard"],
        },
    },
    {
        "name": "list_workflows",
        "description": "List the workflow specifications known to the bridge (contract only).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_status",
        "description": "Return the run status for the bridged session (contract only).",
        "inputSchema": {
            "type": "object",
            "properties": {"project_id": {"type": "string"}},
            "required": ["project_id"],
        },
    },
)

_TOOL_NAMES = {tool["name"] for tool in _TOOLS}


def list_bridge_tools() -> list[dict[str, Any]]:
    """Return the bridge's tool schemas (copies, never the live list)."""
    return [json.loads(json.dumps(tool)) for tool in _TOOLS]


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def handle_mcp_frame(frame: Any) -> dict[str, Any]:
    """Handle one JSON-RPC 2.0 frame against the fake bridge.

    Unknown methods return -32601, malformed frames -32600, and
    unknown tools -32602. No frame ever reaches a real runtime.
    """
    if not isinstance(frame, dict):
        return _error(None, -32600, "frame must be a JSON object")
    request_id = frame.get("id")
    if frame.get("jsonrpc") != "2.0" or "method" not in frame:
        return _error(request_id, -32600, "frame must carry jsonrpc 2.0 and a method")
    method = frame["method"]
    params = frame.get("params", {})
    if not isinstance(params, dict):
        return _error(request_id, -32602, "params must be an object")
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
            },
        )
    if method == "tools/list":
        return _result(request_id, {"tools": list_bridge_tools()})
    if method == "tools/call":
        tool_name = params.get("name")
        if tool_name not in _TOOL_NAMES:
            return _error(request_id, -32602, f"unknown tool: {tool_name}")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            return _error(request_id, -32602, "arguments must be an object")
        return _result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "tool": tool_name,
                                "arguments_received": sorted(arguments),
                                "executed_here": False,
                                "contract_only": True,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
                "isError": False,
            },
        )
    return _error(request_id, -32601, f"method not found: {method}")


def check_mcp_transcript(frames: Any) -> dict[str, Any]:
    """Judge a list of request/response frame pairs.

    A transcript is well-formed when every request has a matching
    response id, ``initialize`` comes first, ids are unique, and
    no response carries both ``result`` and ``error``. This
    judges shape only; it never replays a session.
    """
    if not isinstance(frames, list) or not frames:
        raise CapabilityError("transcript must be a non-empty list of frames")
    issues: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    first_method = None
    for index, pair in enumerate(frames):
        if not isinstance(pair, dict):
            issues.append({"code": "pair_not_object", "detail": f"pair {index} is not an object"})
            continue
        request = pair.get("request", {})
        response = pair.get("response", {})
        if not isinstance(request, dict) or not isinstance(response, dict):
            issues.append({"code": "pair_shape", "detail": f"pair {index} needs request/response objects"})
            continue
        if first_method is None:
            first_method = request.get("method")
        request_id = request.get("id")
        if request_id in seen_ids:
            issues.append({"code": "duplicate_id", "detail": f"request id {request_id} repeats", "pair": index})
        seen_ids.add(request_id)
        if response.get("id") != request_id:
            issues.append(
                {"code": "id_mismatch", "detail": f"pair {index} response id does not match request", "pair": index}
            )
        has_result = "result" in response
        has_error = "error" in response
        if has_result == has_error:
            issues.append(
                {"code": "response_shape", "detail": f"pair {index} must carry exactly one of result/error", "pair": index}
            )
    if first_method != "initialize":
        issues.append({"code": "initialize_not_first", "detail": "transcript must begin with initialize"})
    verdict = "fail" if issues else "pass"
    return {
        "ok": verdict != "fail",
        "verdict": verdict,
        "issues": issues,
        "not_checked": [],
        "frame_count": len(frames),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript = params.get("transcript")
    if transcript is not None:
        report: dict[str, Any] = check_mcp_transcript(transcript)
    else:
        frame = params.get("frame")
        if frame is None:
            raise CapabilityError("params require frame or transcript")
        report = {"response": handle_mcp_frame(frame), "executed_here": False}
    report_path = out_dir / "mcp_bridge_contract.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path)},
    )


def register_mcp_bridge_contract_capabilities_once() -> list[str]:
    """Register ``qa.mcp_bridge_contract`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.mcp_bridge_contract",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "frame": {"type": "object"},
                    "transcript": {"type": "array"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "MCP bridge contract (fake harness): JSON-RPC 2.0 frames "
                "for initialize/tools-list/tools-call against canned answers; "
                "no runtime is launched and nothing is executed."
            ),
        )
    )
    return ["qa.mcp_bridge_contract"]


__all__ = [
    "check_mcp_transcript",
    "handle_mcp_frame",
    "list_bridge_tools",
    "register_mcp_bridge_contract_capabilities_once",
]
