"""CharacterCard contract and serialization.

3O Pillar: obase.character_card
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CharacterCard:
    """Consolidated character dossier across novel scenes and shots."""

    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    gender: str = "male"
    age_band: str = "young"
    appearance_zh: str = ""
    appearance_en_tokens: str = ""
    voice: str = "zh_CN-huayan-medium.onnx"
    voice_speed: float = 1.0
    ref_image: str | None = None
    ref_face_embedding: list[float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "aliases": list(self.aliases),
            "gender": self.gender,
            "age_band": self.age_band,
            "appearance_zh": self.appearance_zh,
            "appearance_en_tokens": self.appearance_en_tokens,
            "voice": self.voice,
            "voice_speed": self.voice_speed,
            "ref_image": self.ref_image,
            "ref_face_embedding": self.ref_face_embedding,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CharacterCard:
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            aliases=list(data.get("aliases") or []),
            gender=str(data.get("gender", "male")),
            age_band=str(data.get("age_band", "young")),
            appearance_zh=str(data.get("appearance_zh", "")),
            appearance_en_tokens=str(data.get("appearance_en_tokens", "")),
            voice=str(data.get("voice", "zh_CN-huayan-medium.onnx")),
            voice_speed=float(data.get("voice_speed", 1.0)),
            ref_image=data.get("ref_image"),
            ref_face_embedding=data.get("ref_face_embedding"),
        )
