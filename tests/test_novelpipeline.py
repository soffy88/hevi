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
    check_chapter,
    continue_work,
    create_novel,
    dialogue_stats,
    load_book,
    split_chapter_by_beats,
    verify_book,
    write_chapter,
)

novel_caps.register_novelpipeline_capabilities_once()

NOVEL_NAMES = ("novel.create", "novel.write_chapter", "novel.continue_work")


def _filler(n: int, dialogue_ratio: float = 0.5) -> str:
    """Exactly ``n`` non-whitespace chars with the given dialogue share.

    Dialogue = quoted inner chars; quotes themselves count toward the
    total, so narrative = n - dialogue_inner - 2.
    """
    if n <= 0:
        return ""
    d = int(round(n * dialogue_ratio))
    narrative = n - d - 2
    if narrative < 0:
        d = max(0, n - 2)
        narrative = n - d - 2
    return "“" + "话" * d + "”" + "叙" * narrative


class FakeLlm:
    """Deterministic llm_fn: JSON for planning kinds, marker-sized prose else.

    Prose is dialogue-rich (50% quoted) so the default 45-58% dialogue
    gate passes unless a test opts into a low-dialogue script.
    """

    def __init__(
        self,
        draft_ratio: float = 1.0,
        expand_ratio: float = 1.0,
        expand_ratios: list[float] | None = None,
        repair_ratio: float = 1.0,
    ) -> None:
        self.calls: list[str] = []
        self.draft_ratio = draft_ratio
        self.expand_ratio = expand_ratio
        self.expand_ratios = list(expand_ratios or [])
        self.repair_ratio = repair_ratio

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
        if kind == "segment_continue":
            need = int(re.search(r"CONTINUE_NEED_CHARS=(\d+)", prompt).group(1))
            return _filler(need)
        if kind in ("segment_expand", "segment_dialogue"):
            budget = int(re.search(r"SEGMENT_TARGET_CHARS=(\d+)", prompt).group(1))
            ratio = self.expand_ratios.pop(0) if self.expand_ratios else self.expand_ratio
            return _filler(int(budget * ratio))
        target = int(re.search(r"TARGET_CHARS=(\d+)", prompt).group(1))
        if kind == "chapter_body":
            return _filler(int(target * self.draft_ratio))
        if kind == "expand":
            ratio = self.expand_ratios.pop(0) if self.expand_ratios else self.expand_ratio
            return _filler(int(target * ratio))
        if kind == "shrink":
            return _filler(target)
        if kind == "repair":
            return _filler(int(target * self.repair_ratio))
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
    assert result["rounds"] == [
        {"kind": "draft", "chars": 1000, "dialogue_ratio": 0.5, "attempts": 1}
    ]
    assert result["in_tolerance"] is True
    assert result["dialogue_ratio"] == 0.5
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
    # Structure fix: a short chapter no longer gets a full-rewrite expand;
    # it gets one segmented-expansion round (one segment, budget = target).
    fake = FakeLlm(draft_ratio=0.5)
    book_dir = _make_book(tmp_path, fake)
    fake.calls.clear()

    result = write_chapter(book_dir=book_dir, llm_fn=fake)

    assert result["governance"] == "segment_expanded"
    assert [r["kind"] for r in result["rounds"]] == ["draft", "segment_expand"]
    assert result["rounds"][0]["chars"] == 500
    assert result["final_chars"] == 1000
    assert result["rounds"][1]["segment_budgets"] == [1000]
    assert fake.calls == ["chapter_body", "segment_expand"]


def test_write_chapter_expand_capped_blocks_instead_of_silent_delivery(
    tmp_path: Path,
) -> None:
    # Segmented rounds still too short after the cap (even the forward
    # continuation stays short): no silent delivery.  The draft is
    # quarantined, progress is untouched, and exactly the capped number
    # of governance rounds ran.
    fake = ScriptedFake(
        {
            "chapter_body": [_filler(500)],
            "segment_expand": [_filler(500)] * 3,
            "segment_continue": [_filler(100)] * 3,
        }
    )
    book_dir = _make_book(tmp_path, fake)
    fake.calls.clear()
    with pytest.raises(CapabilityError) as excinfo:
        write_chapter(book_dir=book_dir, llm_fn=fake, max_governance_rounds=3)
    assert "blocked" in str(excinfo.value)
    assert fake.calls.count("segment_expand") == 3
    assert fake.calls.count("segment_continue") == 3  # once per round, not per retry
    assert (book_dir / "chapters" / "chapter_001.quarantine.md").is_file()
    assert not (book_dir / "chapters" / "chapter_001.md").is_file()
    assert load_book(book_dir)["progress"]["completed"] == []


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
    assert write_result.qa["governance"] == "segment_expanded"
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


