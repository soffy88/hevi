"""Central 3O layer attribution table for the capabilities registry.

Generated from ``~/workspace/3o-conformance/layer_attribution.json``
(397 capabilities, one entry each, no "unclassified" remainder).
Regenerate — never hand-edit entries — with
``scripts/ci/gen_layer_attribution.py`` (reads the JSON, writes this file).

Each entry: name -> {"layer": <3O layer>, "reason": <one-line evidence>,
"file": <defining module file>}. ``register()`` fills ``Capability.layer``
from this table when the caller did not declare one explicitly; an
explicit layer on the Capability wins.

Layers follow HELIOS_3O_SPEC_v3_0 §1: oprim (atomic), oskill (>=2 oprim
combination, stateless algorithm), omodul (business transaction),
obase (external adapter / cross-cutting), oservi (reusable engine
skeleton, 5 red lines in SPEC §7.2).
"""

from __future__ import annotations

from typing import Any

# Filled by codegen from layer_attribution.json; empty until the
# attribution batch lands. The conformance test asserts full coverage,
# so an empty table fails loudly instead of silently passing.
LAYER_ATTRIBUTION: dict[str, dict[str, Any]] = {}
