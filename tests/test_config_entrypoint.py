"""P0-2: entrypoint import order + Settings configuration-exception semantics."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from hevi.core.config import Settings
from hevi.core.exceptions import ConfigurationError

REPO_ROOT = Path(__file__).resolve().parents[1]
STRONG_JWT = "unit-test-jwt-not-for-production-reuse-0123456789abcdef"

ENTRYPOINTS = (
    REPO_ROOT / "hevi/events/publisher_entrypoint.py",
    REPO_ROOT / "hevi/queue/worker_entrypoint.py",
    REPO_ROOT / "hevi/scheduler/entrypoint.py",
    REPO_ROOT / "hevi/provider_policy/health_entrypoint.py",
)


def _load_dotenv_before_settings(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    dotenv_lineno: int | None = None
    settings_lineno: int | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            func = node.value.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name == "load_dotenv":
                dotenv_lineno = node.lineno
        if isinstance(node, ast.ImportFrom) and node.module == "hevi.core.config":
            if any(a.name == "settings" for a in node.names):
                settings_lineno = node.lineno
        if isinstance(node, ast.Import) and any(a.name == "hevi.core.config" for a in node.names):
            settings_lineno = node.lineno
    if dotenv_lineno is None or settings_lineno is None:
        return False
    return dotenv_lineno < settings_lineno


def test_entrypoints_load_dotenv_before_settings() -> None:
    missing = [
        str(p.relative_to(REPO_ROOT)) for p in ENTRYPOINTS if not _load_dotenv_before_settings(p)
    ]
    assert not missing, f"load_dotenv() must precede hevi.core.config import: {missing}"


def test_settings_empty_jwt_raises_not_exits() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        Settings(app_env="development", jwt_secret="")
    assert "JWT_SECRET" in str(exc_info.value)
    assert not isinstance(exc_info.value, SystemExit)


def test_settings_production_weak_raises_not_exits() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        Settings(app_env="production", jwt_secret=STRONG_JWT)
    assert "PRODUCTION_WEAK_SECRET" in str(exc_info.value)
    assert not isinstance(exc_info.value, SystemExit)


def test_config_module_has_no_sys_exit() -> None:
    src = (REPO_ROOT / "hevi/core/config.py").read_text(encoding="utf-8")
    assert "sys.exit" not in src
    assert "ConfigurationError" in src


def test_publisher_entrypoint_main_exits_on_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "hevi.events.publisher_entrypoint_under_test",
        REPO_ROOT / "hevi/events/publisher_entrypoint.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)

        async def boom() -> None:
            raise ConfigurationError("FATAL: JWT_SECRET must be set in .env")

        monkeypatch.setattr(mod, "run", boom)
        with pytest.raises(SystemExit) as exc_info:
            mod.main()
        assert exc_info.value.code == 1
    finally:
        sys.modules.pop(spec.name, None)


def test_worker_entrypoint_import_order_is_load_dotenv_first() -> None:
    text = (REPO_ROOT / "hevi/queue/worker_entrypoint.py").read_text(encoding="utf-8")
    dotenv_at = text.index("load_dotenv()")
    settings_at = text.index("from hevi.core.config import settings")
    assert dotenv_at < settings_at


def test_subprocess_missing_jwt_exits_1_from_wrong_cwd(tmp_path: Path) -> None:
    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(REPO_ROOT),
        "JWT_SECRET": "",
        "APP_ENV": "development",
        "VIRTUAL_ENV": str(REPO_ROOT / ".venv"),
    }
    proc = subprocess.run(
        [
            str(REPO_ROOT / ".venv/bin/python"),
            "-c",
            "from hevi.core.config import Settings; Settings(jwt_secret='')",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=env,
        timeout=30,
    )
    assert proc.returncode != 0
    assert "JWT_SECRET" in (proc.stderr + proc.stdout)


def test_qualification_child_env_shape() -> None:
    root = REPO_ROOT / "scripts/qualification/non_gpu_runtime_qualify.py"
    text = root.read_text(encoding="utf-8")
    assert "_child_env" in text
    assert 'APP_ENV"] = "development"' in text or "APP_ENV'] = 'development'" in text
    assert "JWT_SECRET" in text
    # creative runtime Popen must pass env + cwd
    creative = (REPO_ROOT / "scripts/qualification/qualify_creative_runtime.py").read_text(
        encoding="utf-8"
    )
    assert "env=_child_env()" in creative
    assert "cwd=" in creative
