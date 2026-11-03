# Toonflow method attribution

Source repository: HBAI-Ltd/Toonflow-app.

Method ideas borrowed, text self-written: segment assembly
(scenes into capped segments, one segment per generation node,
long lines split at semantic pauses without deleting words),
a three-layer asset registry (script, master assets, episode
references only; derivatives naming parent, changed and
unchanged aspects, with a default extraction boundary), and a
reference-number gate (numbered references must resolve to a
declared order, first-frame and multi-parameter modes kept
apart, script text never treated as a connection).

Licence, verified against the repository LICENSE file: MIT.
That MIT licence covers the Toonflow repository itself only;
model services, generated material and third-party plugins carry
their own terms, and nothing in this intake re-licences them.

No Toonflow text, code, prompts, images or assets are copied
into this repository. All module text, rules and tests here were
written for hevi from the ideas above.
