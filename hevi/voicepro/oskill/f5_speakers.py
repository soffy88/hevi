"""F5 目录选模 + 多说话人参考绑定。

组合: `pick_model_for_language` + `parse_conversation` + `get_model`。
3O 归属(待上游): `oskill.f5_speakers`。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hevi.voicepro.oprim.f5_catalog import get_model, parse_conversation, pick_model_for_language
from hevi.voicepro.schemas import F5ModelSpec, SpeakerTurn


@dataclass
class SpeakerRef:
    speaker: str
    reference_audio: str
    reference_text: str


@dataclass
class BoundTurn:
    turn: SpeakerTurn
    model: F5ModelSpec
    reference_audio: str
    reference_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "speaker": self.turn.speaker,
            "message": self.turn.message,
            "model": self.model.name,
            "reference_audio": self.reference_audio,
            "reference_text": self.reference_text,
        }


def pick_catalog_model(
    language: str = "",
    model_name: str | None = None,
    catalog_path: str | None = None,
) -> str:
    if model_name:
        spec = get_model(model_name, catalog_path)
    else:
        spec = pick_model_for_language(language, catalog_path)
    return spec.name


def conversation_turns(text: str) -> list[SpeakerTurn]:
    return parse_conversation(text)


def resolve_turns(
    text: str,
    *,
    language: str = "",
    model_name: str | None = None,
    speakers: dict[str, SpeakerRef] | None = None,
    default_ref: SpeakerRef | None = None,
    catalog_path: str | None = None,
) -> list[BoundTurn]:
    """把 `{spk1}` 对话绑到各说话人参考音频,并选定 F5 模型。"""
    if model_name:
        model = get_model(model_name, catalog_path)
    else:
        model = pick_model_for_language(language, catalog_path)
    turns = parse_conversation(text)
    if not turns and text.strip():
        turns = [SpeakerTurn(speaker="host", message=text.strip())]
    table = speakers or {}
    bound: list[BoundTurn] = []
    for turn in turns:
        ref = table.get(turn.speaker) or default_ref
        if ref is None:
            raise ValueError(f"no voice reference for speaker {turn.speaker}")
        bound.append(
            BoundTurn(
                turn=turn,
                model=model,
                reference_audio=str(ref.reference_audio),
                reference_text=ref.reference_text,
            )
        )
    return bound


def refs_exist(turns: list[BoundTurn]) -> bool:
    return all(Path(item.reference_audio).exists() for item in turns)
