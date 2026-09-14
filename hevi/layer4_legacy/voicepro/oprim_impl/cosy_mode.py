"""CosyVoice 三模式解析 + CosyVoice3 <|endofprompt|> 前缀。

对齐 Voice-Pro `abus_tts_cosyvoice`:Zero-Shot / Cross-Lingual / Instruct。
CV3 缺系统提示词时 LLM 线程静默死亡、产出空音频。
3O 归属(待上游): `oprim.cosy_mode`。
"""

from __future__ import annotations

from hevi.voicepro.schemas import CosyInferenceMode

CV3_SYSTEM_PROMPT = "You are a helpful assistant.<|endofprompt|>"

_ALIASES: dict[str, CosyInferenceMode] = {
    "zero_shot": "zero_shot",
    "zero-shot": "zero_shot",
    "zeroshot": "zero_shot",
    "cross_lingual": "cross_lingual",
    "cross-lingual": "cross_lingual",
    "crosslingual": "cross_lingual",
    "instruct": "instruct",
    "instruct2": "instruct",
}


def normalize_mode(raw: str | None) -> CosyInferenceMode | None:
    if raw is None:
        return None
    key = str(raw).strip().lower().replace(" ", "_")
    return _ALIASES.get(key)


def detect_family(model_name: str | None) -> str:
    name = (model_name or "").lower()
    if "cosyvoice3" in name or name in {"cv3", "fun-cosyvoice3-0.5b"}:
        return "cosyvoice3"
    return "cosyvoice2"


def needs_cv3_prefix(family: str) -> bool:
    return family == "cosyvoice3"


def resolve_inference_mode(
    *,
    requested: str | None = None,
    ref_text: str | None = None,
    instruct_text: str | None = None,
) -> CosyInferenceMode:
    explicit = normalize_mode(requested)
    if explicit is not None:
        return explicit
    if instruct_text and str(instruct_text).strip():
        return "instruct"
    if ref_text and str(ref_text).strip():
        return "zero_shot"
    return "cross_lingual"


def apply_cv3_prefix(
    text: str,
    *,
    family: str,
    mode: CosyInferenceMode,
) -> str:
    """按模式给 CV3 加系统前缀。CV2 原样返回。"""
    body = text or ""
    if not needs_cv3_prefix(family):
        return body
    if body.startswith(CV3_SYSTEM_PROMPT):
        return body
    return CV3_SYSTEM_PROMPT + body


def cv3_fields_for_mode(
    *,
    family: str,
    mode: CosyInferenceMode,
    tts_text: str,
    ref_text: str | None,
    instruct_text: str | None,
) -> tuple[str, str, str]:
    """返回 (prompt_text, tts_text_out, instruct_out)。

    Voice-Pro:zero_shot 前缀加在 ref_text;cross_lingual 加在 tts_text;
    instruct 的 instruct_text 为系统提示(CV3)或空(CV2)。
    """
    if mode == "zero_shot":
        prompt = apply_cv3_prefix(ref_text or "", family=family, mode=mode)
        return prompt, tts_text, ""
    if mode == "cross_lingual":
        return "", apply_cv3_prefix(tts_text, family=family, mode=mode), ""
    instruct = instruct_text or ""
    if needs_cv3_prefix(family) and not instruct:
        instruct = CV3_SYSTEM_PROMPT
    elif needs_cv3_prefix(family):
        instruct = apply_cv3_prefix(instruct, family=family, mode=mode)
    return "", tts_text, instruct
