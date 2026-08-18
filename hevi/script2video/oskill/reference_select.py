"""参考图选择 + best-of-k。

组合: `pick_portrait_view` + `select_pairs_by_indices` + `compose_image_prefix_prompt`
+ `score_image_basic` / `score_image_file_size` / `score_image_dimensions`。
3O 归属(待上游): `oskill.reference_select`。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.script2video.oprim.image_score import (
    score_image_basic,
    score_image_dimensions,
    score_image_file_size,
)
from hevi.script2video.oprim.reference_pick import (
    cap_refs,
    compose_image_prefix_prompt,
    pick_portrait_view,
    select_pairs_by_indices,
)
from hevi.script2video.schemas import (
    PortraitRegistry,
    ReferenceCandidate,
    ReferenceSelection,
)

logger = logging.getLogger(__name__)

ImageGenFn = Callable[..., Awaitable[Path]]
MAX_REFS = 8


@dataclass
class CandidateImage:
    path: Path
    prompt: str = ""
    score: float = 0.0
    notes: str = ""
    index: int = 0

    @property
    def exists(self) -> bool:
        return self.path.exists()


@dataclass
class SelectionResult:
    best: CandidateImage
    all_candidates: list[CandidateImage] = field(default_factory=list)
    strategy: str = "heuristic"
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "best": {
                "index": self.best.index,
                "path": str(self.best.path),
                "score": self.best.score,
            },
            "strategy": self.strategy,
            "reasoning": self.reasoning,
            "all_candidates": [
                {"path": str(item.path), "score": item.score, "exists": item.exists}
                for item in self.all_candidates
            ],
        }


def select_reference_images_and_prompt(
    *,
    frame_description: str,
    portraits: PortraitRegistry | None = None,
    visible_characters: list[str] | None = None,
    facing_hints: dict[str, str] | None = None,
    cam_azimuth_deg: float | None = None,
    scene_frames: list[tuple[str, str]] | None = None,
    missing_info: str | None = None,
    transition_anchor: tuple[str, str] | None = None,
) -> ReferenceSelection:
    """确定性挑选:每角色最多一张视角图 + 场景锚 + 过渡构图,最多 8 张。"""
    candidates: list[ReferenceCandidate] = []
    facing_hints = facing_hints or {}
    if portraits is not None:
        for identifier in visible_characters or portraits.portraits.keys():
            portrait = portraits.get(identifier)
            if portrait is None:
                continue
            view = pick_portrait_view(
                facing_text=facing_hints.get(identifier, ""),
                cam_azimuth_deg=cam_azimuth_deg,
            )
            chosen = {
                "front": portrait.front,
                "side": portrait.side,
                "back": portrait.back,
            }.get(view) or portrait.front
            if chosen is None:
                continue
            candidates.append(
                ReferenceCandidate(
                    path=chosen.path,
                    description=chosen.description or f"A {view} view portrait of {identifier}.",
                    kind="portrait",
                    view=chosen.view,
                    character_id=identifier,
                )
            )
    if transition_anchor is not None:
        path, text = transition_anchor
        note = text
        if missing_info:
            note = (
                f"{text} Wrong elements: {missing_info}. "
                "Select this image as the main reference and replace characters "
                "with the provided portraits. Don't change the background."
            )
        candidates.append(
            ReferenceCandidate(path=Path(path), description=note, kind="transition_anchor")
        )
    for path, text in scene_frames or []:
        candidates.append(
            ReferenceCandidate(path=Path(path), description=text, kind="scene_frame")
        )

    capped = cap_refs(candidates, limit=MAX_REFS)
    pairs = [item.as_pair() for item in capped]
    prefix = compose_image_prefix_prompt(pairs)
    body = (
        f"Create an image following the given description:\n{frame_description}\n"
        "Characters should reference the selected portrait images. "
        "Environment and composition should reference any scene/transition images."
    )
    text_prompt = f"{prefix}\n{body}" if prefix else body
    return ReferenceSelection(
        pairs=pairs,
        text_prompt=text_prompt,
        selected_indices=list(range(len(pairs))),
    )


def select_pairs(pairs: list[tuple[str, str]], indices: list[int]) -> list[tuple[str, str]]:
    return select_pairs_by_indices(pairs, indices)


def select_best_image(
    candidates: list[CandidateImage],
    *,
    min_score: float = 0.0,
) -> SelectionResult:
    valid = [item for item in candidates if item.path.exists()]
    if not valid:
        raise ValueError("no valid candidate images found")
    for item in valid:
        item.score = (
            0.5 * score_image_basic(item.path)
            + 0.25 * score_image_file_size(item.path)
            + 0.25 * score_image_dimensions(item.path)
        )
    best = max(valid, key=lambda item: item.score)
    if best.score < min_score:
        logger.warning("best image score %.2f < min %.2f, selecting anyway", best.score, min_score)
    return SelectionResult(
        best=best,
        all_candidates=valid,
        strategy="heuristic",
        reasoning="weighted basic/size/aspect scores",
    )


async def generate_and_select(
    *,
    prompt: str,
    output_dir: Path,
    image_gen: ImageGenFn,
    n_candidates: int = 2,
    reference_images: list[str] | None = None,
    min_score: float = 0.0,
) -> SelectionResult:
    """best-of-k:并发生 N 张再启发式选一张。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates: list[CandidateImage] = []
    for idx in range(max(1, n_candidates)):
        path = output_dir / f"candidate_{idx}.png"
        try:
            await image_gen(
                prompt=prompt,
                output_path=path,
                reference_image_paths=list(reference_images or []),
            )
            candidates.append(CandidateImage(path=path, prompt=prompt, index=idx))
        except Exception as exc:
            logger.warning("candidate %d failed: %s", idx, exc)
    if not candidates:
        raise ValueError("no valid candidate images found")
    return select_best_image(candidates, min_score=min_score)
