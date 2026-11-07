"""Packaging component vocabulary (``qa.packaging_component_vocabulary``).

Clean-room method index, restated in hevi's own words, of the
packaging-component discipline in ``hevi-vs-digital-human-koubo-recheck.md``
item B4: a finished piece is assembled from small on-screen
components -- title bars, evidence cards, counters, maps, and the
like -- each with one job and one limit. This module is only the
index: component names with a purpose and a constraint, written
here from the plain meaning of each name and from ordinary
editing discipline. It contains no template text, no template
code, no demonstration imagery, and no author material.

Two cautions from the recheck are carried here. First, the
upstream component count is inconsistent in its own documents
(about 47-48 claimed, 43 previews present); this vocabulary
therefore claims no total and indexes only the components it
names. Second, no figure from the upstream author's own reports
is used as a threshold anywhere in this module: every numeric
limit in a plan is caller-supplied.

A packaging plan is judged component by component: every
component a plan uses must be in this vocabulary, and every use
must declare its own purpose and its own constraint. A use with
no constraint fails -- an unconstrained overlay is how a frame
ends up covered, a figure ends up unlabelled, or a claim ends up
presented as fact. A plan carrying template text fails: the
vocabulary is a method index, not a template store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Each entry: name, purpose, constraint. All wording is hevi's own.
_PACKAGING_COMPONENTS: tuple[dict[str, str], ...] = (
    {
        "name": "LowerThird",
        "purpose": "A bar at the bottom of the frame naming the speaker or the topic of the current passage.",
        "constraint": "One at a time; it must never cover the speaker's mouth, and it leaves when the topic changes.",
    },
    {
        "name": "NamePlate",
        "purpose": "A fixed plate showing a person's name at their first appearance.",
        "constraint": "The spelling must match the verified name list, and the plate appears once per person per piece.",
    },
    {
        "name": "KeywordStack",
        "purpose": "A short stack of the key terms of the current section, shown together.",
        "constraint": "Every term must be a term actually used in the spoken section, and the stack holds only a few terms at once.",
    },
    {
        "name": "WordStack",
        "purpose": "Single words appearing one after another in step with the spoken line.",
        "constraint": "Each word must match the word being spoken at that moment; no word may appear early.",
    },
    {
        "name": "ChapterCard",
        "purpose": "A full-frame card marking the start of a new section.",
        "constraint": "Only at section boundaries, carrying the section title and nothing else.",
    },
    {
        "name": "ProgressTracker",
        "purpose": "A thin indicator showing how far through the piece the viewer is.",
        "constraint": "It must reflect the true number of segments; it must never imply a longer or shorter piece.",
    },
    {
        "name": "ProgressChapters",
        "purpose": "Chapter marks along the timeline, labelled with the chapter titles.",
        "constraint": "Labels must match the actual chapter titles, in the actual order.",
    },
    {
        "name": "EvidenceCard",
        "purpose": "A card presenting one document, figure, or quotation as evidence for the spoken claim.",
        "constraint": "It must carry the source line on the card, and an unverified figure must never be presented as fact.",
    },
    {
        "name": "SourceDoc",
        "purpose": "A framed view of a source document, shown while it is discussed.",
        "constraint": "The source must be named on screen, and any quoted text must match the source word for word.",
    },
    {
        "name": "DocFocus",
        "purpose": "A closer view of one passage inside a document already on screen.",
        "constraint": "The passage must be legible or read aloud, and the source must stay named.",
    },
    {
        "name": "Counter",
        "purpose": "An on-screen number that counts toward a stated figure.",
        "constraint": "The number must match the verified figure, and the count must land exactly on it.",
    },
    {
        "name": "Odometer",
        "purpose": "A rolling-digit display that settles on a stated figure.",
        "constraint": "The digits must settle exactly on the verified figure, with units shown.",
    },
    {
        "name": "NumberSpike",
        "purpose": "A brief emphasis on one single number in the spoken line.",
        "constraint": "One number per spike, and the figure must be verified before the spike is used.",
    },
    {
        "name": "Charts",
        "purpose": "A simple chart visualising the numbers being discussed.",
        "constraint": "Axes and values must be labelled, and a shortened axis must be marked as shortened.",
    },
    {
        "name": "CompareWipe",
        "purpose": "A wipe transition comparing two states side by side, before and after.",
        "constraint": "Both sides must be labelled, and both sides must share the same scale.",
    },
    {
        "name": "MapRoute",
        "purpose": "A map with a route line tracing the journey being described.",
        "constraint": "The route must follow real geography, and place names must be spelled correctly.",
    },
    {
        "name": "FreezeFrame",
        "purpose": "A held still frame used to let one moment land.",
        "constraint": "The hold length is declared in the plan, and the audio during the hold is declared too.",
    },
    {
        "name": "TeaserColdOpen",
        "purpose": "A short teaser moment shown before the title, drawn from the piece itself.",
        "constraint": "The teaser must be a real moment from the piece, never a staged claim.",
    },
    {
        "name": "Highlight",
        "purpose": "A ring or box drawing the eye to the part of the frame being discussed.",
        "constraint": "It must point at the thing being discussed, and it is removed when the topic moves on.",
    },
    {
        "name": "ZoomFocus",
        "purpose": "A slow zoom into one detail of the frame.",
        "constraint": "The zoom target is declared, and the zoom must not crop out context the viewer needs.",
    },
    {
        "name": "CalloutLeader",
        "purpose": "A label joined by a line to the detail it names.",
        "constraint": "Label and target must stay connected for the whole callout.",
    },
    {
        "name": "GlassPanel",
        "purpose": "A translucent panel placed behind on-screen text.",
        "constraint": "Text over the panel must stay readable over moving picture for the whole shot.",
    },
    {
        "name": "SlamText",
        "purpose": "One large short phrase landing with emphasis.",
        "constraint": "One short phrase only, used sparingly, never over a key spoken line.",
    },
    {
        "name": "SearchTyping",
        "purpose": "Text appearing as if typed into a search box, showing the query being discussed.",
        "constraint": "The query shown must be the query actually discussed, typed in full.",
    },
    {
        "name": "TypedNameTag",
        "purpose": "A name appearing letter by letter.",
        "constraint": "The spelling must be verified before the tag is used.",
    },
    {
        "name": "PollPop",
        "purpose": "A pop-up graphic showing a poll question with its options.",
        "constraint": "Question and options are shown in full, and results are labelled as poll results, not a survey.",
    },
    {
        "name": "ReactionPop",
        "purpose": "A small window showing a recorded reaction.",
        "constraint": "The reaction must be a real recorded reaction, labelled as a reaction.",
    },
    {
        "name": "MemeWindow",
        "purpose": "A small inset clip window inside the main frame.",
        "constraint": "The inset must be licensed or original material, credited on screen.",
    },
    {
        "name": "HostFloaters",
        "purpose": "Floating labels placed around the presenter.",
        "constraint": "Only one floater family at a time, and no floater may cover the presenter's face.",
    },
    {
        "name": "PunchInHost",
        "purpose": "A cut to a closer framing of the presenter for one stressed line.",
        "constraint": "The cut must land on a stressed line, and the return framing is declared.",
    },
    {
        "name": "TiltAside",
        "purpose": "The frame tilted aside to make room for a graphic beside the presenter.",
        "constraint": "The tilt must return to level, and the presenter must stay fully in frame.",
    },
    {
        "name": "TextBehind",
        "purpose": "Text placed behind the presenter in the frame.",
        "constraint": "The separation must be real, and the text must never cover the presenter's face.",
    },
    {
        "name": "RecapBoard",
        "purpose": "A board at the end of a section summarising what was covered.",
        "constraint": "Only points already covered may appear; no new claim may be introduced on a recap board.",
    },
    {
        "name": "ReviewCards",
        "purpose": "Cards summarising the review points of a section.",
        "constraint": "One point per card, with wording matching the spoken summary.",
    },
    {
        "name": "ArchiveCards",
        "purpose": "Cards presenting archive material.",
        "constraint": "Every archive item must be dated and sourced on the card.",
    },
    {
        "name": "SpecCard",
        "purpose": "A card listing the specifications of one item.",
        "constraint": "Every value must be verified, and units must be shown for every value.",
    },
    {
        "name": "PaperCollage",
        "purpose": "A paper-texture collage used as a background.",
        "constraint": "The collage must not reduce the legibility of any text placed over it.",
    },
    {
        "name": "TornStrip",
        "purpose": "A torn-paper strip used as a transition between sections.",
        "constraint": "Transitions only at section breaks, never mid-argument.",
    },
    {
        "name": "GlitchInterstitial",
        "purpose": "A brief glitch-style break between passages.",
        "constraint": "Sparing use only, and never over a spoken key line.",
    },
    {
        "name": "HandDraw",
        "purpose": "A hand-drawn style overlay illustrating the spoken point.",
        "constraint": "The drawing must match the spoken point, and the style must stay consistent within the piece.",
    },
    {
        "name": "RetentionCaption",
        "purpose": "A persistent caption line kept on screen to hold attention through a passage.",
        "constraint": "The caption text must match the spoken line it accompanies.",
    },
    {
        "name": "Danmaku",
        "purpose": "Scrolling viewer-style comments overlaid on the picture.",
        "constraint": "Overlaid comments must be clearly marked as viewer comments, never presented as facts.",
    },
)

_VOCABULARY = {entry["name"]: entry for entry in _PACKAGING_COMPONENTS}


def _issue(code: str, detail: str, **extra: Any) -> dict[str, Any]:
    issue = {"code": code, "detail": f"qa.packaging_component_vocabulary: {detail}"}
    issue.update(extra)
    return issue


def packaging_component_vocabulary() -> list[dict[str, str]]:
    """The vocabulary: component name, purpose, and constraint, in hevi's own words."""
    return [dict(entry) for entry in _PACKAGING_COMPONENTS]


