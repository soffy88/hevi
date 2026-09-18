"""W9 gates: scoped memory over the real HEVI store, precedence, safety."""

from __future__ import annotations

import pytest

from hevi.creative.layer4.creative_memory import (
    CreativeMemory,
    MemoryError,
    MemorySource,
    check_memory_safety,
)
from hevi.memory.store import MemoryStore


def _memory(tmp_path, name: str = "mem.db") -> CreativeMemory:
    return CreativeMemory(MemoryStore(tmp_path / name))


def test_remember_and_inspect_scopes(tmp_path) -> None:
    memory = _memory(tmp_path)
    memory.remember(scope="user", key="subtitle_style", content="双语,白色黑边")
    memory.remember(scope="project:proj-a", key="pacing", content="快节奏竖屏", project_id="proj-a")
    user_entries = memory.inspect(scope="user")
    assert [e.entry_key for e in user_entries] == ["subtitle_style"]
    project_entries = memory.inspect(scope="project:proj-a", project_id="proj-a")
    assert [e.entry_key for e in project_entries] == ["pacing"]
    other = memory.inspect(scope="project:proj-b", project_id="proj-b")
    assert other == ()


def test_cross_session_recall(tmp_path) -> None:
    """CROSS_SESSION_RECALL: a new instance over the same SQLite recalls."""

    first = _memory(tmp_path)
    first.remember(scope="user", key="visual_style", content="电影感暗调", session_id="s1")
    first.remember(
        scope="project:proj-a",
        key="pacing",
        content="慢节奏横屏",
        project_id="proj-a",
        session_id="s1",
    )
    second = _memory(tmp_path)  # new session, same store file
    hits = second.recall_for_project("proj-a", "visual style pacing")
    keys = {hit.entry_key for hit in hits}
    assert "visual_style" in keys
    assert "pacing" in keys
    other_project = second.recall_for_project("proj-b", "pacing")
    assert all(hit.scope == "user" for hit in other_project)


def test_project_convention_recall_and_precedence(tmp_path) -> None:
    """PROJECT_CONVENTION_RECALL + PRECEDENCE: instruction > convention > pref."""

    memory = _memory(tmp_path)
    memory.remember(scope="user", key="pacing", content="用户偏好快节奏")
    memory.remember(
        scope="project:proj-a", key="pacing", content="本项目慢节奏", project_id="proj-a"
    )
    resolved = memory.resolve("proj-a")
    pacing = next(r for r in resolved if r.entry_key == "pacing")
    assert pacing.content == "本项目慢节奏"
    assert pacing.source is MemorySource.PROJECT_CONVENTION
    with_instruction = memory.resolve("proj-a", instruction="这次要超快节奏")
    assert with_instruction[-1].source is MemorySource.INSTRUCTION
    assert with_instruction[-1].content == "这次要超快节奏"
    # shadowed user row stays stored and inspectable
    assert any(e.content == "用户偏好快节奏" for e in memory.inspect(scope="user"))


def test_memory_edit_and_disable(tmp_path) -> None:
    """MEMORY_EDIT: edits append newer rows; disable tombstones recall."""

    memory = _memory(tmp_path)
    memory.remember(scope="user", key="naming", content="旧约定")
    memory.edit(scope="user", key="naming", content="新约定")
    entries = memory.inspect(scope="user")
    assert [e.content for e in entries if e.entry_key == "naming"] == ["新约定"]
    memory.disable(scope="user", key="naming")
    assert memory.inspect(scope="user") == ()
    hidden = memory.inspect(scope="user", include_disabled=True)
    assert hidden[0].disabled is True
    assert memory.resolve("proj-a") == ()


def test_pii_memory_gate(tmp_path) -> None:
    """PII_MEMORY_GATE: secrets/PII refuse before any write."""

    memory = _memory(tmp_path)
    with pytest.raises(MemoryError, match="MEMORY_SECRET_REFUSED"):
        memory.remember(scope="user", key="k", content="api_key: SECRET123")
    with pytest.raises(MemoryError, match="MEMORY_SECRET_REFUSED"):
        memory.remember(scope="user", key="k", content="token sk-abcdefgh12345678")
    with pytest.raises(MemoryError, match="MEMORY_PII_REFUSED"):
        memory.remember(scope="user", key="k", content="联系 zhang@example.com")
    with pytest.raises(MemoryError, match="MEMORY_PII_REFUSED"):
        memory.remember(scope="user", key="k", content="电话 13800138000")
    with pytest.raises(MemoryError, match="MEMORY_PII_REFUSED"):
        memory.remember(scope="user", key="k", content="身份证 110105199001011234")
    assert memory.inspect(scope="user") == ()
    check_memory_safety("纯偏好内容")


def test_scope_validation(tmp_path) -> None:
    memory = _memory(tmp_path)
    with pytest.raises(MemoryError, match="MEMORY_SCOPE_UNKNOWN"):
        memory.remember(scope="global", key="k", content="x")
    with pytest.raises(MemoryError, match="MEMORY_PROJECT_SCOPE_NEEDS_PROJECT_ID"):
        memory.remember(scope="project:proj-a", key="k", content="x")
    with pytest.raises(MemoryError, match="MEMORY_KEY_EMPTY"):
        memory.remember(scope="user", key="  ", content="x")


def test_integration_uses_real_hevi_store(tmp_path) -> None:
    """Runtime integration evidence: real MemoryStore class + SQLite + recall."""

    from hevi.memory.store import MemoryStore as RealStore

    memory = _memory(tmp_path)
    assert isinstance(memory._store, RealStore)
    memory.remember(scope="user", key="provider", content="偏好本地引擎")
    assert memory._store.count() >= 1
    assert memory._store.by_key("user-pref:provider")