# ---------------------------------------------------------------------------
# Governance fixes (probe failures): multi-round, beats, dialogue,
# anti-fabrication, title/scene, backup, retry
# ---------------------------------------------------------------------------


class ScriptedFake(FakeLlm):
    """FakeLlm with per-kind scripted outputs (str) or errors to raise."""

    def __init__(self, scripts: dict, **kwargs) -> None:
        super().__init__(**kwargs)
        self.scripts = {k: list(v) for k, v in scripts.items()}

    def __call__(self, prompt: str, kind: str) -> str:
        if kind in self.scripts and self.scripts[kind]:
            self.calls.append(kind)
            item = self.scripts[kind].pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return super().__call__(prompt, kind)


def test_dialogue_stats_counts_quoted_text() -> None:
    stats = dialogue_stats("“你好。”她说。叙述叙述。")
    assert stats["dialogue_chars"] == 3  # 你好。
    assert stats["total_chars"] == char_count("“你好。”她说。叙述叙述。")
    assert 0 < stats["ratio"] < 1


def test_check_chapter_beat_coverage() -> None:
    beat = "手稿本三处线条对不上"
    missing = check_chapter(_filler(1000), target=1000, beats=[beat])
    assert beat in missing["missing_beats"]
    assert missing["passed"] is False
    present = check_chapter(
        "手稿上的三处线条对不上。" + _filler(1000), target=1000, beats=[beat]
    )
    assert present["missing_beats"] == []
    # Explicit anchors: half the anchors must appear.
    anchored = check_chapter(
        _filler(1000), target=1000,
        beats=[{"beat": "验稿", "anchors": ["手稿", "线条"], "min_anchors": 2}],
    )
    assert anchored["missing_beats"] == ["验稿"]


def test_check_chapter_forbidden_and_title_scene() -> None:
    body = _filler(1000)
    forbidden = check_chapter(
        body, target=1000,
        forbidden_phrases=["乔蔓在签约夜前夜调换手稿本三页"],
    )
    assert forbidden["blockers"] == []
    leaked = check_chapter(
        body + "乔蔓在签约夜前夜调换手稿本三页。",
        target=1000,
        forbidden_phrases=["乔蔓在签约夜前夜调换手稿本三页"],
    )
    assert leaked["blockers"]
    assert leaked["passed"] is False
    # Scene keyword only in the closing line is a mismatch.
    late = _filler(900) + "鉴定室的内容以后再说。"
    assert check_chapter(late, target=1000, scene_keywords=["鉴定室"])["passed"] is False
    early = "鉴定室里灯光明亮。" + _filler(900)
    assert check_chapter(early, target=1000, scene_keywords=["鉴定室"])["passed"] is True
    # No keywords supplied: skipped, never guessed.
    assert check_chapter(body, target=1000)["title_scene"]["checked"] is False


def test_multi_round_expansion_reaches_target(tmp_path: Path) -> None:
    # Segmented pattern: round 1 expands to 600 and its single forward
    # continuation only adds 100 (still short), so a second segmented
    # round is needed to reach target.  The continuation is a within-round
    # top-up, not a substitute for the next governance round.
    fake = ScriptedFake(
        {
            "chapter_body": [_filler(300)],
            "segment_expand": [_filler(600), _filler(1000)],
            "segment_continue": [_filler(100)],
        }
    )
    book_dir = _make_book(tmp_path, fake)
    fake.calls.clear()
    result = write_chapter(book_dir=book_dir, llm_fn=fake, max_governance_rounds=3)
    assert [r["kind"] for r in result["rounds"]] == ["draft", "segment_expand", "segment_expand"]
    assert [r["chars"] for r in result["rounds"]] == [300, 700, 1000]
    assert result["governance"] == "segment_expanded"
    assert result["final_chars"] == 1000
    assert fake.calls.count("segment_expand") == 2
    assert fake.calls.count("segment_continue") == 1


