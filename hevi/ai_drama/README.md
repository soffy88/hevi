# ai_drama line

Availability: **internal** (quality gate: propose opening only at quality >= 4).

Topic/script -> structured script -> storyboard -> asset bible -> video
segments -> edit list -> 9:16 film. Each stage is one canvas node with its own
checks; a failed node is retried alone.

## Run offline (no key)

```bash
python -m hevi.ai_drama --episode hevi/ai_drama/data/sample_episode.json \
  --out output/ai_drama_sample --provider offline --seed 42
```

No paid API is called. Keyframe images use local SD-Turbo on CPU, voice uses
the local Piper `zh_CN-huayan-medium` voice, lip-sync uses the local Wav2Lip
ONNX model when a face is detected, and `ffmpeg` assembles the film.

## Providers

| name | requirements | pricing |
|---|---|---|
| `offline` | local models only | free |
| `runninghub_h3` | `RUNNINGHUB_API_KEY`, `RUNNINGHUB_WORKFLOW_ID`, `RUNNINGHUB_NODE_MAP` | estimated, see credentials page |
| `minimax_h3_api` | `MINIMAX_API_KEY`; `MINIMAX_FILE_BASE` for local reference media | estimated |
| `kaggle_gpu` | `kaggle` CLI + `KAGGLE_USERNAME`/`KAGGLE_KEY` | free quota, batch only |
| `wan` | reserved, no verified endpoint | n/a |

`RUNNINGHUB_NODE_MAP` is a JSON array of
`{"nodeId": "...", "fieldName": "...", "role": "prompt|image1..9|audio1..3|seed|resolution|ratio|mode"}`.
The provider refuses to invent node ids: without this map it is unavailable.
Prices in `credits.PRICE_TABLE_CNY` are planning estimates, not vendor quotes;
replace them with measured values after a 5 s preview.

Budget: `AI_DRAMA_BUDGET_CNY` (default 30 CNY per episode). A request that
would cross the cap is refused before the network call and logged to
`credit_ledger.jsonl`.

## Compliance

- MiniMax H3 community licence excludes EU/UK/KR/US; commercial UI must show
  "MiniMax H3" (see NOTICE).
- Real people / celebrities must never be used as image or voice references.
  The asset builder only writes fictional character prompts; the upload entry
  must show the same warning and block such files.
- Every film carries the "AI 生成" label; the file name and QA report keep it.
- Fonts are Noto Sans CJK / Noto Sans Mono CJK (SIL OFL 1.1).

## game_pov

`style=game_pov` adds a daily -> anomaly -> reversal check, first-person prompt
guards (where/looking/next move/visible hands, sleeves, shoes), a third-person
pass shot with an explicit composition, interaction UI overlays (transparent
PNG), and a game dialogue box (blurred feathered band + pixel-style text). A
bridge helper renders a first/last-frame transition through the provider and
falls back to a short dissolve offline.
