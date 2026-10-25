# Editing sound layer: local SFX cache (NOT in the repo)

Audio files live only in the gitignored local cache:

- `data/material_cache/cinematic_sfx/mixkit/` — 11 clips, manifest
  `mixkit_manifest.json` in the same directory.
- `data/material_cache/cinematic_sfx/soundeffect-lab/` — 8 clips, manifest
  `soundeffect_lab_manifest.json` in the same directory.

Never `git add` the audio files (they are also covered by the repo's
`*.wav` / `*.mp3` ignore rules). The manifests are the record: clip
name, source URL, license note, intended use.

## Placement rule

- Whoosh / sweep / transition clips go ON scene cuts: a short whoosh
  straddling the cut, never under dialogue.
- Ambience clips (rain, crowd, stream, wind, room tone) are low beds
  under a scene, looped if needed, never the feature sound.
- One scene, one bed at most; a whoosh plus a bed may overlap only
  across the cut itself.

## License summaries (see manifests for the full notes)

- Mixkit SFX Free License: free for commercial and personal projects,
  no attribution required, YouTube use allowed. Caveat: the license
  detail page body is JS-gated and was not read in full; third-party
  summaries add: do not resell the raw file, do not register Content
  ID, and some Mixkit clips carry a Restricted (personal/educational)
  license — if a clip's own page shows Restricted, drop it from
  commercial use.
- Soundeffect-lab (Japanese terms, verified line by line): free
  including commercial use, no report / link / attribution required.
  Forbidden: adult or unlawful use; redistribution (including
  sound-effect-led content, sound-effect showcase videos, and use as
  a creation app's default sounds); direct file links; AI training
  data; Content ID / trademark registration. Adaptation is allowed
  but adapted audio still may not be redistributed.