def test_missing_beat_triggers_repair_then_passes(tmp_path: Path) -> None:
    # Structure fix: a missing beat no longer triggers a full-rewrite
    # repair; it gets a fresh segment (budget 500) beside the existing
    # draft segment (condensed to its 500 budget).
    beat = "手稿本三处线条对不上"
    good = "手稿上的三处线条对不上。" + _filler(488)
    assert char_count(good) == 500
    fake = ScriptedFake(
        {"chapter_body": [_filler(1000)], "segment_expand": [_filler(500), good]}
    )
    book_dir = _make_book(tmp_path, fake)
    fake.calls.clear()
    result = write_chapter(book_dir=book_dir, llm_fn=fake, beats=[beat])
    assert result["governance"] == "segment_expanded"
    assert [r["kind"] for r in result["rounds"]] == ["draft", "segment_expand"]
    assert result["rounds"][1]["segment_budgets"] == [500, 500]
    assert result["checks"]["missing_beats"] == []
    chapter_text = Path(result["path"]).read_text(encoding="utf-8")
    assert "手稿" in chapter_text and "线条" in chapter_text


def test_low_dialogue_triggers_repair(tmp_path: Path) -> None:
    # Structure fix: low dialogue with length already in band no longer
    # triggers a full-rewrite repair; the length-OK segment is converted
    # to dialogue paragraph by paragraph (segment_dialogue).
    fake = ScriptedFake(
        {"chapter_body": [_filler(1000, dialogue_ratio=0.1)],
         "segment_dialogue": [_filler(1000, dialogue_ratio=0.5)]}
    )
    book_dir = _make_book(tmp_path, fake)
    result = write_chapter(book_dir=book_dir, llm_fn=fake)
    assert result["governance"] == "segment_expanded"
    assert result["rounds"][1]["segment_kinds"] == ["segment_dialogue"]
    assert result["dialogue_ratio"] == 0.5


def test_dialogue_range_none_measures_only(tmp_path: Path) -> None:
    fake = ScriptedFake({"chapter_body": [_filler(1000, dialogue_ratio=0.1)]})
    book_dir = _make_book(tmp_path, fake)
    result = write_chapter(book_dir=book_dir, llm_fn=fake, dialogue_ratio_range=None)
    assert result["governance"] == "none"
    assert result["dialogue_ratio"] == 0.1


def test_forbidden_blocker_preserves_previous_chapter(tmp_path: Path) -> None:
    fake = FakeLlm()
    book_dir = _make_book(tmp_path, fake)
    first = write_chapter(book_dir=book_dir, llm_fn=fake)
    original = Path(first["path"]).read_text(encoding="utf-8")
    leaked = _filler(1000) + "乔蔓在签约夜前夜调换手稿本三页。"
    # Repair must stay leaked for every governance round (the fallback
    # filler is clean, so a single scripted leak would pass on round 2).
    bad = ScriptedFake({"chapter_body": [leaked], "repair": [leaked] * 3})
    with pytest.raises(CapabilityError) as excinfo:
        write_chapter(
            book_dir=book_dir,
            llm_fn=bad,
            chapter=1,
            forbidden_phrases=["乔蔓在签约夜前夜调换手稿本三页"],
        )
    assert "blocked" in str(excinfo.value)
    # Previous chapter untouched; progress still counts chapter 1 once.
    assert Path(first["path"]).read_text(encoding="utf-8") == original
    assert (book_dir / "chapters" / "chapter_001.quarantine.md").is_file()
    assert load_book(book_dir)["progress"]["completed"] == [1]


def test_title_scene_blocker_quarantines(tmp_path: Path) -> None:
    late = _filler(900) + "鉴定室的内容以后再说。"
    fake = ScriptedFake({"chapter_body": [late], "repair": [late]})
    book_dir = _make_book(tmp_path, fake)
    with pytest.raises(CapabilityError):
        write_chapter(book_dir=book_dir, llm_fn=fake, scene_keywords=["鉴定室"])
    assert (book_dir / "chapters" / "chapter_001.quarantine.md").is_file()
    assert load_book(book_dir)["progress"]["completed"] == []


