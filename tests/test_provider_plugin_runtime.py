from __future__ import annotations

import sys

from hevi.providers.plugin_config import ProviderDecl, invoke_declared_provider


def test_declared_provider_can_run_isolated_json_command() -> None:
    decl = ProviderDecl(
        id="test-json-provider",
        tool="video/shot",
        meta={
            "command": [
                sys.executable,
                "-c",
                "import json,sys; p=json.load(sys.stdin); print(json.dumps({'status':'ok','echo':p['x']}))",
            ]
        },
    )
    result = invoke_declared_provider(decl, {"x": "verified"})
    assert result == {"status": "ok", "echo": "verified"}
