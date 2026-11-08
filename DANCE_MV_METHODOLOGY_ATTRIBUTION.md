# Dance MV Methodology — Attribution

## Method source

The twelve discipline gates and five contract schemas in this
graft are a clean-room restatement of the method described in
the author's dance MV methodology document (revision 1.0, archived
at `~/workspace/references/dance-mv-methodology-rev1.0.md`). No
paragraph of the source document is copied: every rule below is
rewritten in hevi's own words, and every number is taken from the
method's own definitions rather than from any reported result.

The method covers: music structure and cut timing; reference
picture responsibilities; asset and prop ledgers; dance-genre
grammar; action-chain design; time windows and rotation budgets;
physical camera description; camera–action synchronisation;
transition mechanisms; H3 prompt engineering; pre-generation
checks and post-generation review; and the nine-section prompt
pack format.

## Five cited sources not found

The source document cites five supporting items that were
searched for in the workspace and in hevi and were **not found**:

1. Index's *Morning Trouble* Rev.8.7 — 178 BPM, 18 segments.
2. 《画楼春梦》 — a classical-dance reference case.
3. 《灵犀照月》 — a second classical-dance reference case.
4. Song Yu's classical-dance plan.
5. Dance-motion-chain H3 Rev.1.4 — the action-library document
   the method's chain entries point at.

Because item 5 was never found, **no action-library entry from
Rev.1.4 appears anywhere in this graft, and none was invented**:
no C-chain text, no C-chain number, and no code-shaped value
(such as a bare letter followed by one or two digits) is
accepted by any gate or schema here. The action chain gates
and schemas work on plain-language action descriptions only.
Any future graft that wants library entries must first find
and cite the actual Rev.1.4 document.

## Transition vocabulary — eleven, closed

The method's transition list is closed at eleven mechanisms:
match on action, shape match, direction match, foreground
wipe, whip pan, focus match, reflection match, rotation phase
match, hard cut on the beat, soft dissolve, and flash. The
gate `qa.dance_transition_gate` and the schema
`video.dance_transition_table_schema` both enforce exactly
these eleven and refuse any twelfth.

## Six-section format — three of six match

The method describes a six-section H3 prompt, but only three
of its section names match hevi's house six-section format
(`subject_definitions`, `summary`, `retention_analysis`,
`detailed_description`, `overall_soundscape`,
`non_diegetic_music`). This graft follows the house format
only: `qa.dance_h3_prompt_gate` imports the section list from
`hevi/capabilities/scene_reference.py` as its single source,
and refuses any other section name — including the
provider-layer field `integrated_multimodal_description`,
which is not part of the six-section format.

## What this graft does not claim

- The source document's self-reported results (timings,
  counts, and case outcomes) are **not** presented here as
  hevi-verified. No H3 generation was run and no video was
  rendered as part of this graft.
- The method's thirteen physical camera paths are **not**
  equated with hevi's camera assets: hevi's `shot.camera_movements`
  (40 entries) and `video.camera_movement_index` (46 entries)
  are different catalogues, and `video.camera_render_mapping`
  maps only 4 of 46 to a real render path. The physical-camera
  gate judges the physical facts of a shot, not a catalogue
  lookup.
- All twelve gates are discipline checks only and all five
  schemas are contract-only layers (`executed_here: false`,
  `output_file: None` on a well-formed contract;
  `CapabilityError` on any shape violation).
  Real H3 execution and GPU inference are a separate work
  item and are not part of this graft.
