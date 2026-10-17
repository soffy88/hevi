# HEVI P6.1 — Narrative Grammar Compiler

> Status: **P6.1 COMPLETE**
> Baseline: `34df92098b548cfaf20fe74f8f410865f0b61506`
> First P6 grammar with working behaviour
> No P0-P5 module modified

---

## 1. What now works

```
ProductProfile.narrative_grammar_id
    → NARRATIVE_GRAMMAR_REGISTRY.resolve()
    → NarrativeCompiler.compile_with()
    → NarrativeIntent
    → ProductIntent          (compile_product_intent)
    → production runtime boundary
```

P6.0 shipped contracts. P6.1 ships the first grammar that actually compiles.

```
DocumentaryIntent
  grammar_id   = 'documentary'
  sequence     = (HOOK, CONTEXT, EVIDENCE, DEVELOPMENT, INTERPRETATION, CONCLUSION)
  valid        = True
  checks run   = 5
  content_hash = stable across repeated and fresh compilers
```

## 2. Two `NarrativeGrammar` types, and why

P6.0 already shipped `schema.NarrativeGrammar` (`mode` + `nodes` +
`arc_constraints`). P6.1 adds `narrative.NarrativeGrammar` (`id` + `version` +
ordered nodes + transitions + constraints). Both are legitimate and neither
shadows the other:

| | P6.0 `schema.NarrativeGrammar` | P6.1 `narrative.NarrativeGrammar` |
|---|---|---|
| Role | profile-side **declaration** | registry-side **definition** |
| Says | "this product wants a documentary arc" | "here is what a documentary arc is" |
| Cardinality | one per profile | one per grammar, shared |

Merging them would give every product a private narrative engine, which is the
failure this architecture exists to prevent. `test_p6_0_narrative_declaration_still_intact`
asserts the two remain distinct and both still work.

## 3. Model

`NarrativeNode`: `id`, `type`, `required`, `optional`, `order`, `constraints`.
`NarrativeGrammar`: `id`, `version`, `name`, `description`, `nodes`,
`transitions`, `constraints`.

Fifteen canonical node types, closed. The eleven from the spec plus four general
ones the built-in grammars need: `DEMONSTRATION`, `INTERPRETATION`,
`PATTERN_INTERRUPT`, `PAYOFF`.

`PATTERN_INTERRUPT` is vocabulary, not a short-form branch — it lives on the
shared enum, so a documentary may use it.
`test_pattern_interrupt_is_a_general_node_type` proves this by constructing it
outside any short-form grammar.

**No product-specific node types.** `test_no_product_specific_node_type` scans
all fifteen for `COMMERCIAL`, `HISTOR`, `DOCUMENTARY`, `P01`…`P10` and eleven
other tokens. `COMMERCIAL_HOOK` would mean the vocabulary had started branching
on product identity.

### Construction invariants (all fail closed)

| Invariant | Error |
|---|---|
| node ids unique | `DUPLICATE_NARRATIVE_NODE_ID` |
| `order` unique → total sequence | `AMBIGUOUS_NODE_ORDER` |
| cannot open on RESOLUTION/CONCLUSION/CTA | `INVALID_OPENING_NODE` |
| at least one required node | `NARRATIVE_GRAMMAR_WITHOUT_REQUIRED_NODE` |
| transitions reference real nodes | `DANGLING_TRANSITION` |
| no node both required and optional | `CONTRADICTORY_NODE_FLAGS` |
| node type in closed vocabulary | `UNKNOWN_NARRATIVE_NODE_TYPE` |

## 4. Registry

`NARRATIVE_GRAMMAR_REGISTRY` — the single authority.

Distinct from P6.0's `GRAMMAR_REGISTRY`, and the distinction is load-bearing:

| Registry | Holds | Answers |
|---|---|---|
| P6.0 `GRAMMAR_REGISTRY` | `GrammarKind` → contract class | "which class carries this kind?" |
| P6.1 `NARRATIVE_GRAMMAR_REGISTRY` | actual named grammar definitions | "what is a documentary arc?" |

Collapsing them would mean a dispatch table holding content, or a content store
that also dispatches.

`get()` and `resolve()` both accept `documentary`, `documentary@1.0.0` and
`documentary@v1.0.0`. A lookup that accepted only one spelling would fail closed
on a reasonable reference, which is a defect, not strictness.

Registration is immutable: duplicate `id@version` raises.

## 5. Built-in grammars

| id | sequence | constraints |
|---|---|---|
| `explanatory` | HOOK, CONTEXT, EXPLANATION, DEMONSTRATION, CONCLUSION | `min_nodes=5`, `demonstration_required` |
| `documentary` | HOOK, CONTEXT, EVIDENCE, DEVELOPMENT, INTERPRETATION, CONCLUSION | `min_nodes=6`, `evidence_before_interpretation` |
| `story` | HOOK, SETUP, CONFLICT, TURNING_POINT, RESOLUTION, CONCLUSION | `conflict_required`, `turning_point_required` |
| `short_form` | HOOK, PATTERN_INTERRUPT, DEVELOPMENT, PAYOFF, CTA | `pattern_interrupt_required`, `hook_and_payoff_required` |

