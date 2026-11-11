# SAND3D_ATTRIBUTION.md

Method source: [Sandflow-ai/sand3d](https://github.com/Sandflow-ai/sand3d)
— "3D modeling in Python, built for LLMs": a flat `s3d.<verb>`
vocabulary on top of Blender `bpy`, with six-format export
(GLB / URDF / USDA / IFC / OBJ / STL), joint articulation,
and program determinism digests.

Checked read-only on 2026-11-11. Repository created 2026-11-03;
last push 2026-11-11 11:48 UTC; 1836 stars / 203 forks at check
time. Version pinned for this graft: **1.6.3** (CHANGELOG:
1.6.1 first public release 2026-11-04; 1.6.3 on 2026-11-06
fixes GLB export). The repository is 8 days old at check time
and its API is still in a fast patch cycle; the graft pins the
version and never assumes a later API.

## License

Code is **Apache-2.0** (standard text, LICENSE read in full):
commercial use, modification, and distribution allowed; the
license and copyright notice must be retained and modified
files marked. No NOTICE file; no trademark grant. This graft
is a clean-room restatement of the method in hevi's own words:
no upstream code, program text, example material, or demo
video was copied into hevi. The site carries one Geist Mono
font file as a site asset; it was not carried into hevi.

## Datasets

Five program datasets, all **CC BY 4.0** (verified against the
Hugging Face API at check time): objaverse, cad, articraft,
simready, automate. Any use must carry attribution and the
source chain; upstream mesh rights are outside this
repository's scope — the datasets contain sand3d program text,
and dataset meshes are never hevi assets. The graft's A7 gate
and B5 schema enforce this.

## Honesty notes (author claims NOT adopted as hevi-verified)

- "2–6× fewer tokens": the comparison methodology exists, but
  authorship is asymmetric — the sand3d programs were
  hand-written by the author while the Blender Python was
  written live by an LLM, and only 9 of 30 Blender programs
  built the right part. hevi states no token-saving factor.
- "Whole API fits in a prompt, about 3,600 tokens": the API
  document measured 1,818 words, which estimates to about
  2,400–3,000 tokens at 1.3–1.7 tokens per word. The 3,600
  figure was not adopted; the A4 gate requires any estimate
  to follow from a measured word count inside that band.
- "Washing machine in 38 lines": the file is 54 lines long;
  38 lines is plausibly the code-only count, which was not
  verified line by line. hevi states no line count.
- Determinism "bit for bit" means program-to-mesh digest
  equality across two fresh processes with different hash
  seeds — not byte-identical export files. The A5 gate
  enforces the digest scope and fails any byte-identical
  export claim.
- IFC GlobalIds are unstable (editing or moving a part can
  change its ID; identical parts can share one) and must not
  be used to track parts across exports. Mass, inertia, and
  dynamics (masses, frictions, efforts, drives) are outside
  what the exporter writes. The A6 gate and B4 schema carry
  both statements with the product.

## What sand3d is not

Not generative 3D (it holds no model or weights; programs are
written by a person or an LLM), not a renderer or animator
(no rendering, animation, video, or texture pipeline), and
not a CAD replacement (no parametric constraint solving, no
assembly interference checks, no mass/inertia/dynamics).
URDF export is a kinematic tree, not a simulation calibration.

## Execution layer (separate work item, not this graft)

sand3d requires bpy 4.5 (Python 3.11) or bpy 5.2 (Python 3.13)
and declares `requires-python >=3.11,!=3.12.*,<3.14`. hevi
runs Blender 4.2.17 LTS with a Python 3.14.4 virtual
environment, so sand3d cannot install or run in the existing
hevi environment. No bpy was installed here, no install
script was run, and all five B schemas are contract-only
(`executed_here: false`). A real execution environment
(py3.13 + bpy 5.2) needs Soffy's separate approval of an
environment plan.

## Red lines respected

No voice, TTS, or cloning material exists upstream and none
was added; no portrait or personal material is involved.
No credentials, keys, or network calls exist upstream.
