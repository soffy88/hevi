"""Narrator CLI wrapper: missing key/binary is a hard miss, not a fake catalog."""

from __future__ import annotations

import pytest

from hevi.narrator.client import NarratorUnavailable, narrator_status, run_narrator


def test_status_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NARRATOR_APP_KEY", raising=False)
    monkeypatch.setattr("hevi.narrator.client.shutil.which", lambda _name: None)
    status = narrator_status()
    assert status["cli"] is False
    assert status["app_key"] is False
    assert "pip install" in status["hint"]


def test_run_refuses_unknown_verb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NARRATOR_APP_KEY", "x")
    monkeypatch.setattr("hevi.narrator.client.shutil.which", lambda _name: "/usr/bin/narrator-ai-cli")
    with pytest.raises(ValueError, match="白名单"):
        run_narrator("rm")


def test_run_unavailable_without_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NARRATOR_APP_KEY", "x")
    monkeypatch.setattr("hevi.narrator.client.shutil.which", lambda _name: None)
    with pytest.raises(NarratorUnavailable):
        run_narrator("material-list")


def test_cli_status_exits_2_without_key(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from hevi.skills.narrator_cli import main

    monkeypatch.delenv("NARRATOR_APP_KEY", raising=False)
    monkeypatch.setattr("hevi.narrator.client.shutil.which", lambda _name: None)
    assert main(["--status"]) == 2
    out = capsys.readouterr().out
    assert "pip install" in out
