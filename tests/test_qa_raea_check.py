"""S13: optional raea check bypass (off by default, never blocks)."""

from __future__ import annotations

from pathlib import Path

from hevi.qa import raea_check


def test_disabled_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("HEVI_RAEA_CHECK", raising=False)
    video = tmp_path / "x.mp4"
    video.write_bytes(b"not a video")
    out = raea_check.run_raea_check(video)
    assert out["enabled"] is False
    assert out["status"] == "skipped"
    assert out["checked"] is False


def test_missing_binary_skips(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HEVI_RAEA_CHECK", "1")
    monkeypatch.setenv("HEVI_RAEA_BIN", str(tmp_path / "nope"))
    video = tmp_path / "x.mp4"
    video.write_bytes(b"not a video")
    out = raea_check.run_raea_check(video)
    assert out["status"] == "skipped"
    assert "binary not found" in out["reason"]


def test_parses_json_findings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HEVI_RAEA_CHECK", "1")
    fake = tmp_path / "raea"
    fake.write_text(
        "#!/bin/sh\n"
        "out=\"\"\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-o\" ]; then out=\"$2\"; shift 2; else shift; fi\n"
        "done\n"
        "printf '%s' '{\"issues\":[{\"rule\":\"loudness\",\"p\":\"P1\",\"says\":\"-21.8 LUFS\"}],"
        "\"passed\":[\"frozen: ok\"]}' > \"$out\"\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("HEVI_RAEA_BIN", str(fake))
    video = tmp_path / "x.mp4"
    video.write_bytes(b"not a video")
    out = raea_check.run_raea_check(video, timeout_s=5)
    assert out["status"] == "ok"
    assert out["checked"] is True
    assert out["summary"]["by_rule"] == {"loudness": 1}
    assert out["summary"]["blocking"] == 1
    assert out["exit_code"] == 1


def test_timeout_is_a_skip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HEVI_RAEA_CHECK", "1")
    fake = tmp_path / "raea"
    fake.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("HEVI_RAEA_BIN", str(fake))
    video = tmp_path / "x.mp4"
    video.write_bytes(b"not a video")
    out = raea_check.run_raea_check(video, timeout_s=1)
    assert out["status"] == "timeout"
    assert out["checked"] is False


def test_attach_to_quality(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HEVI_RAEA_CHECK", "1")
    fake = tmp_path / "raea"
    fake.write_text(
        "#!/bin/sh\nout=\"\"\nwhile [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = \"-o\" ]; then out=\"$2\"; shift 2; else shift; fi\ndone\n"
        "printf '%s' '{\"issues\":[],\"passed\":[\"ok\"]}' > \"$out\"\nexit 0\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("HEVI_RAEA_BIN", str(fake))
    video = tmp_path / "x.mp4"
    video.write_bytes(b"x")
    result = {"result_video_path": str(video), "quality": {"passed": True, "checks": {}}}
    out = raea_check.attach_to_quality(result)
    assert out["quality"]["checks"]["raea_check"]["checked"] is True
