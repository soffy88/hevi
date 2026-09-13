"""Narrative-to-shot provenance records."""

from __future__ import annotations

from typing import cast

from hevi.narrative.models import NarrativeProvenance, to_dict


def provenance_payload(provenance: NarrativeProvenance) -> dict[str, object]:
    return cast(dict[str, object], to_dict(provenance))
