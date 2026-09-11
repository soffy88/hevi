# Permanent P0 golden projects

These fixtures are intentionally provider-neutral and run without GPU. They
exercise the canonical graph, compiler, Slate bridge, revision boundaries and
creative provenance. A provider capability is only a test double for plan
compilation; these tests do not assert GPU support.

- `gold_a_historical.json`: public-domain historical-style source with exact
  source spans.
- `gold_b_novel.json`: multi-chapter long-form continuity inputs.
- `gold_c_one_prompt.json`: the one-sentence product entry point.
