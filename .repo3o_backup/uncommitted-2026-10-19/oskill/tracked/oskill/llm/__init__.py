"""LLM integration primitives submodule."""

from oskill.llm.consistency import llm_response_consistency
from oskill.llm.cot import chain_of_thought_extractor
from oskill.llm.deterministic_call import deterministic_llm_call
from oskill.llm.faithfulness import faithfulness_score
from oskill.llm.multi_model import multi_model_ensemble
from oskill.llm.prompt_fingerprint import prompt_fingerprint
from oskill.llm.text_translate import text_translate
from oskill.llm.tool_validation import tool_call_validator

__all__ = [
    "deterministic_llm_call",
    "prompt_fingerprint",
    "tool_call_validator",
    "chain_of_thought_extractor",
    "llm_response_consistency",
    "multi_model_ensemble",
    "faithfulness_score",
    "text_translate",
]
