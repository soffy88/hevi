from __future__ import annotations

import asyncio
import contextlib
import os
import sys

import pytest

from hevi.distribution.mcp_process import McpProcessError, read_only_call


def _child(code: str) -> tuple[str, str, str]:
    return (sys.executable, "-u", "-c", code)


def test_mcp_accounts_returns_and_exits() -> None:
    result = asyncio.run(
        read_only_call(
            _child(
                "import json,sys,time; "
                "json.loads(sys.stdin.readline()); "
                "print(json.dumps({'jsonrpc':'2.0','id':1,'result':{'accounts':[]}}), flush=True); "
                "time.sleep(30)"
            ),
            "tools/call",
        )
    )
    assert result.response["result"] == {"accounts": []}
    assert result.process_exit < 0
    assert result.process_leaks == 0
    assert result.zombies == 0


def test_mcp_history_returns_and_exits() -> None:
    result = asyncio.run(
        read_only_call(
            _child(
                "import json,sys,time; "
                "json.loads(sys.stdin.readline()); "
                "print(json.dumps({'jsonrpc':'2.0','id':1,'result':{'history':[]}}), flush=True); "
                "time.sleep(30)"
            ),
            "tools/call",
        )
    )
    assert result.response["result"] == {"history": []}
    assert result.process_leaks == 0
    assert result.zombies == 0


def test_mcp_invalid_json_fails_closed() -> None:
    with pytest.raises(McpProcessError, match="invalid JSON"):
        asyncio.run(
            read_only_call(
                _child("import sys; sys.stdin.readline(); print('not-json', flush=True)"),
                "tools/call",
            )
        )


def test_mcp_timeout_cleans_owned_processes() -> None:
    with pytest.raises(McpProcessError, match="timed out"):
        asyncio.run(
            read_only_call(
                _child("import sys,time; sys.stdin.readline(); time.sleep(30)"),
                "tools/call",
                timeout_s=0.05,
                terminate_grace_s=0.05,
            )
        )


def test_mcp_child_exit_nonzero_fails() -> None:
    with pytest.raises(McpProcessError, match="exited"):
        asyncio.run(
            read_only_call(
                _child("import sys; sys.stdin.readline(); sys.exit(7)"),
                "tools/call",
            )
        )


def test_mcp_does_not_kill_unowned_process() -> None:
    marker = "/tmp/hevi-unowned-mcp-marker"
    with contextlib.suppress(FileNotFoundError):
        os.unlink(marker)
    child = asyncio.run(
        read_only_call(
            _child(
                "import json,sys,time,pathlib; "
                f"pathlib.Path({marker!r}).write_text('alive'); "
                "json.loads(sys.stdin.readline()); "
                "print(json.dumps({'jsonrpc':'2.0','id':1,'result':{}}), flush=True); "
                "time.sleep(30)"
            ),
            "tools/call",
        )
    )
    assert child.process_leaks == 0
    assert os.path.exists(marker)
    os.unlink(marker)


def test_mcp_no_zombie_after_success() -> None:
    result = asyncio.run(
        read_only_call(
            _child(
                "import sys,json; json.loads(sys.stdin.readline()); print(json.dumps({'id':1}), flush=True)"
            ),
            "tools/call",
        )
    )
    assert result.process_leaks == 0
    assert result.zombies == 0


def test_mcp_no_zombie_after_timeout() -> None:
    with pytest.raises(McpProcessError):
        asyncio.run(
            read_only_call(
                _child("import sys,time; sys.stdin.readline(); time.sleep(30)"),
                "tools/call",
                timeout_s=0.05,
                terminate_grace_s=0.05,
            )
        )