def test_rewrite_backs_up_previous_chapter(tmp_path: Path) -> None:
    fake = FakeLlm()
    book_dir = _make_book(tmp_path, fake)
    first = write_chapter(book_dir=book_dir, llm_fn=fake)
    original = Path(first["path"]).read_text(encoding="utf-8")
    fake2 = ScriptedFake({"chapter_body": [_filler(1000) + "新稿标记。"]})
    second = write_chapter(book_dir=book_dir, llm_fn=fake2, chapter=1,
                           dialogue_ratio_range=None)
    assert second["backup_path"] is not None
    assert Path(second["backup_path"]).read_text(encoding="utf-8") == original
    assert "新稿标记" in Path(second["path"]).read_text(encoding="utf-8")


def test_transient_llm_error_is_retried(tmp_path: Path) -> None:
    fake = ScriptedFake(
        {"chapter_body": [TimeoutError("read timed out"), _filler(1000)]}
    )
    book_dir = _make_book(tmp_path, fake)
    result = write_chapter(book_dir=book_dir, llm_fn=fake)
    assert result["rounds"][0]["attempts"] == 2
    assert result["final_chars"] == 1000
    assert fake.calls.count("chapter_body") == 2


def test_permanent_llm_error_is_not_retried(tmp_path: Path) -> None:
    fake = ScriptedFake({"chapter_body": [CapabilityError("permanent")]})
    book_dir = _make_book(tmp_path, fake)
    with pytest.raises(CapabilityError, match="permanent"):
        write_chapter(book_dir=book_dir, llm_fn=fake)
    assert fake.calls.count("chapter_body") == 1


