"""D7-B: project identity hardening.

HEVI has one project-shaped authority (the production/task id) and no second
project model. ``project_id`` on identity bindings and continuity is the
**immutable canonical key** — never a mutable display name. This module
validates that key so it can never be a filesystem path escape or a
collision-prone free string.

Display names stay free-form and must never be used as an authority key.
"""

from __future__ import annotations

import re

MAX_PROJECT_ID_LENGTH = 200
# Canonical keys are opaque ids: letters, digits, dash, underscore, dot, colon.
_ALLOWED = re.compile(r"^[A-Za-z0-9._:-]+$")


class ProjectIdentityError(ValueError):
    """Refusal with a stable machine code."""


def validate_project_id(value: str) -> str:
    """Return the canonical project id or refuse with a stable code."""
    project = str(value or "").strip()
    if not project:
        raise ProjectIdentityError("PROJECT_ID_REQUIRED")
    if len(project) > MAX_PROJECT_ID_LENGTH:
        raise ProjectIdentityError("PROJECT_ID_TOO_LONG")
    if project in {".", ".."} or ".." in project:
        raise ProjectIdentityError("PROJECT_ID_TRAVERSAL")
    if "/" in project or "\\" in project:
        raise ProjectIdentityError("PROJECT_ID_PATH_SEPARATOR")
    if any(ord(ch) < 32 for ch in project):
        raise ProjectIdentityError("PROJECT_ID_CONTROL_CHAR")
    if not _ALLOWED.match(project):
        # Unicode/spaces are display names, not authority keys.
        raise ProjectIdentityError("PROJECT_ID_NOT_CANONICAL")
    return project


__all__ = ["MAX_PROJECT_ID_LENGTH", "ProjectIdentityError", "validate_project_id"]
