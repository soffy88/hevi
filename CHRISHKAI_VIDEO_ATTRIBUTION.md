# ChrisHKAI-Video Attribution

Method source: `ChrisHKAI/ChrisHKAI-Video` (MIT, Copyright 2026
ChrisHKAI), skill `creator-toy-intro`: paste a creator's X link,
get a 30-second self-introduction film whose lead is a 3D vinyl
toy made from the creator's avatar, built entirely in code —
no video generation, no image generation, no stock footage.
Reviewed 2026-11-06 from a read-only tarball snapshot (main
branch, last push 2026-11-05); see
`~/workspace/hevi-vs-chrishkai-video.md` for the full
verification table.

## What was grafted

Clean-room method restatements only, in own words. No upstream
code, no character `toy.json`, no demo creator avatars, posts
or toy images, no lemo sample-library audio files, no example
films, no Grok account, no X login, no Blender render. The
nine A gates are discipline checks only; the four B schemas
are fake contracts with `executed_here: false`. No voice, TTS
or cloning route exists upstream and none was added here.

## Rights notes

- Code and docs: MIT (Copyright 2026 ChrisHKAI). A film made
  from one's own material belongs to its maker; the README
  states the maker is responsible for the material in their
  own film.
- Demo creators' avatars, posts, names and toy likenesses
  belong to those creators; they were not copied.
- lemo-opuscar sampler vendored upstream under MIT (Copyright
  2026 LemoLab). The sample library is mostly CC0; Salamander
  Grand Piano is CC BY 3.0 and the MuldjordKit drums are CC BY
  4.0 — credits are required when those are used.
- Fonts do not ship with the upstream repo (system fonts);
  commercial use needs a separate foundry-license check.
- "Free open source" covers the code only. The agent itself
  (Claude Code / Codex account and tokens), optional Grok
  search (the author states about $1–1.4 per search, on the
  user's own Grok account), and GPU render time are all
  charged separately. This graft does not call any of them.

## Portrait authorization gap (A9 fills it)

The reviewed method assumes the maker is the creator and
carries no identity check: anyone could paste someone else's
page and start a film. That gap was not copied. The graft
adds `qa.third_party_portrait_authorization_gate` as a
mandatory gate: a third-party creator's portrait requires
authorization evidence, and a minor creator's portrait is
hard-blocked under hevi's minor hard-intercept rule. It
connects to the existing `qa.portrait_consent_gate`.

## Tim film rights note

The upstream Tim film (2:23) was not published because it
contains another person's keynote footage and song. That
footage and song were not touched, and no Tim material of
any kind entered this graft.

## What is not verified here

The claimed delivered films (three tester films plus isnail
0:30, kingao 0:30, cgnot996 0:42, chris-outro 0:23) were not
played or watched during review. The Blender Cycles render
contract (`video.blender_cycles_render_schema`) is fake;
real rendering needs a GPU and is a separate case. Grok and
X access are separate cases for Soffy himself.
