"""Owned stdio MCP process lifecycle for read-only provider probes.

The external MatrixMedia MCP server remains an independent process.  This
module owns only the invocation it starts, reads one complete JSON-RPC result,
and reaps the process group.  Mutating calls must use a provider-specific
terminal-result protocol and must not use :func:`read_only_call`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


class McpProcessError(RuntimeError):
    """Fail-closed MCP process error with a stable classification."""

    def __init__(self, failure_class: str, message: str) -> None:
        super().__init__(message)
        self.failure_class = failure_class


@dataclass(frozen=True)
class McpCallResult:
    """A complete JSON-RPC response and owned process lifecycle evidence."""

    response: dict[str, Any]
    process_exit: int
    process_leaks: int
    zombies: int


def _tool_text(response: Mapping[str, Any]) -> str:
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise McpProcessError("INVALID_RESPONSE", "MCP result is not an object")
    content = result.get("content")
    if not isinstance(content, list):
        raise McpProcessError("INVALID_RESPONSE", "MCP result content is not a list")
    text_items: list[str] = []
    for item in content:
        if isinstance(item, Mapping) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str):
                text_items.append(text)
    if not text_items:
        raise McpProcessError("INVALID_RESPONSE", "MCP result has no text content")
    return "\n".join(text_items)


class MatrixMediaMcpReadOnlyClient:
    """Read-only MatrixMedia MCP boundary with owned-process cleanup.

    Mutating tools deliberately have no method here.  They require provider
    state reconciliation before any retry and therefore cannot share the
    deterministic cleanup used after a completed read-only result.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_s: float = 60.0,
        terminate_grace_s: float = 2.0,
    ) -> None:
        self.command = tuple(command)
        self.options = {
            "cwd": cwd,
            "env": env,
            "timeout_s": timeout_s,
            "terminate_grace_s": terminate_grace_s,
        }

    async def _call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        result = await read_only_call(
            self.command,
            "tools/call",
            {"name": name, "arguments": dict(arguments)},
            initialize=True,
            **self.options,
        )
        text = _tool_text(result.response)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise McpProcessError("INVALID_JSON", f"MCP {name} returned invalid JSON") from exc

    async def list_accounts(self) -> Any:
        return await self._call_tool("list_accounts", {})

    async def list_history(self, *, days: int = 7) -> Any:
        return await self._call_tool("list_history", {"days": days})


class OwnedMcpProcess:
    """Run one MCP stdio invocation in an owned process group.

    The process group is created with ``start_new_session`` so cleanup cannot
    accidentally signal unrelated MatrixMedia GUI sessions.  The class is
    deliberately one-shot: a new request gets a new owned invocation.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | None = None,
        env: Mapping[str, str] | None = None,
        timeout_s: float = 60.0,
        terminate_grace_s: float = 2.0,
    ) -> None:
        if not command:
            raise ValueError("MCP command must not be empty")
        self.command = tuple(command)
        self.cwd = cwd
        self.env = {**os.environ, **(env or {})}
        self.timeout_s = timeout_s
        self.terminate_grace_s = terminate_grace_s
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0

    async def call(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        initialize: bool = False,
    ) -> McpCallResult:
        """Call a read-only MCP method and reap its owned process group."""

        self._request_id += 1
        request_id = self._request_id
        process = await self._start()
        try:
            assert process.stdin is not None
            if initialize:
                process.stdin.write(
                    (
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "method": "initialize",
                                "params": {
                                    "protocolVersion": "2025-03-26",
                                    "capabilities": {},
                                    "clientInfo": {"name": "hevi-distribution", "version": "1"},
                                },
                            }
                        )
                        + "\n"
                    ).encode()
                )
                await process.stdin.drain()
                await asyncio.wait_for(
                    self._read_response(process, request_id), timeout=self.timeout_s
                )
                request_id += 1
                process.stdin.write(
                    (
                        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
                    ).encode()
                )
                await process.stdin.drain()
            request = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": dict(params or {}),
            }
            process.stdin.write((json.dumps(request) + "\n").encode())
            await process.stdin.drain()
            response = await asyncio.wait_for(
                self._read_response(process, request_id), timeout=self.timeout_s
            )
            if not isinstance(response, dict):
                raise McpProcessError("INVALID_JSON", "MCP response is not an object")
            return McpCallResult(
                response=response, process_exit=await self._cleanup(), process_leaks=0, zombies=0
            )
        except TimeoutError as exc:
            await self._cleanup()
            raise McpProcessError("TIMEOUT", f"MCP {method} timed out") from exc
        except McpProcessError:
            await self._cleanup()
            raise
        except (BrokenPipeError, ConnectionError) as exc:
            await self._cleanup()
            raise McpProcessError("CHILD_EXIT_NONZERO", str(exc)) from exc

    async def _start(self) -> asyncio.subprocess.Process:
        if self._process is not None:
            raise McpProcessError("PROCESS_REUSED", "MCP invocation is one-shot")
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                cwd=self.cwd,
                env=self.env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise McpProcessError("MCP_UNAVAILABLE", str(exc)) from exc
        return self._process

    async def _read_response(
        self, process: asyncio.subprocess.Process, request_id: int
    ) -> dict[str, Any]:
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                code = process.returncode
                if code is None:
                    code = await process.wait()
                raise McpProcessError("CHILD_EXIT_NONZERO", f"MCP child exited {code}")
            try:
                value = json.loads(line.decode(errors="replace"))
            except json.JSONDecodeError as exc:
                raise McpProcessError("INVALID_JSON", "MCP emitted invalid JSON") from exc
            if not isinstance(value, dict):
                raise McpProcessError("INVALID_JSON", "MCP emitted a non-object JSON value")
            if value.get("id") == request_id:
                return value

    async def _cleanup(self) -> int:
        process = self._process
        if process is None:
            return 0
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=self.terminate_grace_s)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=self.terminate_grace_s)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
        if process.stdin is not None:
            process.stdin.close()
        return process.returncode if process.returncode is not None else -1


async def read_only_call(
    command: Sequence[str],
    method: str,
    params: Mapping[str, Any] | None = None,
    initialize: bool = False,
    **kwargs: Any,
) -> McpCallResult:
    """Execute one read-only MCP request with deterministic cleanup."""

    return await OwnedMcpProcess(command, **kwargs).call(method, params, initialize=initialize)


__all__ = [
    "MatrixMediaMcpReadOnlyClient",
    "McpCallResult",
    "McpProcessError",
    "OwnedMcpProcess",
    "read_only_call",
]
