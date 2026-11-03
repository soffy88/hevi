# Portrait 8-Dimension Graft — Attribution

Method source: generic photographic language, restated in our own
words. The forwarded article's eight-dimension structure (physical
photographic language instead of vague adjectives) is an editorial
arrangement of standard terms -- focal lengths, apertures, lighting
names, fabric names -- which are public vocabulary, not ownable
expression. No sentence, prompt, or phrase from the article is
copied anywhere in this graft; every entry's Chinese description
was written fresh for this vocabulary.

Not cited, not relied on:

- The article's "exclusive / veteran photographer" claims: the
  author and provenance were unverified, so no such claim appears
  in code, docs, or outward wording.
- "Fable 5.5": unverified as a released model version and not a
  default anywhere in this graft. No model is named as a default.
- Effectiveness claims ("quality maxed out", batch pipeline):
  unverified, never used as an acceptance standard. Whether the
  method improves images is a question for a measured A/B
  protocol (B3, separate case), not a premise of this graft.

Scope: adult portraits only. The adult gate is a hard intercept;
no minor-related wording is accepted anywhere in these gates.

Files: `hevi/image/portrait_vocab/eight_dim.py` +
`eight_dim_vocab_index.json` (32 extension entries), six
capability modules (`qa.negative_prompt_firewall`,
`qa.physical_language_gate`, `qa.adult_portrait_gate`,
`qa.restraint_ceiling_gate`, `image.portrait_eight_dim_vocab`,
`image.portrait_eight_dim_assembler`), tests
`tests/test_portrait_8dim_graft.py`. The verbatim 66-entry
`portrait_vocab_index.json` transcription is untouched.
