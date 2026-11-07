"""LLM response consistency checker — measures response stability across N samples."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any


def llm_response_consistency(
    prompt_template: str,
    variables: dict[str, Any],
    client_fn: Callable[..., dict],
    *,
    model: str,
    n_samples: int = 5,
    temperature: float = 0.7,
    similarity_fn: Callable[[str, str], float] | None = None,
    response_extractor: Callable[[dict], str] | None = None,
) -> dict[str, Any]:
    """Measure LLM response consistency over N independent samples.

    Workflow:
        1. Format prompt_template with variables
        2. Call client_fn n_samples times (each independent call)
        3. Extract response string per call (use response_extractor if provided)
        4. Compute pairwise similarities if similarity_fn provided
        5. Compute exact_match_rate (most common response / total)

    Parameters
    ----------
    prompt_template : str
        Prompt template with {variable} placeholders.
    variables : dict
        Values for template placeholders.
    client_fn : callable
        (messages, model, **kwargs) -> dict with 'content' key.
    model : str
        Model identifier.
    n_samples : int
        Number of independent calls to make. Must be >= 1.
    temperature : float
        Sampling temperature for all calls.
    similarity_fn : callable or None
        (str, str) -> float comparing two responses. If None, similarity metrics are None.
    response_extractor : callable or None
        (dict) -> str to extract response text from client_fn result.
        If None, uses result['content'].

    Returns
    -------
    dict with keys: 'responses', 'unique_responses', 'n_unique',
    'mean_pairwise_similarity', 'exact_match_rate', 'most_common_response',
    'most_common_frequency', 'is_highly_consistent'

    Raises
    ------
    ValueError
        If n_samples < 1.
    """
    if n_samples < 1:
        raise ValueError(f"n_samples must be >= 1, got {n_samples}")

    # 1. Format prompt
    prompt_rendered = prompt_template.format(**variables)
    messages = [{"role": "user", "content": prompt_rendered}]

    # 2. Call client_fn n_samples times
    responses: list[str] = []
    for _ in range(n_samples):
        result = client_fn(messages, model, temperature=temperature, max_tokens=1024)

        # 3. Extract response string
        if response_extractor is not None:
            text = response_extractor(result)
        else:
            text = result.get("content", "")

        responses.append(text)

    # 4. Compute pairwise similarity
    mean_pairwise_similarity: float | None = None
    if similarity_fn is not None and len(responses) >= 2:
        pair_scores: list[float] = []
        for i in range(len(responses)):
            for j in range(i + 1, len(responses)):
                score = similarity_fn(responses[i], responses[j])
                pair_scores.append(score)
        mean_pairwise_similarity = sum(pair_scores) / len(pair_scores) if pair_scores else None

    # 5. Compute exact match stats
    counter = Counter(responses)
    most_common_response, most_common_frequency = counter.most_common(1)[0]
    exact_match_rate = most_common_frequency / n_samples

    unique_responses = list(counter.keys())
    n_unique = len(unique_responses)

    # Consider highly consistent if most common response appears in >=60% of samples
    # OR if similarity (when available) is > 0.8
    if mean_pairwise_similarity is not None:
        is_highly_consistent = mean_pairwise_similarity > 0.8 or exact_match_rate >= 0.6
    else:
        is_highly_consistent = exact_match_rate >= 0.6

    return {
        "responses": responses,
        "unique_responses": unique_responses,
        "n_unique": n_unique,
        "mean_pairwise_similarity": mean_pairwise_similarity,
        "exact_match_rate": exact_match_rate,
        "most_common_response": most_common_response,
        "most_common_frequency": most_common_frequency,
        "is_highly_consistent": is_highly_consistent,
    }
