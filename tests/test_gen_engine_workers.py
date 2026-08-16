"""gen_engine worker 纯逻辑测试(不 import torch / cosyvoice, 只测可离线验证部分)。

f5_worker / cosy_worker 的推理路径依赖容器内 venv, 无法在 API 测试环境跑;
这里覆盖模型家族检测等确定性逻辑, 其余由 hevi-api 客户端测试 + 容器内 smoke 兜底。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.gen_engine.cosy_worker import _detect_family


def test_detect_family_cosyvoice3(tmp_path: Path) -> None:
    (tmp_path / "cosyvoice3.yaml").write_text("x", encoding="utf-8")
    (tmp_path / "cosyvoice2.yaml").write_text("x", encoding="utf-8")
    assert _detect_family(tmp_path) == "cosyvoice3"  # v3 优先


def test_detect_family_cosyvoice2(tmp_path: Path) -> None:
    (tmp_path / "cosyvoice2.yaml").write_text("x", encoding="utf-8")
    assert _detect_family(tmp_path) == "cosyvoice2"


def test_detect_family_old_layout_raises_actionable(tmp_path: Path) -> None:
    """旧版 cosyvoice.yaml 布局(生产宿主机现状)必须给出可执行报错。"""
    (tmp_path / "cosyvoice.yaml").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="cosyvoice2.yaml"):
        _detect_family(tmp_path)


def test_detect_family_empty_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cosyvoice2.yaml"):
        _detect_family(tmp_path)
