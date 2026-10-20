"""Contract tests for the novel pipeline capabilities (CAPABILITY_CONTRACT.md).

Offline: every LLM call goes through an injectable fake ``llm_fn`` that reads
the ``TARGET_CHARS=<n>`` / ``TOTAL_CHAPTERS=<n>`` markers out of the prompt
and returns fixed-length text, so word-count governance (expand / shrink /
no-op) and on-disk artefacts are verified with zero network and zero spend.
"""

import asyncio
import json
import re
from pathlib import Path

import pytest

import hevi.capabilities as caps
import hevi.capabilities.novelpipeline as novel_caps
from hevi.capabilities.errors import CapabilityError
from hevi.novelpipeline.core import (
    char_count,
    continue_work,
    create_novel,
    load_book,
    verify_book,
    write_chapter,
)

novel_caps.register_novelpipeline_capabilities_once()

NOVEL_NAMES = ("novel.create", "novel.write_chapter", "novel.continue_work")


class FakeLlm:
    """Deterministic llm_fn: JSON for planning kinds, marker-sized prose else."""

    def __init__(self, draft_ratio: float = 1.0, expand_ratio: float = 1.0) -> None:
        self.calls: list[str] = []
        self.draft_ratio = draft_ratio
        self.expand_ratio = expand_ratio

    def __call__(self, prompt: str, kind: str) -> str:
        self.calls.append(kind)
        if kind == "book_outline":
            total = int(re.search(r"TOTAL_CHAPTERS=(\d+)", prompt).group(1))
            return json.dumps(
                {
                    "title": "雾港来信",
                    "setting": {
                        "world": "雾港是一座常年起雾的海港城",
                        "rules": ["信件只能在退潮时寄出"],
                    },
                    "characters": [
                        {"name": "林晚", "role": "主角", "profile": "灯塔守夜人"},
                        {"name": "周屿", "role": "配角", "profile": "雾港邮差"},
                    ],
                    "outline": [
                        {"title": f"第{i}节", "summary": f"冲突推进到第{i}步"}
                        for i in range(1, total + 1)
                    ],
                },
                ensure_ascii=False,
            )
        if kind == "continue_setup":
            return json.dumps(
                {
                    "title": "雾港来信",
                    "genre": "悬疑",
                    "protagonist": "林晚",
                    "conflict": "林晚要查清无名信的来源",
                    "characters": [
                        {"name": "林晚", "role": "主角", "profile": "灯塔守夜人"},
                        {"name": "周屿", "role": "配角", "profile": "雾港邮差"},
                    ],
                },
                ensure_ascii=False,
            )
        if kind == "summary":
            return "上一章里, 林晚在退潮时收到了一封没有署名的信。"
        target = int(re.search(r"TARGET_CHARS=(\d+)", prompt).group(1))
        if kind == "chapter_body":
            return "字" * int(target * self.draft_ratio)
        if kind == "expand":
            return "字" * int(target * self.expand_ratio)
        if kind == "shrink":
            return "字" * target
        raise AssertionError(f"unexpected llm kind: {kind}")


@pytest.fixture(autouse=True)
def _reset_llm_fn(monkeypatch: pytest.MonkeyPatch):
    # Keep every test hermetic even on machines with a real key in the env:
    # the default Monid backend must only engage when a test opts in by
    # setting a fake MONID_API_KEY explicitly.
    monkeypatch.delenv("MONID_API_KEY", raising=False)
    novel_caps.set_llm_fn(None)
    yield
    novel_caps.set_llm_fn(None)


def _brief_kwargs(book_dir: Path) -> dict:
    return {
        "book_dir": book_dir,
        "genre": "悬疑",
        "protagonist": "林晚",
        "conflict": "林晚要查清无名信的来源",
        "total_chapters": 3,
        "chapter_target_chars": 1000,
    }


def _make_book(tmp_path: Path, fake: FakeLlm) -> Path:
    book_dir = tmp_path / "book"
    create_novel(llm_fn=fake, **_brief_kwargs(book_dir))
    return book_dir


