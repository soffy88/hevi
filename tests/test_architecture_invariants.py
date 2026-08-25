import runpy
from pathlib import Path


def test_architecture_invariants_pass() -> None:
    invariants = runpy.run_path("scripts/ci/check_architecture_invariants.py")
    runtime = runpy.run_path("scripts/ci/check_runtime_boundaries.py")
    assert invariants["main"]() == 0
    assert runtime["main"]() == 0


def test_disaster_restore_refuses_in_place_without_flag() -> None:
    script = Path("hevi/deploy/backup/restore.sh")
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "ALLOW_DESTRUCTIVE_RESTORE" in text
    assert "Refusing in-place restore" in text


def test_backup_and_drill_scripts_exist() -> None:
    assert Path("hevi/deploy/backup/backup.sh").is_file()
    assert Path("hevi/deploy/backup/restore.sh").is_file()
    assert Path("hevi/deploy/backup/drill.sh").is_file()
    assert Path("scripts/live_closure_load.py").is_file()
