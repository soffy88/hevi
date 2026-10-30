"""Pose reference library (``image.pose_library``).

Index-only search layer over the ai-pose-gallery-zh pose collection
(anhao/ai-pose-gallery-zh, Chinese edition of the original Japanese
gallery by Gia (@giaaibusi)). This module bundles metadata and
relative paths only: 288 pose groups, 1439 pose-by-view records,
4 systems, 26 categories, 5 views. No image bytes are bundled and
no image is copied into this repository.

The image files themselves live outside the repo, in a gallery
checkout whose location is configured with ``HEVI_POSE_GALLERY_HOME``
(default ``~/workspace/references/ai-pose-gallery-zh``). Callers
that need a real file must resolve it through this module, which
reports a missing gallery or a missing file by name instead of
pretending the picture exists.

Rights, stated so a caller cannot miss them (see
POSE_GALLERY_ATTRIBUTION.md): the repository LICENSE's MIT grant
covers source code only (index.html, scripts/, _headers). The
images under img/ and thumbs/ and the original data under data/
belong to the original author. Use is non-commercial reference
only; remove the gallery on the author's objection. All four
systems are indexed, including the sexy and two-person systems,
because the owner directed non-commercial absorption of the whole
collection on 2026-10-28; no system is filtered out here.

Risk hints are advisory heuristics over system and category only
(two-person contact and occlusion collapse most often in
generation; revealing or contact-heavy categories need a
downgrade suggestion). A hint never bans a pose: the caller
decides. The hint vocabulary (low / medium / high) matches
``video.gesture_risk_gate``; this module does not re-implement
that gate and does not judge a written gesture plan.

Usage note, borrowed as method only from the upstream skill:
a reference picture is a pose skeleton reference. Pass it to an
image or video model as a pose/composition reference and state
in the prompt that only the pose is referenced, never the
clothing, hairstyle or art style.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

SYSTEMS = ("full_standard", "full_sexy", "upper_body", "two_person")
VIEWS = ("正面", "斜侧", "侧面", "俯视", "仰视")
DEFAULT_HOME = "~/workspace/references/ai-pose-gallery-zh"
_DATA_DIR = Path(__file__).resolve().parent / "pose_gallery_data"
_INDEX_FILE = _DATA_DIR / "pose_index.json"

# Categories whose poses involve sustained body contact or
# occlusion between two people. Heuristic only, advisory only.
_CONTACT_CATEGORIES = {
    "贴身",
    "贴脸系",
    "坐位贴身",
    "立位贴身",
    "背向坐位",
    "面对面坐位",
    "骑乘位",
    "正常位（传教士）",
    "后入位",
    "侧卧位",
}
_BOLD_CATEGORIES = {"性感・大胆系", "挤胸・强调事业线系"}

_Registered = False


def gallery_home(explicit: str | None = None) -> Path:
    """Resolve the gallery checkout directory (no existence check)."""
    raw = explicit or os.environ.get("HEVI_POSE_GALLERY_HOME") or DEFAULT_HOME
    return Path(raw).expanduser()


def require_gallery_home(explicit: str | None = None) -> Path:
    """Resolve the gallery directory, failing by name when absent."""
    home = gallery_home(explicit)
    if not home.is_dir():
        raise CapabilityError(
            "image.pose_library: gallery directory not found: "
            f"{home} (set HEVI_POSE_GALLERY_HOME to a checkout of "
            "anhao/ai-pose-gallery-zh; images are not bundled in hevi)"
        )
    return home


def load_index() -> dict[str, Any]:
    """Load the bundled pose index (metadata and paths only)."""
    if not _INDEX_FILE.is_file():
        raise CapabilityError(
            "image.pose_library: bundled index missing: "
            f"{_INDEX_FILE}; regenerate it with pose_gallery_data/generate_pose_index.py"
        )
    return json.loads(_INDEX_FILE.read_text(encoding="utf-8"))


def counts() -> dict[str, Any]:
    """Return the index counts, verified against the bundled data."""
    index = load_index()
    return dict(index["counts"])


def list_systems() -> list[dict[str, Any]]:
    """List the four systems with record and group counts."""
    return list(load_index()["systems"])


def list_categories() -> list[str]:
    """List the 26 categories, sorted."""
    return list(load_index()["categories"])


def _norm(text: str | None) -> str:
    return (text or "").strip().lower()


def search_poses(
    query: str | None = None,
    system: str | None = None,
    category: str | None = None,
    view: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search pose groups by name/category text, system, category, view.

    ``query`` is a substring match over the pose name, category,
    system name and the upstream search text. ``view`` keeps only
    groups that actually have that view. Results are sorted by
    system, code, then name for stable output.
    """
    if system is not None and system not in SYSTEMS:
        raise CapabilityError(
            f"image.pose_library: unknown system {system!r}; known: {list(SYSTEMS)}"
        )
    if view is not None and view not in VIEWS:
        raise CapabilityError(
            f"image.pose_library: unknown view {view!r}; known: {list(VIEWS)}"
        )
    if category is not None and category not in list_categories():
        raise CapabilityError(
            f"image.pose_library: unknown category {category!r}"
        )
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise CapabilityError("image.pose_library: limit must be a positive integer")
    q = _norm(query)
    hits: list[dict[str, Any]] = []
    for group in load_index()["groups"]:
        if system is not None and group["system"] != system:
            continue
        if category is not None and group["category"] != category:
            continue
        if view is not None and group["views"].get(view) is None:
            continue
        if q:
            haystack = " ".join(
                [
                    group["name"],
                    group["category"],
                    group["system_name"],
                    group["search_text"],
                    group["key"],
                ]
            ).lower()
            if q not in haystack:
                continue
        hits.append(group)
    hits.sort(key=lambda g: (g["system"], g["code"], g["name"]))
    return hits[:limit]


