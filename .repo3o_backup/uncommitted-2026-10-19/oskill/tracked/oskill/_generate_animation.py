"""K-generate_animation: LLM animation HTML generator (stateless)."""

from __future__ import annotations
from oprim import llm_complete

from oprim._animation_types import AnimationResult
from oprim._validate_html import validate_html
from oprim.llm_complete import llm_complete


async def generate_animation(
    *,
    template: str,
    variables: dict,
    domain_prompt: str,
    llm,
    validate: bool = True,
) -> AnimationResult:
    """Generate animation HTML via LLM, then validate for safety.

    Composes:
      llm_complete (oprim) — LLM call with message formatting + usage extraction
      validate_html (oprim) — sandboxed safety check (no network, no DB)

    template + variables form the LLM prompt (template.format_map(variables)).
    domain_prompt is prepended as generation instruction.
    No persistence — callers (omodul) own the storage layer.
    """
    filled = template.format_map(variables) if variables else template
    prompt = f"{domain_prompt}\n\n{filled}" if domain_prompt else filled

    response = await llm_complete(
        [{"role": "user", "content": prompt}],
        caller=llm,
        system="You are an HTML animation generator. Return only valid, self-contained HTML.",
        max_tokens=4096,
    )
    html = response.text.strip()

    is_valid = True
    violations: list[str] = []
    if validate:
        val = validate_html(html=html)
        is_valid = val.is_safe
        violations = val.violations

    return AnimationResult(
        html=html,
        is_valid=is_valid,
        validation_violations=violations,
        entity_meta={
            "variables": variables,
            "domain_prompt_preview": domain_prompt[:200] if domain_prompt else "",
        },
    )
