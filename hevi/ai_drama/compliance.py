"""Compliance gates for ai_drama references and outputs.

The hard rule: a real person or celebrity photo/voice must never be used as a
reference.  Generated (synthetic) assets are allowed; an uploaded file is only
allowed when the caller explicitly declares it synthetic.  There is no
"with consent" override for a real person's likeness here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

UPLOAD_NOTICE = (
    "不得上传真人或明星的照片/声音作为参考；只接受 AI 生成的虚构角色素材。"
    "真人肖像需走单独的授权流程，本入口不提供。"
)
MINIMAX_LICENSE_NOTICE = (
    "MiniMax H3 community licence excludes EU/UK/Korea/US; "
    "commercially-facing UI must display 'MiniMax H3'."
)
AI_LABEL = "AI 生成"


class ReferenceRejected(RuntimeError):
    pass


def assert_reference_allowed(path: str | Path, declaration: dict[str, Any] | None) -> None:
    """Reject a reference unless it is declared synthetic and not a real person."""
    if not declaration or declaration.get("synthetic") is not True or declaration.get("no_real_person") is not True:
        raise ReferenceRejected(
            f"reference {path} rejected: {UPLOAD_NOTICE} declaration must contain "
            '{"synthetic": true, "no_real_person": true}'
        )


def assert_generated_assets(assets: dict[str, Any]) -> None:
    """Every asset produced by the line itself is synthetic and safe to send."""
    for img in assets.get("images") or []:
        if img.get("synthetic") is False:
            raise ReferenceRejected(f"asset {img.get('ref')} is marked non-synthetic; refused")
        if not img.get("path"):
            continue
        # Local renders live under the episode out_dir/assets tree; a bare
        # user-supplied absolute path must carry an explicit declaration.
        if img.get("user_upload") and not img.get("declaration"):
            raise ReferenceRejected(f"asset {img.get('ref')} is a user upload without a declaration")


def output_label(edit: dict[str, Any]) -> str:
    if edit.get("ai_label") is not True:
        raise ReferenceRejected("output must carry the AI 生成 label")
    return str(edit.get("ai_label_text") or AI_LABEL)
