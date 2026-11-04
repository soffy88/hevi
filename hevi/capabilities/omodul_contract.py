"""3O omodul standard-form contract (SPEC v3.0 section 6).

An omodul is a business transaction: it combines two or more
oskill/oprim elements, takes ``(config, input_data, output_dir)``,
always returns a status/error envelope, never raises on business
failure, and declares which pillars it enables via
``_enabled_pillars`` (at least one of fingerprint / decision_trail /
report / cost).

The 51 omodul capabilities keep their existing ``render`` entry
points (their callers and tests depend on them); this module is the
standard-form ADAPTER over them. It does not rewrite the workflows.

Pillar assignment rule (auditable, no grep archaeology):
  * ``fingerprint`` + ``report`` for every omodul: the adapter
    guarantees both by construction -- every envelope carries the
    artefact sha256 (fingerprint) and the status/error report.
  * ``cost`` additionally for the three workflows whose modules name
    paid generation executors directly (storyfilm.py and
    shortstory.py reference pixstag/gpt/nano_banana/fasth3 routes):
    story.film_from_prompt, story.oneclick_film, story.short_package.
  * ``decision_trail`` additionally for the two workflows whose
    product is a persisted decision sequence: pipeline.project_handoff
    (step records) and pipeline.stable_film_assembly (manifest/trail).

The table is the single declaration; the guard test locks its keys
against the layer-attribution table, so a new omodul cannot slip in
undeclared.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.layer_attribution import LAYER_ATTRIBUTION
from hevi.capabilities.registry import get as _caps_get

PILLARS = frozenset({"fingerprint", "decision_trail", "report", "cost"})

_COST_PILLAR = frozenset(
    {"story.film_from_prompt", "story.oneclick_film", "story.short_package"}
)
_TRAIL_PILLAR = frozenset(
    {"pipeline.project_handoff", "pipeline.stable_film_assembly"}
)


def _pillars_for(name: str) -> frozenset:
    pillars = {"fingerprint", "report"}
    if name in _COST_PILLAR:
        pillars.add("cost")
    if name in _TRAIL_PILLAR:
        pillars.add("decision_trail")
    return frozenset(pillars)


OMODUL_PILLARS: dict[str, frozenset] = {
    name: _pillars_for(name)
    for name, entry in LAYER_ATTRIBUTION.items()
    if entry["layer"] == "omodul"
}

OmodulFn = Callable[
    [dict[str, Any], dict[str, Any], str | Path], dict[str, Any]
]


def omodul_names() -> list[str]:
    """Names of the omodul-layer capabilities, in attribution order."""
    return list(OMODUL_PILLARS)


def enabled_pillars(name: str) -> frozenset:
    """Declared pillars for one omodul capability (fails closed)."""
    pillars = OMODUL_PILLARS.get(name)
    if pillars is None:
        raise CapabilityError(
            f"omodul contract: {name!r} is not a declared omodul capability"
        )
    if not pillars or not pillars <= PILLARS:
        raise CapabilityError(
            f"omodul contract: {name!r} declares invalid pillars "
            f"{sorted(pillars)}; need >=1 of {sorted(PILLARS)}"
        )
    return pillars


def _envelope(
    name: str, result: Any, pillars: frozenset
) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "status": "ok",
        "error": None,
        "capability": name,
        "pillars": sorted(pillars),
    }
    if result is not None and hasattr(result, "as_dict"):
        envelope["result"] = result.as_dict()
    elif isinstance(result, dict):
        envelope["result"] = result
    elif result is not None:
        envelope["result"] = {"value": result}
    return envelope


def omodul_entry(name: str) -> OmodulFn:
    """Build the standard-form adapter for one omodul capability.

    Signature ``(config, input_data, output_dir) -> dict``. Params
    are ``{**config, **input_data}`` (input_data wins); ``duration`` /
    ``aspect`` / ``seed`` are read from config with the registry
    defaults. The envelope always carries ``status``/``error``; business failure
    returns ``status: "failed"`` with the error text instead of
    raising. Cancellation (``asyncio.CancelledError``) is re-raised,
    never swallowed into an envelope.
    """
    pillars = enabled_pillars(name)

    def entry(
        config: dict[str, Any],
        input_data: dict[str, Any],
        output_dir: str | Path,
    ) -> dict[str, Any]:
        params = {**(config or {}), **(input_data or {})}
        duration = float(config.get("duration", 5.0)) if config else 5.0
        aspect = str(config.get("aspect", "16:9")) if config else "16:9"
        seed = int(config.get("seed", 42)) if config else 42
        try:
            result = _caps_get(name).render_safe(
                params,
                output_dir,
                duration=duration,
                aspect=aspect,
                seed=seed,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - envelope, never raise
            return {
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "capability": name,
                "pillars": sorted(pillars),
            }
        return _envelope(name, result, pillars)

    entry.__name__ = f"omodul_{name.replace('.', '_')}"
    entry.__doc__ = (
        f"Standard-form (config, input_data, output_dir) adapter for "
        f"{name}; pillars {sorted(pillars)}."
    )
    return entry


def run_omodul(
    name: str,
    config: dict[str, Any],
    input_data: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    """One-shot standard-form call for an omodul capability."""
    return omodul_entry(name)(config, input_data, output_dir)
