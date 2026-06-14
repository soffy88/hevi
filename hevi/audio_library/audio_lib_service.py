from __future__ import annotations

from typing import Any, Literal

from hevi.audio.bgm_library import BGMLibrary
from hevi.audio_library.audio_lib_repository import AudioLibraryRepository


class AudioLibraryService:
    def __init__(self, repo: AudioLibraryRepository, bgm_lib: BGMLibrary | None = None) -> None:
        self._repo = repo
        self._bgm_lib = bgm_lib or BGMLibrary()

    async def create_audio_asset(
        self,
        *,
        name: str,
        asset_type: Literal["bgm", "sfx"],
        file_path: str,
        mood: str | None = None,
        duration_s: float = 0.0,
        tags: list[str] | None = None,
        is_official: bool = False,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        data = {
            "name": name,
            "asset_type": asset_type,
            "file_path": file_path,
            "mood": mood,
            "duration_s": duration_s,
            "tags": tags or [],
            "is_official": is_official,
            "user_id": user_id,
        }
        return await self._repo.create(data)

    async def get_audio_asset(self, asset_id: str) -> dict[str, Any] | None:
        return await self._repo.get(asset_id)

    async def search_audio(
        self,
        *,
        asset_type: str | None = None,
        mood: str | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._repo.search(
            asset_type=asset_type,
            mood=mood,
            tags=tags,
            query_text=query,
            user_id=user_id
        )

    async def delete_audio_asset(self, asset_id: str) -> bool:
        return await self._repo.delete(asset_id)

    def get_physical_path(self, file_path: str) -> str:
        """Resolve database file_path to physical filesystem path using bgm_library.
        
        This handles integration with P10.C bgm_library.
        """
        # If it's BGM, check if it's in bgm_library dirs
        # For now, if file_path is just a name, try to resolve it.
        # Otherwise return as is.
        # This is a bit simplified, P10.C bgm_library expects ids/names.
        return str(self._bgm_lib.root_dir / file_path)