def get_pose(system: str, code: str) -> dict[str, Any]:
    """Return one pose group by system and pose code (for example P001)."""
    if system not in SYSTEMS:
        raise CapabilityError(
            f"image.pose_library: unknown system {system!r}; known: {list(SYSTEMS)}"
        )
    key = f"{system}_{code}"
    for group in load_index()["groups"]:
        if group["key"] == key:
            return group
    raise CapabilityError(
        f"image.pose_library: no pose group {key!r} in the bundled index"
    )


def get_pose_by_key(key: str) -> dict[str, Any]:
    """Return one pose group by its index key (system_code)."""
    for group in load_index()["groups"]:
        if group["key"] == key:
            return group
    raise CapabilityError(
        f"image.pose_library: no pose group {key!r} in the bundled index"
    )


def view_files(
    pose: dict[str, Any],
    view: str,
    home: str | None = None,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    """Resolve a pose view to absolute thumbnail and image paths.

    Returns existence flags per file. With ``strict=True`` a
    missing gallery directory, a missing view, or a missing file
    raises CapabilityError naming the path; nothing is faked.
    """
    if view not in VIEWS:
        raise CapabilityError(
            f"image.pose_library: unknown view {view!r}; known: {list(VIEWS)}"
        )
    entry = pose["views"].get(view)
    if entry is None:
        raise CapabilityError(
            f"image.pose_library: pose {pose['key']!r} has no {view!r} view "
            f"(missing views: {pose['missing_views']})"
        )
    root = gallery_home(home)
    thumb = root / entry["thumb"]
    image = root / entry["image"]
    result = {
        "pose": pose["key"],
        "view": view,
        "record_id": entry["id"],
        "thumb": str(thumb),
        "image": str(image),
        "thumb_exists": thumb.is_file(),
        "image_exists": image.is_file(),
    }
    if strict:
        if not root.is_dir():
            raise CapabilityError(
                "image.pose_library: gallery directory not found: "
                f"{root} (set HEVI_POSE_GALLERY_HOME)"
            )
        missing = [p for p, ok in ((thumb, result["thumb_exists"]), (image, result["image_exists"])) if not ok]
        if missing:
            raise CapabilityError(
                "image.pose_library: missing pose files: "
                + ", ".join(str(p) for p in missing)
            )
    return result


def check_gallery(home: str | None = None) -> dict[str, Any]:
    """Check every indexed file against the gallery checkout on disk.

    Returns the full missing list (empty when the checkout is
    complete). A missing gallery directory is reported, not
    raised, so a caller can show the gap; use
    ``require_gallery_home`` when absence must fail.
    """
    root = gallery_home(home)
    index = load_index()
    missing: list[str] = []
    present = 0
    total = 0
    for group in index["groups"]:
        for view in VIEWS:
            entry = group["views"].get(view)
            if entry is None:
                continue
            for rel in (entry["thumb"], entry["image"]):
                total += 1
                if (root / rel).is_file():
                    present += 1
                else:
                    missing.append(rel)
    return {
        "home": str(root),
        "home_exists": root.is_dir(),
        "total_files": total,
        "files_present": present,
        "files_missing": len(missing),
        "missing": sorted(missing),
        "counts": index["counts"],
    }


def risk_hint(pose: dict[str, Any]) -> dict[str, Any]:
    """Advisory generation-risk hint for one pose group.

    Heuristic over system and category only; it is not a
    measurement of this pose and it never bans use. High tier
    always carries a downgrade suggestion, following the
    ``video.gesture_risk_gate`` convention (warn, do not fail).
    """
    if pose["system"] == "two_person" or pose["category"] in _CONTACT_CATEGORIES:
        return {
            "pose": pose["key"],
            "tier": "high",
            "reason": (
                "two-person contact/occlusion pose: hands, limbs and "
                "faces overlap and collapse most often in generation"
            ),
            "suggestion": (
                "split the beat per role with single-person standard "
                "poses, or keep this pose only as a composition "
                "reference and verify hands and faces frame by frame"
            ),
        }
    if pose["system"] == "full_sexy" or pose["category"] in _BOLD_CATEGORIES:
        return {
            "pose": pose["key"],
            "tier": "medium",
            "reason": (
                "revealing-leaning pose: use the skeleton only, never "
                "the outfit or styling, as the reference"
            ),
            "suggestion": (
                "reference the pose skeleton only; state in the prompt "
                "that only the pose is referenced, not clothing, "
                "hairstyle or art style"
            ),
        }
    hint: dict[str, Any] = {
        "pose": pose["key"],
        "tier": "low",
        "reason": "single-person standard/upper-body pose with no sustained contact",
        "suggestion": "",
    }
    if pose["missing_views"]:
        hint["reason"] += f"; views missing: {pose['missing_views']}"
        hint["suggestion"] = (
            "request the missing view from another angle of the same "
            "pose group instead of inventing it"
        )
    return hint


def pose_with_hint(
    pose: dict[str, Any], home: str | None = None
) -> dict[str, Any]:
    """Return a pose group with its risk hint and file existence flags."""
    root = gallery_home(home)
    views: dict[str, Any] = {}
    for view in VIEWS:
        entry = pose["views"].get(view)
        if entry is None:
            views[view] = None
            continue
        views[view] = {
            "id": entry["id"],
            "thumb": str(root / entry["thumb"]),
            "image": str(root / entry["image"]),
            "thumb_exists": (root / entry["thumb"]).is_file(),
            "image_exists": (root / entry["image"]).is_file(),
        }
    return {
        **{k: v for k, v in pose.items() if k != "views"},
        "views": views,
        "risk": risk_hint(pose),
        "home": str(root),
        "home_exists": root.is_dir(),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    action = params.get("action", "search")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if action == "search":
        result: dict[str, Any] = {
            "action": "search",
            "poses": [
                pose_with_hint(p, params.get("home"))
                for p in search_poses(
                    query=params.get("query"),
                    system=params.get("system"),
                    category=params.get("category"),
                    view=params.get("view"),
                    limit=int(params.get("limit", 50)),
                )
            ],
            "counts": counts(),
        }
    elif action == "get":
        pose = get_pose(params["system"], params["code"])
        result = {"action": "get", "pose": pose_with_hint(pose, params.get("home"))}
    elif action == "check":
        result = {"action": "check", "gallery": check_gallery(params.get("home"))}
    else:
        raise CapabilityError(
            f"image.pose_library: unknown action {action!r}; known: search, get, check"
        )
    report_path = out_dir / "pose_library_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path)},
    )


def register_pose_library_capabilities_once() -> list[str]:
    """Register image.pose_library exactly once (report only)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="image.pose_library",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "query": {"type": "string"},
                    "system": {"type": "string"},
                    "category": {"type": "string"},
                    "view": {"type": "string"},
                    "code": {"type": "string"},
                    "limit": {"type": "integer"},
                    "home": {"type": "string"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Pose reference library (index only, no images bundled): "
                "search 288 pose groups / 1439 pose-by-view records over "
                "4 systems, 26 categories and 5 views from "
                "ai-pose-gallery-zh; resolves thumbnail and image paths "
                "under HEVI_POSE_GALLERY_HOME, reports missing files by "
                "name, and attaches an advisory generation-risk hint. "
                "Non-commercial reference use only. Report only; never "
                "generates an image."
            ),
            line="image",
        )
    )
    return ["image.pose_library"]


register_pose_library_capabilities_once()