# ---------------------------------------------------------------------------
# Registration / schema contract
# ---------------------------------------------------------------------------


def test_novel_capabilities_registered_and_listable() -> None:
    names = caps.names()
    for expected in NOVEL_NAMES:
        assert expected in names
    listed = [c.name for c in caps.list(kind="line")]
    for expected in NOVEL_NAMES:
        assert expected in listed


def test_novel_describe_has_params_schema() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    for expected in NOVEL_NAMES:
        assert expected in by_name
        assert by_name[expected].get("description"), expected
        assert by_name[expected].get("params_schema"), expected


def test_create_rejects_invalid_params(tmp_path: Path) -> None:
    cap = caps.get("novel.create")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, tmp_path / "o", duration=1.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):  # total_chapters below schema minimum
        cap.render_safe(
            {
                "book_dir": str(tmp_path / "b"),
                "genre": "悬疑",
                "protagonist": "林晚",
                "conflict": "冲突",
                "total_chapters": 0,
            },
            tmp_path / "o",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    with pytest.raises(CapabilityError):  # additionalProperties: False
        cap.render_safe(
            {
                "book_dir": str(tmp_path / "b"),
                "genre": "悬疑",
                "protagonist": "林晚",
                "conflict": "冲突",
                "total_chapters": 3,
                "bogus": 1,
            },
            tmp_path / "o",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )


def test_continue_rejects_missing_text(tmp_path: Path) -> None:
    cap = caps.get("novel.continue_work")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"book_dir": str(tmp_path / "b")},
            tmp_path / "o",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )


