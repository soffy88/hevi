import os
from pathlib import Path


class BGMLibrary:
    """BGM and SFX management framework.

    Handles directory scanning and retrieval by mood or type.
    Actual audio files are pending; this provides the management framework.
    """

    def __init__(self, root_dir: Path | str = "assets/audio"):
        self.root_dir = Path(root_dir)
        self.bgm_dir = self.root_dir / "bgm"
        self.sfx_dir = self.root_dir / "sfx"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Ensure the audio directories exist."""
        self.bgm_dir.mkdir(parents=True, exist_ok=True)
        self.sfx_dir.mkdir(parents=True, exist_ok=True)

    def list_bgm(self, mood: str | None = None) -> list[Path]:
        """List BGM files, optionally filtered by mood (directory name)."""
        if not self.bgm_dir.exists():
            return []

        if mood:
            mood_dir = self.bgm_dir / mood
            if not mood_dir.exists():
                return []
            return [
                mood_dir / f
                for f in os.listdir(mood_dir)
                if os.path.isfile(mood_dir / f) and not f.startswith(".")
            ]

        # Return all BGM files recursively
        return [
            Path(root) / f
            for root, _, files in os.walk(self.bgm_dir)
            for f in files
            if not f.startswith(".")
        ]

    def get_sfx(self, name: str) -> Path | None:
        """Get SFX file by name."""
        # Simple name match in sfx_dir
        for f in os.listdir(self.sfx_dir):
            if f.startswith(name) and os.path.isfile(self.sfx_dir / f):
                return self.sfx_dir / f
        return None

    def get_bgm_path(self, bgm_id: str) -> Path | None:
        """Retrieve BGM path by its ID (filename or relative path)."""
        potential_path = self.bgm_dir / bgm_id
        if potential_path.exists() and potential_path.is_file():
            return potential_path
        return None
