# Eian Short-Film Workflow Attribution

Method source: Eian, "From one idea to a finished film" (Chinese
article shared by Soffy, 2026-11-06; archived read-only at
`~/workspace/references/eian-video-workflow.md`, not for
redistribution). The article is a method write-up: no code, no
weights, no models, no sample media. This graft takes method
only, restated in the reviewers' own words. No prompt text from
the article was copied into the repository.

## What was checked (2026-11-06, see `hevi-vs-eian-video-workflow.md`)

- Seedance 2.5 model id `doubao-seedance-2-5-260628` and Seedance
  2.0 mini model id `doubao-seedance-2-0-mini-260615`: confirmed
  against Volcano Engine Ark model pages.
- Pricing is per million tokens on the official basis: 2.5 at
  70 CNY per million tokens, 2.0 mini at 23 CNY per million
  tokens (about 3.04x apart). The article's per-second figures
  (about ¥1.5/s and ¥0.5/s at 720p) are the author's own
  conversions and check out arithmetically; the bill and the
  official pricing page always govern. The per-million-token
  rates above are the rates the gates enforce.
- ARK endpoint shape `POST .../api/v3/contents/generations/tasks`
  with task polling `GET .../tasks/{id}`: confirmed against
  multiple sources including an official documentation snapshot.
  Opening Seedance requires an account balance above ¥200, a
  ¥200+ savings plan, or remaining resource-package balance.
- Codex CLI invocation in the article is partly accurate: the
  flags exist, but `-i` is variadic and swallows a following
  `-`, and image generation needs `-s workspace-write`, not
  `-s read-only`. The graft records no Codex invocation.
- The author's case numbers (a 13% size drift on a cup, a very
  low re-draw rate, music leaking into a 2.5 clip, end-frame
  jumps, first-frame over-sharpening, 2.0 mini darkening over a
  clip, quota exhaustion after an OpenAI billing merge) are the
  author's own case notes. They were not independently verified
  and are not repeated here as facts; the gates do not depend
  on them.

## Four-thread mapping only

The article's four-thread mode (lead maker, reviewer,
supervisor, agent) is recorded as a mapping for reference
only: reviewer to the blind-review gate, supervisor to a
standing decision ledger, agent to an approval card. The
mapping is not an equivalence claim. No hevi or veya
mechanism is the four-thread mode, and the contract
(`video.four_thread_contract`) fails any plan that claims
equivalence.

## What this graft does not touch

- No prompt text from the article was copied into the repo.
- No ARK/Seedance key, no Codex account, no quota: registration
  and payment are Soffy's own steps, never handled here.
- No real Seedance call and no real Codex image run: the B1
  schema is a fake contract (`executed_here: false`); real
  submission is a separate keyed case.
- No weights, no sample media, no image assets: the B4
  character sheet carries text only.
- The author's case numbers are not stated as verified facts
  anywhere in the new modules.
- The free-route-first line of hevi stands: the article assumes
  paid generation is the norm; hevi prefers free routes, and
  the economy gate prices paid generation without preferring it.
