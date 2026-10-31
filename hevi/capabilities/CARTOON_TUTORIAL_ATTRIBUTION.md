# Attribution: 3D cartoon tutorial method intake

Source: a six-step tutorial article forwarded by Soffy (Claude Code +
Opus 5.5 + Three.js + Remotion, 3D cartoon shorts). Read-only
review: `~/workspace/hevi-vs-3d-cartoon-tutorial.md` (90 lines).

What was taken: three narrow disciplines only, clean-room
rewritten as JSON plan gates -- `qa.feedback_discipline`
(timestamp + part + expected, at most two changes per
round, unmentioned parts frozen), `pipeline.project_style_sheet`
(versioned project-local sheet with numeric fields, fresh
sample required before rendering), and `qa.voice_first_gate`
(every shot cut to a timed voice segment with word-level
timing). No tutorial prompt text, no reference image, and no
code from the tutorial was copied: the tutorial supplied no
code, and the three gates are original implementations
against hevi's own registry, critic, style-note, sample-first
and word-subtitle-contract disciplines.

What was not taken: the tutorial's "good enough is the
traffic" posture -- hevi gate standards (measured subtitles,
pixel identity, ASR checks) are unchanged; passing these
gates never means a film is finished. Reference images
shown in the tutorial were not copied into any project.

Expressly not verified / not done: Remotion word-by-word
pop-up rendering (contract layer only, render code not
audited here); Higgsfield voice MCP (no key, price or
availability verified -- not recommended, not connected);
vertical tier for `video.code_render` (still absent);
Three.js doll rig; hook-plus-twist script template (P1,
not landed); 4-second sample duration parameterisation
(P1, not landed). The tutorial's single-author claims
("dozens of hours to stabilise", "10 minutes to install")
are author statements, not reproduced evidence.
