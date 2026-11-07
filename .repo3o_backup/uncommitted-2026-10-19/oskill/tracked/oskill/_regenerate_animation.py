"""K-regenerate_animation: version-update re-generation with diff context."""

from __future__ import annotations

from oprim._animation_types import AnimationResult

from oskill._generate_animation import generate_animation


async def regenerate_animation(
    *,
    template: str,
    variables: dict,
    domain_prompt: str,
    previous_html: str,
    llm,
) -> AnimationResult:
    """Re-generate animation HTML incorporating context from a previous version.

    Builds an augmented domain_prompt that includes the previous HTML so the
    LLM can produce an evolution rather than a from-scratch generation.
    Delegates to generate_animation (validate=True by default).
    """
    prev_ctx = (
        f"Previous version (for reference/improvement):\n```html\n{previous_html}\n```\n\n"
        if previous_html
        else ""
    )
    augmented_prompt = f"{prev_ctx}{domain_prompt}" if domain_prompt else prev_ctx.rstrip()

    result = await generate_animation(
        template=template,
        variables=variables,
        domain_prompt=augmented_prompt,
        llm=llm,
        validate=True,
    )

    result.entity_meta["previous_html_len"] = len(previous_html)
    result.entity_meta["is_regeneration"] = True
    return result
