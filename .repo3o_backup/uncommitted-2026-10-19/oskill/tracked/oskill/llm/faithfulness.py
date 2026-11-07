"""Faithfulness scorer — evaluates LLM response grounding in retrieved evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from oprim import canonical_json, sha256_hash

_DEFAULT_CLAIM_EXTRACTOR_TEMPLATE = (
    "Extract atomic factual claims from the following response. "
    "Output one claim per line, no numbering.\n\n"
    "Response: {response}"
)

_DEFAULT_NLI_TEMPLATE = (
    "Is the following claim supported by the evidence? "
    "Answer 'yes' or 'no' only.\n\n"
    "Claim: {claim}\n\nEvidence: {evidence}\n\nAnswer:"
)


def faithfulness_score(
    response: str,
    retrieved_evidence: list[str],
    client_fn: Callable[..., dict],
    *,
    model: str,
    claim_extractor_template: str | None = None,
    nli_template: str | None = None,
    threshold: float = 0.5,
) -> dict[str, Any]:
    """Score faithfulness of an LLM response against retrieved evidence.

    Workflow:
        1. Use claim_extractor_template to extract atomic claims via client_fn
        2. For each claim: use nli_template to check if any evidence supports it
        3. faithfulness_score = supported_claims / total_claims
           If total_claims == 0: score = 1.0 (vacuously faithful)
        4. Compute evaluation_fingerprint via oprim.canonical_json + oprim.sha256_hash

    Parameters
    ----------
    response : str
        LLM response to evaluate.
    retrieved_evidence : list[str]
        List of evidence passages to check claims against.
    client_fn : callable
        (messages, model, **kwargs) -> dict with 'content' key.
    model : str
        Model identifier.
    claim_extractor_template : str or None
        Template for claim extraction. Uses default if None.
    nli_template : str or None
        Template for NLI check. Uses default if None.
    threshold : float
        Minimum faithfulness score to consider response faithful.

    Returns
    -------
    dict with keys: 'faithfulness_score', 'is_faithful', 'claims', 'claim_support',
    'n_supported', 'n_total', 'evaluation_fingerprint'
    """
    if claim_extractor_template is None:
        claim_extractor_template = _DEFAULT_CLAIM_EXTRACTOR_TEMPLATE
    if nli_template is None:
        nli_template = _DEFAULT_NLI_TEMPLATE

    # 1. Extract atomic claims
    extraction_prompt = claim_extractor_template.format(response=response)
    messages = [{"role": "user", "content": extraction_prompt}]
    extraction_result = client_fn(messages, model, temperature=0.0, max_tokens=1024)
    raw_claims_text = extraction_result.get("content", "")

    # Parse claims: one per line, skip empty lines
    claims = [line.strip() for line in raw_claims_text.splitlines() if line.strip()]

    # Edge case: no claims extracted → vacuously faithful
    if not claims:
        fingerprint_payload = {
            "response": response,
            "retrieved_evidence": retrieved_evidence,
            "model": model,
            "claims": [],
        }
        evaluation_fingerprint = sha256_hash(canonical_json(fingerprint_payload))
        return {
            "faithfulness_score": 1.0,
            "is_faithful": True,
            "claims": [],
            "claim_support": {},
            "n_supported": 0,
            "n_total": 0,
            "evaluation_fingerprint": evaluation_fingerprint,
        }

    # 2. For each claim, check if any evidence supports it
    claim_support: dict[str, bool] = {}
    combined_evidence = "\n\n".join(retrieved_evidence) if retrieved_evidence else ""

    for claim in claims:
        supported = False
        # Check against each piece of evidence (or combined if empty)
        evidence_list = retrieved_evidence if retrieved_evidence else [combined_evidence]
        for evidence in evidence_list:
            nli_prompt = nli_template.format(claim=claim, evidence=evidence)
            nli_messages = [{"role": "user", "content": nli_prompt}]
            nli_result = client_fn(nli_messages, model, temperature=0.0, max_tokens=10)
            nli_answer = nli_result.get("content", "").strip().lower()
            if nli_answer.startswith("yes"):
                supported = True
                break
        claim_support[claim] = supported

    # 3. Compute faithfulness score
    n_total = len(claims)
    n_supported = sum(1 for v in claim_support.values() if v)
    score = n_supported / n_total if n_total > 0 else 1.0
    is_faithful = score >= threshold

    # 4. Compute fingerprint
    fingerprint_payload = {
        "response": response,
        "retrieved_evidence": retrieved_evidence,
        "model": model,
        "claims": claims,
        "claim_support": {k: v for k, v in sorted(claim_support.items())},
    }
    evaluation_fingerprint = sha256_hash(canonical_json(fingerprint_payload))

    return {
        "faithfulness_score": score,
        "is_faithful": is_faithful,
        "claims": claims,
        "claim_support": claim_support,
        "n_supported": n_supported,
        "n_total": n_total,
        "evaluation_fingerprint": evaluation_fingerprint,
    }
