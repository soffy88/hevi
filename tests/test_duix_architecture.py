from pathlib import Path


def test_avatar_paths_use_provider_contract_not_duix_runtime() -> None:
    root = Path(__file__).parents[1]
    for relative in ("hevi/digital_human/talking_face.py", "hevi/explainer/echo_avatar.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "from hevi.digital_human.duix_offline" not in source
        assert "provider_contract" in source
