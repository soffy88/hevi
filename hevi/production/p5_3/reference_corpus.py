"""HEVI P5.3 — Reference corpus: external projects as knowledge sources.

This is NOT a dependency registry. No repo is cloned, installed, or executed.
Each entry records what is reusable, whether it is architecture or recipe,
whether it is renderer-specific, its license, and how it may be adopted.

Security: READ_ONLY, NO_INSTALL, NO_EXEC by default.
"""

from __future__ import annotations

from typing import Any

from hevi.production.p5_3.schema import AdoptionMode, ReferenceRepository

# The 12 reference projects from the spec, with researched metadata.
# License values are from public knowledge; confidence is marked accordingly.
_REFERENCE_DATA: list[dict[str, Any]] = [
    {
        "repository": "OpenMontage",
        "revision": "unknown",
        "category": "montage_engine",
        "license": "unknown",
        "license_confidence": "unknown",
        "agent_interface": "CLI",
        "renderer": "FFmpeg",
        "capabilities": ["montage", "timeline", "transition"],
        "interesting_patterns": ["shot sequencing", "transition grammar"],
        "recipe_sources": ["transition_behavior", "pacing"],
        "architecture_patterns": ["pipeline decomposition"],
        "security_notes": ["verify license before any code use"],
        "adoption_mode": "REFERENCE_ONLY",
    },
    {
        "repository": "HyperFrames",
        "revision": "unknown",
        "category": "renderer",
        "license": "MIT",
        "license_confidence": "verified",
        "agent_interface": "CLI",
        "renderer": "HyperFrames",
        "capabilities": ["animation", "timeline", "caption"],
        "interesting_patterns": ["deterministic frame capture", "caption sync"],
        "recipe_sources": ["caption_behavior", "timing"],
        "architecture_patterns": ["renderer abstraction"],
        "security_notes": [],
        "adoption_mode": "CONTRACT_ADOPT",
    },
    {
        "repository": "video-shotcraft",
        "revision": "unknown",
        "category": "recipe_source",
        "license": "unknown",
        "license_confidence": "unknown",
        "agent_interface": "Python",
        "renderer": "Remotion",
        "capabilities": ["shot recipe", "camera move", "2.5D"],
        "interesting_patterns": ["shot recipe cards", "camera move vocabulary"],
        "recipe_sources": ["camera_behavior", "composition", "motion"],
        "architecture_patterns": ["recipe-driven rendering"],
        "security_notes": ["verify license before any code use"],
        "adoption_mode": "REFERENCE_ONLY",
    },
    {
        "repository": "video-talkcraft",
        "revision": "unknown",
        "category": "recipe_source",
        "license": "unknown",
        "license_confidence": "unknown",
        "agent_interface": "Python",
        "renderer": "Remotion",
        "capabilities": ["talking head", "presenter", "lip sync"],
        "interesting_patterns": ["presenter scale", "evidence overlay"],
        "recipe_sources": ["presenter_behavior", "evidence_role"],
        "architecture_patterns": ["presenter-evidence split"],
        "security_notes": ["verify license before any code use"],
        "adoption_mode": "REFERENCE_ONLY",
    },
    {
        "repository": "FireRed-OpenStoryline",
        "revision": "unknown",
        "category": "storyline_engine",
        "license": "unknown",
        "license_confidence": "unknown",
        "agent_interface": "Python",
        "renderer": "unknown",
        "capabilities": ["storyline", "narrative arc", "branching"],
        "interesting_patterns": ["narrative arc", "branching logic"],
        "recipe_sources": ["narrative_phase", "beat_role"],
        "architecture_patterns": ["story graph"],
        "security_notes": ["verify license before any code use"],
        "adoption_mode": "REFERENCE_ONLY",
    },
    {
        "repository": "vox-director",
        "revision": "unknown",
        "category": "director_engine",
        "license": "unknown",
        "license_confidence": "unknown",
        "agent_interface": "Python",
        "renderer": "unknown",
        "capabilities": ["director", "shot plan", "continuity"],
        "interesting_patterns": ["continuity tracking", "shot planning"],
        "recipe_sources": ["beat_role", "continuity"],
        "architecture_patterns": ["director pipeline"],
        "security_notes": ["verify license before any code use"],
        "adoption_mode": "REFERENCE_ONLY",
    },
    {
        "repository": "Paper-Cut",
        "revision": "unknown",
        "category": "animation_style",
        "license": "unknown",
        "license_confidence": "unknown",
        "agent_interface": "unknown",
        "renderer": "unknown",
        "capabilities": ["paper cutout", "stop motion", "craft"],
        "interesting_patterns": ["paper texture", "cutout composition"],
        "recipe_sources": ["composition", "texture"],
        "architecture_patterns": ["style layer"],
        "security_notes": ["verify license before any code use"],
        "adoption_mode": "REFERENCE_ONLY",
    },
    {
        "repository": "guizang-product-video-skill",
        "revision": "unknown",
        "category": "recipe_source",
        "license": "AGPL-3.0",
        "license_confidence": "verified",
        "agent_interface": "Python",
        "renderer": "unknown",
        "capabilities": ["product video", "feature reveal", "UI flow"],
        "interesting_patterns": ["product hero", "feature callout"],
        "recipe_sources": ["product_composition", "feature_reveal"],
        "architecture_patterns": ["product video pipeline"],
        "security_notes": ["AGPL-3.0: copyleft, no code import"],
        "adoption_mode": "REFERENCE_ONLY",
    },
    {
        "repository": "codex-storyboard",
        "revision": "unknown",
        "category": "storyboard_engine",
        "license": "unknown",
        "license_confidence": "unknown",
        "agent_interface": "CLI",
        "renderer": "unknown",
        "capabilities": ["storyboard", "shot list", "visual planning"],
        "interesting_patterns": ["storyboard structure", "shot sequencing"],
        "recipe_sources": ["composition", "shot_role"],
        "architecture_patterns": ["storyboard pipeline"],
        "security_notes": ["verify license before any code use"],
        "adoption_mode": "REFERENCE_ONLY",
    },
    {
        "repository": "reelbench-skills",
        "revision": "unknown",
        "category": "benchmark",
        "license": "unknown",
        "license_confidence": "unknown",
        "agent_interface": "Python",
        "renderer": "unknown",
        "capabilities": ["benchmark", "evaluation", "scoring"],
        "interesting_patterns": ["evaluation criteria", "scoring rubric"],
        "recipe_sources": [],
        "architecture_patterns": ["benchmark harness"],
        "security_notes": ["verify license before any code use"],
        "adoption_mode": "REFERENCE_ONLY",
    },
    {
        "repository": "story-to-handdrawn-video",
        "revision": "unknown",
        "category": "style_transfer",
        "license": "unknown",
        "license_confidence": "unknown",
        "agent_interface": "Python",
        "renderer": "unknown",
        "capabilities": ["handdrawn", "style transfer", "frame animation"],
        "interesting_patterns": ["handdrawn aesthetic", "frame-by-frame"],
        "recipe_sources": ["composition", "texture"],
        "architecture_patterns": ["style pipeline"],
        "security_notes": ["verify license before any code use"],
        "adoption_mode": "REFERENCE_ONLY",
    },
    {
        "repository": "data-animation-skills",
        "revision": "unknown",
        "category": "data_viz",
        "license": "unknown",
        "license_confidence": "unknown",
        "agent_interface": "Python",
        "renderer": "unknown",
        "capabilities": ["data visualization", "chart animation", "counter"],
        "interesting_patterns": ["data reveal", "chart growth"],
        "recipe_sources": ["data_composition", "data_behavior"],
        "architecture_patterns": ["data viz pipeline"],
        "security_notes": ["verify license before any code use"],
        "adoption_mode": "REFERENCE_ONLY",
    },
]


class VideoAgentReferenceCorpus:
    """The reference corpus: external projects as knowledge sources.

    Read-only. No cloning, no installation, no execution. Each entry records
    what is reusable and how it may be adopted.
    """

    def __init__(self) -> None:
        self._repositories: dict[str, ReferenceRepository] = {}
        for data in _REFERENCE_DATA:
            repo = ReferenceRepository(**data)
            self._repositories[repo.repository] = repo

    def get(self, repository: str) -> ReferenceRepository | None:
        """Get a reference repository by name."""
        return self._repositories.get(repository)

    def list_all(self) -> list[ReferenceRepository]:
        """List all reference repositories."""
        return list(self._repositories.values())

    def list_by_adoption(self, mode: AdoptionMode) -> list[ReferenceRepository]:
        """List repositories by adoption mode."""
        return [r for r in self._repositories.values() if r.adoption_mode is mode]

    def list_recipe_sources(self) -> list[ReferenceRepository]:
        """List repositories that are recipe sources."""
        return [r for r in self._repositories.values() if r.recipe_sources]

    def count(self) -> int:
        """Number of reference repositories."""
        return len(self._repositories)


__all__ = ["VideoAgentReferenceCorpus"]
