"""字体 / BGM / mocap 拷贝包 + 资产目录。"""

from __future__ import annotations

from pathlib import Path

from hevi.studio.fonts import list_fonts, resolve_font
from hevi.studio.mocap import get_mocap, list_mocap
from hevi.studio.packs import list_packs, pull_pack


def test_pack_catalog_includes_four_new() -> None:
    packs = list_packs()
    for name in (
        "edge-tts-samples",
        "kokoro-tts-samples",
        "subtitle-fonts",
        "stock-bgm",
        "handwrite-font",
        "mocap-clips",
        "open-corpus-seed",
    ):
        assert name in packs


def test_copy_fonts_bgm_mocap(tmp_path: Path) -> None:
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    (fonts / "Charm-Regular.ttf").write_bytes(b"ttf")
    (fonts / "BeVietnamPro-Medium.ttf").write_bytes(b"ttf")
    songs = tmp_path / "songs"
    songs.mkdir()
    (songs / "output000.mp3").write_bytes(b"mp3")
    mocap = tmp_path / "mocap"
    (mocap / "clips").mkdir(parents=True)
    (mocap / "catalog.json").write_text('[{"name":"wave","desc":"waves"}]', encoding="utf-8")
    (mocap / "clips" / "wave.json").write_text("{}", encoding="utf-8")

    packs = list_packs()
    packs["subtitle-fonts"]["roots"] = [str(fonts)]
    packs["stock-bgm"]["roots"] = [str(songs)]
    packs["stock-bgm"]["mirror"] = str(tmp_path / "mirror-bgm")
    packs["mocap-clips"]["roots"] = [str(mocap)]
    packs["handwrite-font"]["roots"] = [str(fonts)]
    packs["handwrite-font"]["include"] = ["Charm-Regular.ttf"]

    from hevi.studio import packs as packs_mod

    orig = packs_mod.list_packs
    packs_mod.list_packs = lambda path=None: packs
    try:
        fonts_out = pull_pack("subtitle-fonts", root=tmp_path / "assets")
        bgm_out = pull_pack("stock-bgm", root=tmp_path / "assets")
        mocap_out = pull_pack("mocap-clips", root=tmp_path / "assets")
        hand_out = pull_pack("handwrite-font", root=tmp_path / "assets")
    finally:
        packs_mod.list_packs = orig

    assert fonts_out.pulled == 2
    assert bgm_out.pulled == 1
    assert (tmp_path / "mirror-bgm" / "output000.mp3").exists()
    assert mocap_out.pulled >= 2
    assert hand_out.pulled == 1
    root = tmp_path / "assets"
    assert resolve_font("charm", root=root) is not None
    assert len(list_fonts(root=root)) >= 2
    wave = get_mocap("wave", root=root)
    assert wave is not None
    assert len(list_mocap(root=root)) >= 1
