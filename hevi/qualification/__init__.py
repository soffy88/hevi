"""Machine-readable production qualification contracts.

Two authorities live here:

* media — the pre-existing single media validation gate, used by every production
  qualification. Path-based, and MediaValidation.passed is a plain field.
* live_run / live_runner — P9.0 live qualification. Byte-based via P8.4, and
  passed is derived.

The two overlap on codec / resolution / duration / fps. They are **not** merged: the
pre-existing gate has live consumers, and consolidating them is a decision for the
architecture owner rather than something a qualification harness should do silently.
See docs/P9-QUALIFICATION.md.
"""

from .live_run import (
    DeclaredVsObserved,
    LinkName,
    LinkState,
    LiveQualificationRun,
    QualificationLink,
    QualificationVerdict,
    compare_to_declaration,
)
from .live_runner import qualify_many, run_live_qualification
from .media import MediaValidation, validate_media

__all__ = [
    "DeclaredVsObserved",
    "LinkName",
    "LinkState",
    "LiveQualificationRun",
    "MediaValidation",
    "QualificationLink",
    "QualificationVerdict",
    "compare_to_declaration",
    "qualify_many",
    "run_live_qualification",
    "validate_media",
]
