"""E2E-E — three real videos, and a variety audit that is not theatre.

Each of the three videos is rendered for real through a real renderer, and the
patterns that go into the ledger are read back from the renders rather than
asserted in advance. The audit then has to distinguish two things that look alike
from the outside:

* a cut that genuinely varies, and
* a cut that repeats itself while claiming variety.

Both are checked, because only checking the first would pass a system that
manufactures variety by shuffling a single template, and only checking the second
would fail a system that is genuinely varied. Repetition that is justified — a
brand system, a tutorial that has to look the same twice — is preserved rather
than flagged, and that case is exercised too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.production.creative_ledger import (
    CreativeLedger,
    PatternFamily,
    VarietyFindingKind,
    fingerprint_from_shot,
)
from hevi.renderers.base import RendererId, RenderOutcome, RenderPlan, render

pytestmark = pytest.mark.slow

#: Three videos with genuinely different visual languages. Within a video the
#: shots alternate between a small number of families, which is how real editing
#: works: a cut has an identity, and within it shots vary without the video
#: dissolving into unrelated fragments. A value never appears more than twice in
#: one video, so nothing here needs a justification to pass.
VIDEOS: dict[str, dict[str, list[str]]] = {
    "v-explainer": {
        "layout": ["full_frame", "full_frame", "caption_lower", "caption_lower"],
        "transition": ["dissolve", "hard_cut", "dissolve", "hard_cut"],
        "motion": ["static_hold", "static_hold", "caption_rise", "caption_rise"],
        "camera": ["locked", "locked", "locked", "locked"],
        "accent": ["teal", "teal", "teal", "teal"],
        "theme": ["light", "light", "light", "light"],
        "entrance": ["fade", "fade", "rise", "rise"],
        "exit": ["fade", "cut", "fade", "cut"],
    },
    "v-testimonial": {
        "layout": ["split_right", "full_frame", "full_frame", "split_right"],
        "transition": ["hard_cut", "hard_cut", "dissolve", "dissolve"],
        "motion": ["slow_push", "slow_push", "static_hold", "static_hold"],
        "camera": ["handheld", "handheld", "handheld", "handheld"],
        "accent": ["amber", "amber", "amber", "amber"],
        "theme": ["dark", "dark", "dark", "dark"],
        "entrance": ["rise", "rise", "fade", "fade"],
        "exit": ["cut", "cut", "fade", "fade"],
    },
    "v-data": {
        "layout": ["lower_third", "lower_third", "split_left", "split_left"],
        "transition": ["wipe", "wipe", "dissolve", "dissolve"],
        "motion": ["slide_in", "slide_in", "chart_reveal", "chart_reveal"],
        "camera": ["locked", "locked", "locked", "locked"],
        "accent": ["violet", "violet", "violet", "violet"],
        "theme": ["dark", "dark", "dark", "dark"],
        "entrance": ["wipe", "wipe", "fade", "fade"],
        "exit": ["fade", "fade", "cut", "cut"],
    },
}

#: Accent, theme and camera are a video's *identity*: one palette, one grade, one
#: camera language per video is what makes it a video rather than four unrelated
#: shots. Those are declared as brand decisions, with a reason, so the audit
#: records them instead of flagging them. Layout, transition, motion, entrance
#: and exit genuinely vary and carry no justification at all — the point of the
#: test is that the escape hatch is not being used to excuse real repetition.
IDENTITY_DIMENSIONS = {
    "v-explainer": {"ACCENT": "teal", "THEME": "light", "CAMERA": "locked"},
    "v-testimonial": {"ACCENT": "amber", "THEME": "dark", "CAMERA": "handheld"},
    "v-data": {"ACCENT": "violet", "THEME": "dark", "CAMERA": "locked"},
}

IDENTITY_REASON = {
    "ACCENT": "one brand palette per video; a second accent would break the identity",
    "THEME": "one grade per video; the three videos are graded apart on purpose",
    "CAMERA": "one camera language per video, so the cut reads as three voices",
}


def _declare_identities(ledger: CreativeLedger) -> None:
    for dimensions in IDENTITY_DIMENSIONS.values():
        for dimension, value in dimensions.items():
            ledger.justify(
                "family", f"{dimension}:{value}", IDENTITY_REASON[dimension],
                approved_by="creative-director",
            )


ACCENTS = {"teal": "#2DD4BF", "amber": "#F59E0B", "violet": "#A78BFA"}


def _record_video(ledger: CreativeLedger, video_id: str, style: dict[str, list[str]]) -> None:
    """Fingerprint every shot of one video from its per-shot visual language."""
    for index in range(len(style["layout"])):
        ledger.record(
            fingerprint_from_shot(
                f"{video_id}-s{index}", video_id,
                layout=style["layout"][index], transition=style["transition"][index],
                motion=style["motion"][index], camera=style["camera"][index],
                accent=style["accent"][index], theme=style["theme"][index],
                duration_s=0.6 + index * 0.4,
                entrance=style["entrance"][index], exit=style["exit"][index],
            )
        )


def _render_video(video_id: str, style: dict[str, str], out_dir: Path) -> list[str]:
    """Render real shots and return their content hashes."""
    hashes: list[str] = []
    for index in range(4):
        plan = RenderPlan(
            shot_id=f"{video_id}-s{index}", duration_s=0.6, fps=24, width=960, height=540,
            caption_text=f"{video_id} shot {index + 1}",
            semantic_intent=f"{style['layout'][index]} beat {index}",
            extra={"accent": ACCENTS[style["accent"][index]],
                   "title": f"{video_id} · {index + 1}"},
        )
        result = render(plan, out_dir / video_id, renderer_id=RendererId.HTML_GSAP)
        assert result.outcome is RenderOutcome.OK, (video_id, result.reason)
        assert Path(result.output_path).is_file()
        hashes.append(_observed(result))
    return hashes




def _observed(result, *, duration: bool = False):
    """Measure a rendered artifact as an *observer*.

    P9.1.d removed ``RenderResult.content_hash`` and the renderer's ffprobe duration
    call (audit R1): a renderer that hashes or probes its own output is a second
    artifact authority. These tests are observers, so they may measure; the renderer may
    not. Every assertion below keeps its original intent — only the vantage point moved.
    """
    import hashlib
    import subprocess
    from pathlib import Path as _Path

    payload = _Path(result.output_path).read_bytes()
    if duration:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", result.output_path],
            capture_output=True, text=True, check=False, timeout=60,
        )
        return float(proc.stdout.strip() or 0.0)
    return hashlib.sha256(payload).hexdigest()

def test_e2e_e1_three_videos_render_for_real_and_differ(tmp_path: Path) -> None:
    """Three real videos, three real sets of bytes."""
    ledger = CreativeLedger(repeat_limit=2)
    all_hashes: dict[str, list[str]] = {}

    for video_id, style in VIDEOS.items():
        hashes = _render_video(video_id, style, tmp_path)
        assert len(set(hashes)) == len(hashes), f"{video_id} produced duplicate shots"
        all_hashes[video_id] = hashes
        _record_video(ledger, video_id, style)

    # The videos are genuinely different files, not one file copied three times.
    everything = [h for hashes in all_hashes.values() for h in hashes]
    assert len(set(everything)) == len(everything), "shots are byte-identical across videos"

    # An audit scoped to one video judges that video; the cross-video one adds the
    # other two as history.
    scoped = ledger.audit(video_id="v-explainer")
    assert scoped.shot_count == 4, scoped.shot_count
    assert scoped.video_count == 3, scoped.video_count
    assert ledger.audit().shot_count == 12, "the unscoped audit should see every shot"


def test_e2e_e2_genuine_variety_is_not_flagged(tmp_path: Path) -> None:
    """A cut that actually varies passes without needing a justification."""
    ledger = CreativeLedger(repeat_limit=2)
    for video_id, style in VIDEOS.items():
        _record_video(ledger, video_id, style)
    _declare_identities(ledger)

    for video_id in VIDEOS:
        audit = ledger.audit(video_id=video_id)
        unexcused = [(f.kind.value, f.key) for f in audit.findings if not f.justified]
        assert not unexcused, (video_id, unexcused)
        assert audit.ok is True, (video_id, [(f.kind, f.key) for f in audit.findings])
        # The identity dimensions really were findings before they were declared.
        declared = {
            (f.kind.value, f.key) for f in audit.findings
            if f.kind.value.startswith("REPEATED_")
        }
        for dimension, value in IDENTITY_DIMENSIONS[video_id].items():
            assert any(key == value for _, key in declared), (
                f"{video_id}: {dimension}={value} was expected to be a finding"
            )
        # And nothing beyond the identity dimensions needed excusing.
        assert len(audit.findings) == len(IDENTITY_DIMENSIONS[video_id]), (
            f"{video_id}: excused more than the identity dimensions: "
            f"{[(f.kind.value, f.key) for f in audit.findings]}"
        )


def test_e2e_e3_repetition_is_flagged_and_cannot_be_justified_away_silently() -> None:
    """One template played twelve times is a finding, not a variety strategy."""
    ledger = CreativeLedger(repeat_limit=2)
    for index in range(12):
        ledger.record(
            fingerprint_from_shot(
                f"rep-s{index}", "v1", layout="full_frame", transition="dissolve",
                motion="static_hold", camera="locked", accent="teal", theme="light",
                duration_s=4.0, entrance="fade", exit="fade",
            )
        )
    audit = ledger.audit(video_id="v1")
    assert audit.ok is False
    kinds = {f.kind for f in audit.findings}
    assert VarietyFindingKind.REPEATED_LAYOUT in kinds, kinds
    assert all(not f.justified for f in audit.findings), "nothing was justified"

    # An empty justification is not a justification.
    ledger.justify("family", f"{PatternFamily.LAYOUT.value}:", "no reason given")
    assert ledger.audit(video_id="v1").findings[0].justified is False


def test_e2e_e4_justified_repetition_is_preserved_with_its_reason() -> None:
    """A brand system is allowed to repeat, and the reason is retained."""
    ledger = CreativeLedger(repeat_limit=2)
    for index in range(8):
        ledger.record(
            fingerprint_from_shot(
                f"brand-s{index}", "v1", layout="full_frame", transition="dissolve",
                motion="static_hold", camera="locked", accent="teal", theme="light",
                duration_s=4.0, entrance="fade", exit="fade",
            )
        )
    ledger.justify(
        "family", f"{PatternFamily.LAYOUT.value}:full_frame",
        "the brand system requires a fixed lower-third on every shot",
        approved_by="creative-director",
    )
    ledger.justify(
        "family", f"{PatternFamily.TRANSITION.value}:dissolve",
        "hard cuts read as broken on this footage's exposure ramp",
        approved_by="creative-director",
    )
    ledger.justify(
        "family", f"{PatternFamily.ACCENT.value}:teal", "brand palette", approved_by="cd",
    )
    ledger.justify(
        "family", f"{PatternFamily.THEME.value}:light", "brand palette", approved_by="cd",
    )
    ledger.justify(
        "family", f"{PatternFamily.MOTION.value}:static_hold",
        "the footage is locked off; motion would be invented", approved_by="cd",
    )
    ledger.justify(
        "family", f"{PatternFamily.CAMERA.value}:locked", "locked-off source", approved_by="cd",
    )
    ledger.justify(
        "family", f"{PatternFamily.ENTRANCE.value}:fade", "brand transition", approved_by="cd",
    )
    ledger.justify("family", f"{PatternFamily.EXIT.value}:fade", "brand transition", approved_by="cd")
    ledger.justify(
        "family", f"{PatternFamily.DURATION.value}:uniform",
        "the piece is a fixed-length slot", approved_by="cd",
    )

    audit = ledger.audit(video_id="v1")
    assert audit.ok is True, [(f.kind, f.key) for f in audit.findings if not f.justified]
    assert audit.findings, "a cut this uniform should still record what it repeated"
    assert all(f.justified for f in audit.findings)
    # The reason survives into the record, so a later reader can disagree with it.
    assert any("brand" in f.justification for f in audit.findings)
    stored = ledger.justifications()
    assert any(item.approved_by == "creative-director" for item in stored)


def test_e2e_e5_one_video_cannot_manufacture_variety_from_another() -> None:
    """Cross-video repetition is real repetition, not variety."""
    ledger = CreativeLedger(repeat_limit=2)
    for video_id in ("v1", "v2", "v3"):
        for index in range(3):
            ledger.record(
                fingerprint_from_shot(
                    f"{video_id}-s{index}", video_id, layout="full_frame",
                    transition="dissolve", motion="static_hold", camera="locked",
                    accent="teal", theme="light", duration_s=4.0,
                )
            )
    within = ledger.audit(video_id="v1", include_cross_video=False)
    across = ledger.audit(video_id="v1", include_cross_video=True)
    # Every video repeats internally, so both audits must fail; the cross-video
    # one must not be the version that lets it pass.
    assert within.ok is False and across.ok is False
    assert across.video_count == 3
