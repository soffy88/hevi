"""P0.8 — the OpenReel adapter seam.

What is and is not imported
--------------------------
Nothing from OpenReel is imported at module scope. §22 makes it an adapter boundary,
not a HEVI core dependency, and §54 requires HEVI core tests to pass with OpenReel
absent -- which is the current state of this repository: there is no ``openreel``
package, no sibling checkout, and nothing in ``pyproject``.

Consequences, stated rather than hidden:

* The mappers below translate between HEVI contracts and the *shape* of an OpenReel
  action/artifact, as plain dataclasses. That translation is fully testable now.
* The execution path -- actually running an OpenReel action and reading back an
  artifact -- requires the runtime and is therefore BLOCKED, not skipped. See
  ``OpenReelExecutionAdapter.execute``, which fails loudly rather than pretending.

What is absorbed from OpenReel, per §0.2
------------------------------------------
The execution substrate: action/operation execution, validation-before-execution,
transaction, rollback, headless execution, job runner, receipts.

What is explicitly not absorbed
-------------------------------
OpenReel Project is not a HEVI Project, its Agent Loop is not a HEVI planner, its
semantic planner is not a Director, and its 228-tool surface is not an authority. A
mapper here translates *dialect*, never meaning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from hevi.production.operation import ProductionOperation, ProductionOperationType


@dataclass(frozen=True)
class OpenReelAction:
    """One OpenReel action, in the shape OpenReel's runner expects.

    A plain dataclass on purpose: this is the wire shape, not a HEVI type and not an
    OpenReel import. Constructing it requires no OpenReel, which is what keeps the
    mapping layer testable in its absence.
    """

    action_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    #: Set when the action must run after others. OpenReel orders by this; HEVI does not
    #: derive order from it.
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class OpenReelArtifact:
    """What an OpenReel run hands back."""

    artifact_id: str
    uri: str
    content_hash: str = ""
    kind: str = "unknown"
    produced_by_action: str = ""


class OpenReelRunner(Protocol):
    """The injected seam. Implemented by whatever actually drives OpenReel.

    Keeping this a Protocol is what lets the executor be constructed and tested with no
    OpenReel present. A concrete import here would make the whole execution contract
    unimportable without the external project.
    """

    def available(self) -> bool: ...

    def run_actions(
        self, actions: tuple[OpenReelAction, ...], *, work_dir: Any = None
    ) -> tuple[OpenReelArtifact, ...]: ...


class OpenReelUnavailable(RuntimeError):
    """OpenReel is not present. Named so callers can distinguish it from a real failure."""


__all__ = [
    "OpenReelAction",
    "OpenReelArtifact",
    "OpenReelRunner",
    "OpenReelUnavailable",
    "ProductionOperation",
    "ProductionOperationType",
]