def test_missing_llm_surfaces_as_capability_error(tmp_path: Path) -> None:
    cap = caps.get("novel.create")
    with pytest.raises(CapabilityError) as excinfo:
        cap.render_safe(
            {
                "book_dir": str(tmp_path / "b"),
                "genre": "悬疑",
                "protagonist": "林晚",
                "conflict": "冲突",
                "total_chapters": 3,
            },
            tmp_path / "o",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    assert "llm" in str(excinfo.value).lower()
    # The error must name BOTH fallbacks: the injection point and the
    # default Monid backend's missing key.
    assert "set_llm_fn" in str(excinfo.value)
    assert "MONID_API_KEY" in str(excinfo.value)


# ---------------------------------------------------------------------------
# novel.create (core)
# ---------------------------------------------------------------------------


def test_create_writes_complete_book_structure(tmp_path: Path) -> None:
    fake = FakeLlm()
    book_dir = tmp_path / "book"
    book = create_novel(llm_fn=fake, **_brief_kwargs(book_dir))

    assert book["title"] == "雾港来信"
    assert book["setting"]["world"]
    assert [c["name"] for c in book["characters"]] == ["林晚", "周屿"]
    assert len(book["outline"]) == 3
    assert book["outline"][0]["chapter"] == 1
    assert book["total_chapters"] == 3
    assert book["chapter_target_chars"] == 1000
    assert book["progress"] == {"completed": [], "next_chapter": 1, "status": "created"}
    assert "facts" in book["continuity"]

    on_disk = json.loads((book_dir / "book.json").read_text(encoding="utf-8"))
    assert on_disk == book
    assert (book_dir / "chapters").is_dir()
    assert fake.calls == ["book_outline"]


def test_create_rejects_bad_brief(tmp_path: Path) -> None:
    fake = FakeLlm()
    kwargs = _brief_kwargs(tmp_path / "b1")
    kwargs["genre"] = "  "
    with pytest.raises(CapabilityError):
        create_novel(llm_fn=fake, **kwargs)
    kwargs = _brief_kwargs(tmp_path / "b2")
    kwargs["total_chapters"] = 0
    with pytest.raises(CapabilityError):
        create_novel(llm_fn=fake, **kwargs)
    kwargs = _brief_kwargs(tmp_path / "b3")
    kwargs["chapter_target_chars"] = 50
    with pytest.raises(CapabilityError):
        create_novel(llm_fn=fake, **kwargs)
    with pytest.raises(CapabilityError):  # no llm injected
        create_novel(llm_fn=None, **_brief_kwargs(tmp_path / "b4"))


# ---------------------------------------------------------------------------
# novel.write_chapter + word-count governance
# ---------------------------------------------------------------------------


def test_write_chapter_on_target_no_governance_round(tmp_path: Path) -> None:
    fake = FakeLlm(draft_ratio=1.0)
    book_dir = _make_book(tmp_path, fake)
    fake.calls.clear()

    result = write_chapter(book_dir=book_dir, llm_fn=fake)

    assert result["chapter"] == 1
    assert result["governance"] == "none"
    assert result["final_chars"] == 1000
    assert result["rounds"] == [{"kind": "draft", "chars": 1000}]
    assert fake.calls == ["chapter_body"]

    chapter_file = Path(result["path"])
    assert chapter_file.is_file()
    assert char_count(chapter_file.read_text(encoding="utf-8").split("-->", 1)[1]) >= 1000
    assert Path(result["analysis_path"]).is_file()

    book = load_book(book_dir)
    assert book["progress"]["completed"] == [1]
    assert book["progress"]["next_chapter"] == 2
    assert book["progress"]["status"] == "writing"
    assert book["chapters"][0]["governance"] == "none"


def test_write_chapter_within_tolerance_no_round(tmp_path: Path) -> None:
    fake = FakeLlm(draft_ratio=0.85)  # -15%, inside the ±20% band
    book_dir = _make_book(tmp_path, fake)
    fake.calls.clear()
    result = write_chapter(book_dir=book_dir, llm_fn=fake)
    assert result["governance"] == "none"
    assert result["final_chars"] == 850
    assert fake.calls == ["chapter_body"]


def test_write_chapter_too_short_expands_exactly_once(tmp_path: Path) -> None:
    fake = FakeLlm(draft_ratio=0.5)
    book_dir = _make_book(tmp_path, fake)
    fake.calls.clear()

    result = write_chapter(book_dir=book_dir, llm_fn=fake)

    assert result["governance"] == "expanded"
    assert [r["kind"] for r in result["rounds"]] == ["draft", "expand"]
    assert result["rounds"][0]["chars"] == 500
    assert result["final_chars"] == 1000
    assert fake.calls == ["chapter_body", "expand"]


def test_write_chapter_expand_is_capped_at_one_round(tmp_path: Path) -> None:
    # Even when the expand round is STILL too short, no second round may run.
    fake = FakeLlm(draft_ratio=0.5, expand_ratio=0.5)
    book_dir = _make_book(tmp_path, fake)
    fake.calls.clear()
    result = write_chapter(book_dir=book_dir, llm_fn=fake)
    assert result["governance"] == "expanded"
    assert len(result["rounds"]) == 2
    assert fake.calls.count("expand") == 1


def test_write_chapter_too_long_shrinks_exactly_once(tmp_path: Path) -> None:
    fake = FakeLlm(draft_ratio=1.5)
    book_dir = _make_book(tmp_path, fake)
    fake.calls.clear()

    result = write_chapter(book_dir=book_dir, llm_fn=fake)

    assert result["governance"] == "shrunk"
    assert [r["kind"] for r in result["rounds"]] == ["draft", "shrink"]
    assert result["rounds"][0]["chars"] == 1500
    assert result["final_chars"] == 1000
    assert fake.calls == ["chapter_body", "shrink"]


def test_write_second_chapter_uses_prev_summary(tmp_path: Path) -> None:
    fake = FakeLlm()
    book_dir = _make_book(tmp_path, fake)
    write_chapter(book_dir=book_dir, llm_fn=fake)
    fake.calls.clear()

    result = write_chapter(book_dir=book_dir, llm_fn=fake)

    assert result["chapter"] == 2
    assert fake.calls[0] == "summary"  # 写前分析先摘要上一章
    analysis = json.loads(Path(result["analysis_path"]).read_text(encoding="utf-8"))
    assert analysis["prev_chapter_summary"]
    assert analysis["intent"]
    book = load_book(book_dir)
    assert book["progress"]["completed"] == [1, 2]
    assert book["progress"]["next_chapter"] == 3


def test_write_chapter_rejects_missing_book_and_bad_chapter(tmp_path: Path) -> None:
    fake = FakeLlm()
    with pytest.raises(CapabilityError):
        write_chapter(book_dir=tmp_path / "nope", llm_fn=fake)
    book_dir = _make_book(tmp_path, fake)
    with pytest.raises(CapabilityError):
        write_chapter(book_dir=book_dir, llm_fn=fake, chapter=99)
    with pytest.raises(CapabilityError):
        write_chapter(book_dir=book_dir, llm_fn=None)


def test_verify_book_fails_after_artefact_deleted(tmp_path: Path) -> None:
    fake = FakeLlm()
    book_dir = _make_book(tmp_path, fake)
    result = write_chapter(book_dir=book_dir, llm_fn=fake)
    assert verify_book(book_dir)["ok"] is True

    Path(result["path"]).unlink()
    with pytest.raises(CapabilityError):
        verify_book(book_dir)


# ---------------------------------------------------------------------------
# novel.continue_work
# ---------------------------------------------------------------------------

IMPORTED_TEXT = (
    "第一章 灯塔\n"
    "林晚在灯塔上值夜, 海雾漫过礁石, 她擦亮了灯罩, 又把值班簿翻到新的一页。\n"
    "第二章 来信\n"
    "退潮的时候, 她在沙滩上捡到一个漂流瓶, 瓶里塞着一封没有署名的信。\n"
    "第三章 雾起\n"
    "大雾封了港, 信里的地址指向港尾的旧仓库, 林晚决定天亮就去看看。\n"
)


def test_continue_work_splits_and_writes_from_breakpoint(tmp_path: Path) -> None:
    fake = FakeLlm()
    book_dir = tmp_path / "imported"

    result = continue_work(
        book_dir=book_dir, text=IMPORTED_TEXT, llm_fn=fake, chapter_target_chars=1000
    )

    assert result["imported_chapters"] == 3
    assert result["new_chapter"]["chapter"] == 4
    assert result["new_chapter"]["governance"] == "none"
    assert result["new_chapter"]["final_chars"] == 1000

    # Imported chapters preserved on disk, new chapter written after them.
    for i in (1, 2, 3, 4):
        assert (book_dir / "chapters" / f"chapter_{i:03d}.md").is_file()
    imported_1 = (book_dir / "chapters" / "chapter_001.md").read_text(encoding="utf-8")
    assert "漂流瓶" not in imported_1 and "灯塔上值夜" in imported_1

    # Continuation context: last-chapter summary + character table.
    continuation = json.loads(Path(result["continuation_path"]).read_text(encoding="utf-8"))
    assert continuation["imported_chapters"] == 3
    assert continuation["last_chapter"] == 3
    assert continuation["last_chapter_summary"]
    assert [c["name"] for c in continuation["characters"]] == ["林晚", "周屿"]

    book = load_book(book_dir)
    assert book["created_from"] == "import"
    assert book["total_chapters"] == 4
    assert book["progress"]["completed"] == [1, 2, 3, 4]
    assert book["progress"]["status"] == "complete"
    sources = {e["chapter"]: e["source"] for e in book["chapters"]}
    assert sources == {1: "imported", 2: "imported", 3: "imported", 4: "generated"}
    assert verify_book(book_dir)["ok"] is True


def test_continue_work_rejects_empty_text_and_existing_book(tmp_path: Path) -> None:
    fake = FakeLlm()
    with pytest.raises(CapabilityError):
        continue_work(book_dir=tmp_path / "b", text="   ", llm_fn=fake)
    with pytest.raises(CapabilityError):
        continue_work(book_dir=tmp_path / "b", text=IMPORTED_TEXT, llm_fn=None)
    book_dir = tmp_path / "b2"
    continue_work(book_dir=book_dir, text=IMPORTED_TEXT, llm_fn=fake)
    with pytest.raises(CapabilityError):  # never overwrite an existing book
        continue_work(book_dir=book_dir, text=IMPORTED_TEXT, llm_fn=fake)


# ---------------------------------------------------------------------------
# Capability-level end-to-end (injected llm_fn)
# ---------------------------------------------------------------------------


def test_capability_end_to_end_create_and_write(tmp_path: Path) -> None:
    fake = FakeLlm(draft_ratio=0.5)  # short drafts: capability must expand once
    novel_caps.set_llm_fn(fake)
    book_dir = tmp_path / "capbook"

    create_result = caps.get("novel.create").render_safe(
        {
            "book_dir": str(book_dir),
            "genre": "悬疑",
            "protagonist": "林晚",
            "conflict": "林晚要查清无名信的来源",
            "total_chapters": 3,
            "chapter_target_chars": 1000,
        },
        tmp_path / "job1",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert create_result.qa["title"] == "雾港来信"
    assert create_result.sha256
    assert (book_dir / "book.json").is_file()

    write_result = caps.get("novel.write_chapter").render_safe(
        {"book_dir": str(book_dir)},
        tmp_path / "job2",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert write_result.qa["governance"] == "expanded"
    assert write_result.qa["final_chars"] == 1000
    chapter_path = Path(write_result.qa["chapter_path"])
    assert chapter_path.is_file()

    chapter_path.unlink()
    assert not chapter_path.exists(), "contract: deleting the artifact must break verification"
    with pytest.raises(CapabilityError):
        verify_book(book_dir)


def test_capability_continue_work_end_to_end(tmp_path: Path) -> None:
    novel_caps.set_llm_fn(FakeLlm())
    book_dir = tmp_path / "capimport"
    result = caps.get("novel.continue_work").render_safe(
        {"book_dir": str(book_dir), "text": IMPORTED_TEXT, "chapter_target_chars": 1000},
        tmp_path / "job3",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert result.qa["imported_chapters"] == 3
    assert result.qa["new_chapter"]["chapter"] == 4
    assert Path(result.qa["continuation_json"]).is_file()
    assert result.sha256


# ---------------------------------------------------------------------------
# Default Monid backend (no injection; fake key + patched transport)
# ---------------------------------------------------------------------------


def _outline_json_from_prompt(prompt: str) -> str:
    total = int(re.search(r"TOTAL_CHAPTERS=(\d+)", prompt).group(1))
    return json.dumps(
        {
            "title": "雾港来信",
            "setting": {
                "world": "雾港是一座常年起雾的海港城",
                "rules": ["信件只能在退潮时寄出"],
            },
            "characters": [
                {"name": "林晚", "role": "主角", "profile": "灯塔守夜人"},
                {"name": "周屿", "role": "配角", "profile": "雾港邮差"},
            ],
            "outline": [
                {"title": f"第{i}节", "summary": f"冲突推进到第{i}步"}
                for i in range(1, total + 1)
            ],
        },
        ensure_ascii=False,
    )


def test_default_backend_used_when_key_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No injection + MONID_API_KEY set -> hevi.llm.monid_chat drives it."""
    from hevi.llm import monid_chat

    fake = FakeLlm()
    monkeypatch.setenv("MONID_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(monid_chat, "chat_for_kind_sync", fake)

    book_dir = tmp_path / "defaultbook"
    result = caps.get("novel.create").render_safe(
        {
            "book_dir": str(book_dir),
            "genre": "悬疑",
            "protagonist": "林晚",
            "conflict": "林晚要查清无名信的来源",
            "total_chapters": 3,
            "chapter_target_chars": 1000,
        },
        tmp_path / "job-default",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert result.qa["title"] == "雾港来信"
    assert (book_dir / "book.json").is_file()
    assert fake.calls == ["book_outline"]


def test_default_backend_end_to_end_write_chapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.llm import monid_chat

    fake = FakeLlm(draft_ratio=1.0)
    monkeypatch.setenv("MONID_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(monid_chat, "chat_for_kind_sync", fake)

    book_dir = tmp_path / "defaultbook2"
    caps.get("novel.create").render_safe(
        {
            "book_dir": str(book_dir),
            "genre": "悬疑",
            "protagonist": "林晚",
            "conflict": "林晚要查清无名信的来源",
            "total_chapters": 3,
            "chapter_target_chars": 1000,
        },
        tmp_path / "job-d1",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    write_result = caps.get("novel.write_chapter").render_safe(
        {"book_dir": str(book_dir)},
        tmp_path / "job-d2",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert write_result.qa["governance"] == "none"
    assert write_result.qa["final_chars"] == 1000
    assert "chapter_body" in fake.calls


def test_default_backend_transport_is_monid_chat_route(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Full chain: capability -> monid_chat -> monid_client.run_endpoint.

    Pins the storyfilm-identical route: provider blockrun.ai, endpoint
    /api/v1/chat/completions, model gpt-4o-mini.
    """
    from hevi.audio import monid_client

    seen: dict = {}

    async def fake_run_endpoint(provider, endpoint, *, body=None, **_kwargs):
        seen["provider"] = provider
        seen["endpoint"] = endpoint
        seen["body"] = body
        prompt = body["messages"][-1]["content"]
        return (
            {"choices": [{"message": {"content": _outline_json_from_prompt(prompt)}}]},
            0.0011,
        )

    monkeypatch.setenv("MONID_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(monid_client, "run_endpoint", fake_run_endpoint)

    book_dir = tmp_path / "transportbook"
    result = caps.get("novel.create").render_safe(
        {
            "book_dir": str(book_dir),
            "genre": "悬疑",
            "protagonist": "林晚",
            "conflict": "林晚要查清无名信的来源",
            "total_chapters": 3,
            "chapter_target_chars": 1000,
        },
        tmp_path / "job-transport",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert result.qa["title"] == "雾港来信"
    assert seen["provider"] == "blockrun.ai"
    assert seen["endpoint"] == "/api/v1/chat/completions"
    assert seen["body"]["model"] == "gpt-4o-mini"


def test_injected_llm_fn_wins_over_default_backend(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from hevi.llm import monid_chat

    def forbidden_default(prompt: str, kind: str) -> str:
        raise AssertionError("default backend must not run when injected")

    monkeypatch.setenv("MONID_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(monid_chat, "chat_for_kind_sync", forbidden_default)
    novel_caps.set_llm_fn(FakeLlm())

    book_dir = tmp_path / "injectedbook"
    result = caps.get("novel.create").render_safe(
        {
            "book_dir": str(book_dir),
            "genre": "悬疑",
            "protagonist": "林晚",
            "conflict": "林晚要查清无名信的来源",
            "total_chapters": 3,
            "chapter_target_chars": 1000,
        },
        tmp_path / "job-injected",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert result.qa["title"] == "雾港来信"


def test_default_llm_fn_sync_facade_inside_running_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default llm_fn must work while an event loop is running."""
    from hevi.audio import monid_client

    async def fake_run_endpoint(provider, endpoint, *, body=None, **_kwargs):
        return ({"choices": [{"message": {"content": "摘要内容。"}}]}, 0.0003)

    monkeypatch.setenv("MONID_API_KEY", "fake-key-for-tests")
    monkeypatch.setattr(monid_client, "run_endpoint", fake_run_endpoint)

    async def _call_from_loop() -> str:
        # Synchronous call while this thread's loop is running: the facade
        # must offload to a fresh thread/loop instead of deadlocking.
        return novel_caps._default_llm_fn("任意 prompt", "summary")

    assert asyncio.run(_call_from_loop()) == "摘要内容。"
