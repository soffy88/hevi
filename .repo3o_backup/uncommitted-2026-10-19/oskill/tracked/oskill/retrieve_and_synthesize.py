from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from oskill._llm_caller import LLMCaller


class RetrievedDoc(BaseModel):
    doc_id: str
    content: str
    score: float
    metadata: dict[str, Any] = {}


class SynthesizedResult(BaseModel):
    retrieved_docs: list[RetrievedDoc]
    synthesized_answer: str
    confidence: float
    citations: list[dict[str, Any]] = []  # [{doc_id, snippet, relevance}]


def retrieve_and_synthesize(
    *,
    query: str,
    corpus_id: str,  # 在哪个 corpus 检索 (服务层映射 user_id → corpus_id)
    llm: LLMCaller,
    top_k: int = 5,
    vector_search_fn: Callable[[str, str, int], list[RetrievedDoc]] | None = None,
) -> SynthesizedResult:
    """向量检索 + LLM 合成.

    vector_search_fn 由 caller (omodul) 注入, 默认 None 时 raise — 让 caller 自决用什么向量库.
    """
    if vector_search_fn is None:
        raise ValueError("vector_search_fn must be provided")

    # 1. Retrieve
    docs = vector_search_fn(query, corpus_id, top_k)

    if not docs:
        return SynthesizedResult(
            retrieved_docs=[], synthesized_answer="No relevant documents found.", confidence=0.0
        )

    # 2. Synthesize
    context_text = "\n\n".join([f"Document {d.doc_id}:\n{d.content}" for d in docs])
    prompt = f"""Use the following context to answer the query.
Query: {query}

Context:
{context_text}

Provide a concise answer with citations (e.g., [Document ID]).
Include your confidence score (0.0 to 1.0).
"""

    response = llm(messages=[{"role": "user", "content": prompt}], max_tokens=2048)

    answer = response.get("content", "Failed to synthesize answer.")

    # Extract confidence (reusing logic from agentic_investigate_loop)
    from oskill._utils import extract_confidence

    confidence = extract_confidence(answer)
    return SynthesizedResult(
        retrieved_docs=docs,
        synthesized_answer=answer,
        confidence=confidence,
        citations=[],  # Simplified: citations could be extracted from answer if needed
    )