Four general shapes. No `commercial.*`, no `historical.*`, no `product.*`. A
product composes these rather than owning a private shape — a private grammar per
product is a private pipeline per product in all but name.

Constraints are *semantic*, not length checks: `evidence_before_interpretation`
means a documentary that interprets before it shows has asserted, not argued.

## 6. Compiler

Three properties, each verified by an executing test:

**deterministic** — identical input yields a byte-identical
`content_hash()`. No clock, RNG or environment read. Order comes from the
grammar's `order` field, which is required to be unique, so nothing sorts
ambiguously. Proven across five repeated calls *and* across fresh compiler
instances.

**fail_closed** — unknown grammar, missing grammar id, required node excluded,
or constraint violation raises. `test_excluding_required_nodes_fails_compilation`
drops an optional DEMONSTRATION node and confirms `DEMONSTRATION_REQUIRED_BUT_ABSENT`
rather than a holed intent.

**serializable** — `to_dict()` round-trips through JSON; the hash derives from
that payload.

Five validation checks run on every compile, recorded on the intent so a
downstream stage can see validation happened:

`non_empty_sequence`, `required_nodes_present`, `grammar_constraints`,
`optional_exclusions`, `transition_integrity`

### Constraint merging

A grammar's own constraints are carried onto the intent as well as enforced
during validation, merged with the profile's by `(key, value)` with
first-occurrence-wins. Without this, a consumer of the intent could not see
*why* a node was required.

## 7. Runtime boundary

`compile_product_intent()` returns a `ProductIntent` carrying the product
identity, the compiled narrative, and the constraints. It calls no renderer,
builds no timeline, creates no shot, resolves no asset, judges no quality.

`NARRATIVE_REQUIRED_PRODUCT_TYPES` is a **requirement table**, not dispatch: it
asks whether a grammar id was declared. It does not choose one — the compiler
resolves whatever was declared through the registry. The branching guard
explicitly permits membership against a named table while rejecting an equality
compare or a product-keyed dispatch.

## 8. Guards, mutation-verified

Three mutations were injected and each was caught:

| Mutation | Result |
|---|---|
| `_DISPATCH = {"P08_COMMERCIAL": "story"}` per-product table | `test_no_product_branching` fails |
| `COMMERCIAL_HOOK` added to the node enum | `test_no_product_specific_node_type` fails |
| non-deterministic node ordering | `test_compile_explanatory` + `test_same_input_same_output` fail (77 failures) |

The first is the important one: "ten products, one engine" is only true if a
product cannot be given its own narrative path.

Boundary guards cover renderer, timeline, shot, asset, QA and provider in one
parametrized sweep over 14 forbidden module prefixes, plus targeted checks that
`NarrativeIntent` and `ProductIntent` carry no timeline/shot fields.

## 9. Acceptance

| Gate | Result |
|---|---|
| `P6.1_ARCHITECTURE` | PASS |
| `NARRATIVE_SCHEMA` | PASS |
| `NARRATIVE_REGISTRY` | PASS |
| `NARRATIVE_COMPILER` | PASS |
| `PRODUCT_CONNECTION` | PASS |
| `RUNTIME_BOUNDARY` | PASS |
| `FAIL_CLOSED` | PASS |
| `DETERMINISM` | PASS |
| `NO_SECOND_PIPELINE` | PASS |
| `NO_SECOND_RENDERER` | PASS |
| `NO_SECOND_TIMELINE` | PASS |
| `NO_SECOND_SHOT` | PASS |
| `NO_SECOND_ASSET` | PASS |
| `NO_SECOND_QA` | PASS |
| `NO_PROVIDER_AUTHORITY` | PASS |

`TESTS=107` (P6.1) + `157` (P6.0) · `RUFF=PASS` · `MYPY=PASS` ·
`P6.1_REGRESSION=PASS` · `P0_P5_REGRESSION=PASS` ·
`SOURCE_MUTATION_SCOPE=P6.1_ONLY` · `UNRELATED_DIRTY_PRESERVED=YES`

## 10. Carried forward

| Gap | Owner |
|---|---|
| `P6_0_COMPILER` still raises `COMPILER_NOT_IMPLEMENTED` | P6.2 — narrative now compiles, the P6.0 product compiler does not |
| `ProductProfile.narrative_grammar` (P6.0 declaration) is not cross-checked against `narrative_grammar_id` | P6.2 — a profile can currently declare one narrative and compile another |
| `profile_refs` unresolved against P2 | P6.2 |
| `PRODUCT_HERO` unresolvable via P2 registry | P6.8 |
| Optional-node exclusion is all-or-nothing per compile | later — per-node selection would help P06 narrative film |
