"""组装 CosyVoice 引擎行:三模式 + CV3 前缀字段。

组合: `resolve_inference_mode` + `cv3_fields_for_mode` + `detect_family`。
3O 归属(待上游): `oskill.cosy_payload`。
"""

from __future__ import annotations

from typing import Any

from hevi.voicepro.oprim.cosy_mode import (
    cv3_fields_for_mode,
    detect_family,
    resolve_inference_mode,
)
from hevi.voicepro.schemas import CosyLinePayload


def build_cosy_line(
    *,
    text: str,
    voice_ref: str | None = None,
    ref_text: str | None = None,
    instruct_text: str | None = None,
    requested_mode: str | None = None,
    model_name: str | None = None,
    speed: float = 1.0,
    speaker_id: str = "host",
) -> CosyLinePayload:
    mode = resolve_inference_mode(
        requested=requested_mode,
        ref_text=ref_text,
        instruct_text=instruct_text,
    )
    family = detect_family(model_name)
    prompt, tts_out, instruct_out = cv3_fields_for_mode(
        family=family,
        mode=mode,
        tts_text=text,
        ref_text=ref_text,
        instruct_text=instruct_text,
    )
    return CosyLinePayload(
        text=tts_out,
        inference_mode=mode,
        prompt_text=prompt,
        instruct_text=instruct_out,
        voice_ref=voice_ref,
        ref_text=ref_text,
        speed=speed,
        speaker_id=speaker_id,
    )


def build_engine_script(lines: list[CosyLinePayload]) -> list[dict[str, Any]]:
    return [line.to_dict() for line in lines]
