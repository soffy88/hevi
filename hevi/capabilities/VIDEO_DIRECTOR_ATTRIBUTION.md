# video-director method attribution

Source repository: win4r/video-director
(https://github.com/win4r/video-director).

Method ideas borrowed, text self-written: a pre-render timeline
gate (scene gaps, hook/CTA legibility, text size floors, term
said+shown, VO timestamp order, caption speed, hero and silence);
a rendered-film defect scan (flash/pop, cut-vs-plan, frozen,
flat, loop seam); rendered-text measurement (Otsu split, cap
height, contrast); an independent critic review discipline (nine
axes, P0/P1/P2 defects, ship bar, one fix round, revision pixel
identity over pre-encode frames); and three on-screen facts
wording rules (moving counters carry no value label, unfinished
periods marked to date, timing not written as cause).

Licence, verified against the repository LICENSE file: MIT
(Copyright (c) 2026 win4r). That MIT licence covers the source
repository itself only.

No video-director text, code, prompts, graders, scripts, images
or demo videos are copied into this repository. All module text,
rules and tests here were written for hevi from the method ideas
above. Thresholds taken from the source method are labelled as
configurable method defaults in each module; where hevi already
had a stricter or verified value (loudness in mix_recipe), the
hevi value stays authoritative and no parallel gate was created.

Eval figures quoted in the source repository (28/28, 30/32 and
blind-preference counts) are the author's own self-reported,
single-run results and were not reproduced here; they are not
presented as hevi results. The hevi-side comparison harness in
tests/test_video_director_eval.py reports only what it measured.

Not implemented from the source method: page-level checks that
need a page contract (deterministic two-way render diff, text
boundary tracking, anchor stability), and ASR checking of voice
over against the script. Those remain unimplemented and are not
claimed anywhere in the gated code.