def test_capability_write_chapter_accepts_governance_params(tmp_path: Path) -> None:
    beat = "手稿本三处线条对不上"
    good = "手稿上的三处线条对不上。" + _filler(488)
    novel_caps.set_llm_fn(
        ScriptedFake(
            {"chapter_body": [_filler(1000)], "segment_expand": [_filler(500), good]}
        )
    )
    book_dir = tmp_path / "capgov"
    caps.get("novel.create").render_safe(
        {
            "book_dir": str(book_dir),
            "genre": "悬疑",
            "protagonist": "林晚",
            "conflict": "林晚要查清无名信的来源",
            "total_chapters": 3,
            "chapter_target_chars": 1000,
        },
        tmp_path / "job-g1",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    result = caps.get("novel.write_chapter").render_safe(
        {
            "book_dir": str(book_dir),
            "beats": [beat],
            "max_governance_rounds": 3,
            "dialogue_min_ratio": 0.45,
            "dialogue_max_ratio": 0.58,
        },
        tmp_path / "job-g2",
        duration=1.0,
        aspect="16:9",
        seed=1,
    )
    assert result.qa["governance"] == "segment_expanded"
    assert result.qa["checks"]["missing_beats"] == []
    assert result.qa["in_tolerance"] is True
    assert result.qa["backup_path"] is None  # first write, nothing to back up


# ---------------------------------------------------------------------------
# Structure fix (reprobe failure): segmented expansion, tolerant beats,
# paragraph-level dialogue conversion, forward continuation top-up
# ---------------------------------------------------------------------------


class SegmentFake:
    """Fake that follows segment instructions: echoes the segment's beat,
    then dialogue-rich filler up to the segment budget."""

    def __init__(self, draft: str) -> None:
        self.draft = draft
        self.calls: list[str] = []

    def __call__(self, prompt: str, kind: str) -> str:
        self.calls.append(kind)
        if kind == "chapter_body":
            return self.draft
        if kind == "summary":
            return "上一章摘要。"
        if kind in ("segment_expand", "segment_dialogue"):
            budget = int(re.search(r"SEGMENT_TARGET_CHARS=(\d+)", prompt).group(1))
            beat_match = re.search(r"节拍[：:]\s*(.+)", prompt)
            beat_text = ""
            if beat_match:
                raw = beat_match.group(1).strip()
                if not raw.startswith("（无固定节拍"):
                    beat_text = raw.split("；")[0].strip()
            room = budget - char_count(beat_text)
            if room <= 0:
                return beat_text
            return beat_text + _filler(room)
        if kind == "segment_continue":
            need = int(re.search(r"CONTINUE_NEED_CHARS=(\d+)", prompt).group(1))
            return _filler(need)
        raise AssertionError(f"unexpected llm kind: {kind}")


def test_beat_tolerance_reprobe_paraphrases() -> None:
    # All four reprobe anchor failures are now hits — with the body at
    # target length and dialogue in range, so tolerance is the only change.
    cases = [
        (
            [{"beat": "重生醒来", "anchors": ["重生", "签约夜前夜"], "min_anchors": 2}],
            "她重生醒来, 回到了签约夜的前夜。" + _filler(1000),
        ),
        (
            [{"beat": "缺钻胸针", "anchors": ["缺钻", "胸针"], "min_anchors": 2}],
            "她攥着缺失的碎钻胸针。" + _filler(1000),
        ),
        (
            [{"beat": "协议条款", "anchors": ["协议终稿", "多出一页", "条款"], "min_anchors": 2}],
            "协议的终稿里有她没见过的条款。" + _filler(1000),
        ),
        (
            [{"beat": "手稿不符", "anchors": ["手稿", "三处", "线条对不上"], "min_anchors": 3}],
            "手稿本三处线条不符。" + _filler(1000),
        ),
    ]
    for beats, body in cases:
        result = check_chapter(body, target=1000, beats=beats)
        assert result["missing_beats"] == [], (beats, result["beats"])


def test_beat_tolerance_does_not_pass_length_or_dialogue() -> None:
    # Tolerance fixes the anchor gate only: a short, low-dialogue chapter
    # with every beat substantively present still fails both hard gates.
    beats = [
        {"beat": "重生醒来", "anchors": ["重生", "签约夜前夜"], "min_anchors": 2},
    ]
    body = "她重生醒来, 回到了签约夜的前夜。" + "叙" * 400
    result = check_chapter(body, target=1000, beats=beats)
    assert result["missing_beats"] == []
    assert result["passed"] is False
    assert result["in_tolerance"] is False
    assert result["dialogue_in_range"] is False


def test_segment_expand_grows_short_chapter_to_target(tmp_path: Path) -> None:
    # Reprobe pattern, fake model: a 300-char draft with two missing beats
    # grows to target in ONE segmented round (intro + two fresh beat
    # segments, budgets summing to target) — not a same-length rewrite.
    book_dir = _make_book(tmp_path, FakeLlm())
    fake = SegmentFake(_filler(300))
    result = write_chapter(
        book_dir=book_dir,
        llm_fn=fake,
        beats=["林晚收到信", "林晚打开信"],
    )
    assert result["rounds"][0]["chars"] == 300
    assert result["final_chars"] == 1000
    assert result["governance"] == "segment_expanded"
    assert [r["kind"] for r in result["rounds"]] == ["draft", "segment_expand"]
    assert fake.calls.count("segment_expand") == 3
    assert sum(result["rounds"][1]["segment_budgets"]) == 1000
    assert result["checks"]["missing_beats"] == []
    assert 0.45 <= result["dialogue_ratio"] <= 0.58


def test_segment_dialogue_converts_narration_per_beat(tmp_path: Path) -> None:
    # Paragraph-level dialogue conversion: length already in band, dialogue
    # at zero, beats present — each beat segment is converted to dialogue
    # (segment_dialogue), not rewritten whole-chapter.
    para1 = "林晚收到信。" + "叙" * 494
    para2 = "林晚打开信。" + "叙" * 494
    draft = para1 + "\n\n" + para2
    assert char_count(draft) == 1000
    book_dir = _make_book(tmp_path, FakeLlm())
    fake = SegmentFake(draft)
    result = write_chapter(
        book_dir=book_dir,
        llm_fn=fake,
        beats=["林晚收到信", "林晚打开信"],
    )
    assert fake.calls.count("segment_dialogue") == 2
    assert "segment_expand" not in fake.calls
    assert result["rounds"][1]["segment_kinds"] == ["segment_dialogue", "segment_dialogue"]
    assert 0.45 <= result["dialogue_ratio"] <= 0.58
    chapter_text = Path(result["path"]).read_text(encoding="utf-8").split("-->", 1)[1]
    for seg in split_chapter_by_beats(chapter_text, ["林晚收到信", "林晚打开信"]):
        if seg["beats"]:
            assert "“" in seg["text"]


def test_segment_continue_advances_without_repeating_tail(tmp_path: Path) -> None:
    # Forward continuation top-up: a segment still below its minimum gets
    # ONE continuation that advances (new filler text), never restates the
    # segment tail, and lands the chapter on target.
    short_seg = _filler(295) + "尾句标记。"
    assert char_count(short_seg) == 300
    fake = ScriptedFake(
        {
            "chapter_body": [_filler(200)],
            "segment_expand": [short_seg],
            "segment_continue": [_filler(700, dialogue_ratio=0.5)],
        }
    )
    book_dir = _make_book(tmp_path, fake)
    result = write_chapter(book_dir=book_dir, llm_fn=fake)
    assert result["final_chars"] == 1000
    assert result["governance"] == "segment_expanded"
    conts = result["rounds"][1]["continuations"]
    assert len(conts) == 1
    assert conts[0]["need_chars"] == 700
    assert conts[0]["truncated"] is False
    chapter_text = Path(result["path"]).read_text(encoding="utf-8")
    assert chapter_text.count("尾句标记") == 1  # tail stated once, never repeated


def test_segment_continue_ceiling_enforced(tmp_path: Path) -> None:
    # A continuation that overshoots its ceiling is truncated to the
    # ceiling at code level (300 + 900 = 1200 = the chapter's max band),
    # not delivered whole.
    short_seg = _filler(295) + "尾句标记。"
    block = ("“" + "话" * 6 + "”" + "叙" * 4) * 200  # 2400 chars, 50% dialogue
    assert char_count(block) == 2400
    fake = ScriptedFake(
        {
            "chapter_body": [_filler(200)],
            "segment_expand": [short_seg],
            "segment_continue": [block],
        }
    )
    book_dir = _make_book(tmp_path, fake)
    result = write_chapter(book_dir=book_dir, llm_fn=fake)
    assert result["final_chars"] == 1200
    conts = result["rounds"][1]["continuations"]
    assert conts[0]["ceiling_chars"] == 900
    assert conts[0]["truncated"] is True
    assert 0.45 <= result["dialogue_ratio"] <= 0.58


def test_segment_expand_capped_preserves_old_chapter(tmp_path: Path) -> None:
    # Blocked rewrite: old chapter untouched, quarantine written, progress
    # untouched — and the pre-generation backup holds the old chapter.
    fake = FakeLlm()
    book_dir = _make_book(tmp_path, fake)
    first = write_chapter(book_dir=book_dir, llm_fn=fake)
    original = Path(first["path"]).read_text(encoding="utf-8")
    bad = ScriptedFake(
        {
            "chapter_body": [_filler(200)],
            "segment_expand": [_filler(300)] * 3,
            "segment_continue": [_filler(100)] * 3,
        }
    )
    with pytest.raises(CapabilityError) as excinfo:
        write_chapter(book_dir=book_dir, llm_fn=bad, chapter=1, max_governance_rounds=3)
    assert "blocked" in str(excinfo.value)
    assert Path(first["path"]).read_text(encoding="utf-8") == original
    assert (book_dir / "chapters" / "chapter_001.quarantine.md").is_file()
    assert load_book(book_dir)["progress"]["completed"] == [1]
    backups = sorted((book_dir / "chapters" / "backups").glob("chapter_001.bak-*.md"))
    assert backups
    assert backups[0].read_text(encoding="utf-8") == original


def test_segment_expand_transient_retry(tmp_path: Path) -> None:
    fake = ScriptedFake(
        {
            "chapter_body": [_filler(200)],
            "segment_expand": [TimeoutError("read timed out"), _filler(1000)],
        }
    )
    book_dir = _make_book(tmp_path, fake)
    result = write_chapter(book_dir=book_dir, llm_fn=fake)
    assert result["final_chars"] == 1000
    assert result["rounds"][1]["attempts"] == 2
    assert fake.calls.count("segment_expand") == 2


def test_segment_expand_permanent_error_not_retried(tmp_path: Path) -> None:
    fake = ScriptedFake(
        {
            "chapter_body": [_filler(200)],
            "segment_expand": [CapabilityError("permanent-segment")],
        }
    )
    book_dir = _make_book(tmp_path, fake)
    with pytest.raises(CapabilityError, match="permanent-segment"):
        write_chapter(book_dir=book_dir, llm_fn=fake)
    assert fake.calls.count("segment_expand") == 1
    assert not (book_dir / "chapters" / "chapter_001.md").is_file()
    assert not (book_dir / "chapters" / "chapter_001.quarantine.md").is_file()
    assert load_book(book_dir)["progress"]["completed"] == []
