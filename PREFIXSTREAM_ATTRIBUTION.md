# Attribution: PrefixStream relay discipline (A1-A5)

Method source: knoic/ComfyUI-MiniMaxH3-PrefixStream (MIT,
Copyright (c) 2026 knoic), a third-party ComfyUI plugin with no
affiliation to MiniMax. Read-only review only:
`~/workspace/hevi-vs-prefixstream.md` (2026-11-02). No plugin
code was copied, no workflow JSON was copied, no weights were
downloaded, and no ComfyUI connection was made.

What was taken, restated in hevi's own words: the *discipline*
behind the relay method -- a fixed 5+17k frame grid with
compile-time snapping, context sources that must name a real
produced clip, clip records with parent lineage and human-only
ratings, disk-segmented output with a manifest and hard-cut
geometry rejection, and a degradation ledger that never certifies
a long relay clean. The five gates in this graft
(`qa.continuation_grid_gate`, `qa.continuation_source_gate`,
`qa.clip_lineage_schema`, `qa.disk_stream_gate`,
`qa.degradation_ledger`) judge plans and records only.

What was deliberately NOT taken:

- Plugin source code, node implementations, and the example
  workflow JSON (bf16 + turbo LoRA configuration): not copied,
  not adapted. The execution gates B1-B3 (mask relay contract,
  clip-bin execution adapter, slice/refill verification) wait on
  a GPU and a ComfyUI install and are not in this commit.
- The KV-cache engine: a legacy exploration, not the production
  path; untouched.
- Anti-Burn LoRA and soft-mask remedies: unverified experiments.
  They appear in the degradation ledger only as names that must
  be marked unverified; they are never defaults and never claimed
  verified.
- Author-reported numbers: none used as default thresholds. The
  grid rule (base 5, step 17) is the discipline itself; every
  frame count, rating, and observation is caller-declared.
- The Clip Bin "tags" field: mentioned in upstream documentation
  but absent from the record type in code. Treated as
  unimplemented; plans declaring it fail rather than pass on a
  field no executor can honour.

Known unsolved problem, carried verbatim in spirit: degradation
accumulates over long relays and is an open issue upstream. The
degradation ledger records observations; a complete ledger is
not evidence that a video is undegraded. Real relay verification
requires the rented-GPU run (see `~/workspace/h3-gpu-runbook.md`):
segment 01 smoke first, without PrefixStream; two-segment relay
only after single-segment generation is proven.