def check_packaging_plan(plan: Any) -> dict[str, Any]:
    """Judge one packaging plan. Returns a report; never raises for a bad plan."""
    issues: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "issues": [_issue("plan_not_object", "packaging plan must be an object")],
        }
    uses = plan.get("components")
    if not isinstance(uses, list) or not uses:
        issues.append(_issue(
            "components_missing",
            "components must be a non-empty list of component uses",
        ))
        return {"ok": False, "verdict": "fail", "issues": issues}
    for position, use in enumerate(uses):
        if not isinstance(use, dict):
            issues.append(_issue(
                "component_use_invalid",
                f"component use {position} must be an object",
            ))
            continue
        name = use.get("name")
        if name not in _VOCABULARY:
            issues.append(_issue(
                "component_unknown",
                f"component {name!r} is not in the packaging vocabulary; "
                "undeclared components are not used",
                name=name,
            ))
            continue
        if use.get("template_text") or use.get("template_source"):
            issues.append(_issue(
                "template_text_forbidden",
                f"component {name!r} carries template text or a template "
                "source; the vocabulary is a method index, not a "
                "template store",
                name=name,
            ))
        if not isinstance(use.get("purpose"), str) or not use["purpose"].strip():
            issues.append(_issue(
                "component_purpose_missing",
                f"component {name!r} must declare its purpose in this plan",
                name=name,
            ))
        if not isinstance(use.get("constraint"), str) or not use["constraint"].strip():
            issues.append(_issue(
                "component_constraint_missing",
                f"component {name!r} must declare its constraint in this "
                "plan; a component without a constraint fails",
                name=name,
            ))
    return {
        "ok": not issues,
        "verdict": "pass" if not issues else "fail",
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            **_kwargs: Any) -> CapabilityResult:
    plan = params.get("plan")
    report = check_packaging_plan(plan)
    report["vocabulary"] = packaging_component_vocabulary()
    report_path = Path(out_dir) / "packaging_component_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_packaging_component_vocabulary_capabilities_once() -> list[str]:
    """Register ``qa.packaging_component_vocabulary`` (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.packaging_component_vocabulary",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Packaging component vocabulary: a method index of "
                "on-screen packaging components (name, purpose, "
                "constraint, in hevi's own words). A plan must use "
                "only vocabulary components, each declaring its "
                "purpose and constraint; template text is refused. "
                "Judges plans only."
            ),
            line="qa",
        )
    )
    return ["qa.packaging_component_vocabulary"]


register_packaging_component_vocabulary_capabilities_once()
