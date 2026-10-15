---
name: lighting-continuity-design
description: Use for lighting mood design, contrast control, shot-to-shot lighting continuity, and visual tone consistency across sequences.
tags:
  - lighting
  - continuity
  - ratio
  - contrast
  - mood
agents:
  allow:
    - planner
    - script_writer
    - image_designer
    - image_edit_agent
    - video_designer
    - flf_video_designer
---
# Lighting Continuity Design

Use this skill for mood + continuity, not just pretty light adjectives.

## Source Basis
- StudioBinder lighting ratio guide.

## Ratio Heuristics
- 1:1 to 2:1: soft, open, calm, commercial, flattering
- 4:1: dramatic but readable
- 8:1 and above: severe, moody, foreboding, oppressive

## Rules
- Keep lighting ratio logic stable across adjacent shots unless the story beat intentionally changes mood.
- Track key direction, fill behavior, rim presence, and practical light motivation.
- Match material response to the chosen contrast level.
- If the scene is ash-grey and backlit, do not suddenly make it glossy daylight-clean in the next shot.

## Prompting Heuristics
- describe light direction
- describe shadow density
- describe practical motivation
- describe atmospheric medium: haze, smoke, dust, rain, mist

## Continuity Failures To Block
- unexplained switch from hard backlight to flat frontal light
- palette shift without narrative cause
- inconsistent eye-light or silhouette logic for the same sequence
