"""gen_engine worker 纯逻辑测试(不 import torch / cosyvoice, 只测可离线验证部分)。

f5_worker / cosy_worker 的推理路径依赖容器内 venv, 无法在 API 测试环境跑;
这里覆盖模型家族检测等确定性逻辑, 其余由 hevi-api 客户端测试 + 容器内 smoke 兜底。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from services.gen_engine.cosy_worker import _detect_family, _normalize_mode
from services.gen_engine.f5_worker import _resolve_checkpoint


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


def test_normalize_mode_aliases() -> None:
    assert _normalize_mode("Instruct") == "instruct"
    assert _normalize_mode("Cross-Lingual") == "cross_lingual"
    assert _normalize_mode("zero-shot") == "zero_shot"
    assert _normalize_mode("") == ""


def test_f5_resolve_checkpoint_falls_back(tmp_path: Path) -> None:
    ckpt, vocab, cfg = _resolve_checkpoint(tmp_path, "SWivid/F5-TTS_v1")
    assert ckpt.name == "model_1200000.safetensors"
    assert vocab.name == "vocab.txt"
    assert cfg["dim"] == 1024


def test_f5_resolve_checkpoint_uses_v1_when_present(tmp_path: Path) -> None:
    ckpt_dir = tmp_path / "F5TTS_v1_Base"
    ckpt_dir.mkdir()
    ckpt = ckpt_dir / "model_1250000.safetensors"
    vocab = ckpt_dir / "vocab.txt"
    ckpt.write_bytes(b"x")
    vocab.write_text("a", encoding="utf-8")
    got_ckpt, got_vocab, _cfg = _resolve_checkpoint(tmp_path, "SWivid/F5-TTS_v1")
    assert got_ckpt == ckpt
    assert got_vocab == vocab
