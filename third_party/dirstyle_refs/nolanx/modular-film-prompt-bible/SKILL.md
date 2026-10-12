---
name: modular-film-prompt-bible
description: Use for high-control film and video prompting that must combine a stable world bible, reference placeholders, real-photography fidelity, sound policy, genre fusion, and shot-level execution into one reusable creative template.
tags:
  - film-prompt
  - modular-template
  - visual-bible
  - shot-execution
  - reference-lock
  - sound-design
aliases:
  - cinematic-prompt-bible
  - 影视创作模板
  - 电影提示词圣经
agents:
  allow:
    - planner
    - script_writer
    - image_designer
    - image_edit_agent
    - video_designer
    - flf_video_designer
---
# Modular Film Prompt Bible

Use this skill when the user wants a film-style creation template rather than a loose prompt paragraph.

This skill turns a concept into two layers:
- a stable creative bible that stays locked
- executable shot or frame instructions that only describe the delta for the current beat

## What This Skill Solves
- Prevents film prompts from collapsing into generic adjective piles.
- Separates identity, world, medium, sound, and shot execution into distinct modules.
- Supports reference placeholders such as `{{Portrait 1}}`, `{{Scene 1}}`, `@image 1`, or `@video 1`.
- Works for both still-image key art and shot-by-shot video prompting.

## Core Principle
Write prompts in this order:
1. identity lock
2. world and genre lock
3. medium and realism lock
4. sound policy
5. per-shot execution
6. continuity carryover

Do not invert this order. If the camera language appears before the world is stable, the output tends to drift.

## Layer 1: Creative Bible
Lock the parts that should not randomly mutate.

### Identity Lock
- Map each recurring subject to a stable reference token.
- Lock silhouette, age cues, species or mechanical type, facial system, costume logic, prop package, and material response.
- For non-human or mechanical faces, define expression states explicitly instead of writing vague emotion words.
- If a recurring prop exists, lock carried side, scale, outline, glow behavior, and wear state.

### World And Genre Lock
- Name the world as a specific place after a specific event, not as a mood cloud.
- If the brief fuses genres, define the blend operationally.
- Example: atompunk + western means period-tailored silhouettes, retro-futurist industrial forms, aged metal, analog control surfaces, and dusty frontier staging.
- State what must not modernize.

### Medium And Realism Lock
- Choose one image logic: live-action realism, large-format film, 35mm genre cinema, retro stock, premium CG with film behavior, or another single coherent medium.
- If realism matters, explicitly block game-like CG, plastic surfaces, floating props, and weightless movement.
- Describe how metal, leather, skin, smoke, dust, rain, LEDs, and water respond to light.
- Tie grain, halation, contrast, bloom, and motion blur to dramatic intent rather than using them as decoration.

### Sound Policy
- Decide whether the piece uses sync sound only, sparse ambience, or score-led treatment.
- If the request wants realism, prefer no BGM and retain only production sound, Foley, and environment.
- Every sound note should come from a visible or inferable source.

## Layer 2: Execution Prompt
Once the bible is locked, describe the current frame or shot.

### Still Image Mode
Use this section order:
- core mood and fidelity
- character or subject
- environment
- composition
- color and lighting
- style finish
- micro-action

### Video Shot Mode
For each shot or time slice, define:
- shot objective
- shot size and angle
- composition
- camera position and movement
- subject movement
- expression or display-state behavior
- environment interaction
- sound in shot
- continuity from previous shot

Do not restate the entire world bible on every shot. Reuse the lock and only describe what changes.

## Chinese-Friendly Section Map
When the user works in Chinese, these headings map cleanly to this skill:
- `基础设定`: identity, world, props, genre fusion
- `核心氛围与画质`: realism level, capture medium, texture, grain, contrast
- `声音`: sync sound, ambience, Foley, BGM policy
- `人物`: subject lock and performance traits
- `场景氛围`: environment state, weather, aftermath, practical light sources
- `构图`: framing, dominant screen position, foreground-midground-background logic
- `色彩与光影`: palette, key direction, shadow density, practical motivation
- `画面风格`: film era, lens feel, realism guardrails
- `动态描述`: body behavior, gaze, servo motion, cloth or smoke response
- `景别 / 运镜 / 画面内容`: shot execution fields for video

## Performance Rules
- A body move must mean something: advance, recoil, stalk, circle, freeze, brace, collapse, hesitate.
- For mechanical characters, translate emotion into readable posture, timing, and interface-state changes.
- If the face is LED, masked, or stylized, define emotional beats as discrete transitions, not fuzzy mood prose.

## Camera Rules
- Choose one dominant camera intention per shot.
- Separate subject motion from camera motion.
- If the world is oppressive, use framing and depth to trap the subject.
- If the beat is revelatory, use push-in, tightening composition, or exposure shift with intent.
- If the beat is absurd, eerie, or tragicomic, let performance and framing carry it before adding style embellishment.

## Continuity Rules
- Carry forward damage state, dirt, weather, costume wear, prop orientation, and action phase.
- If a shot continues a previous moment, define what is inherited before defining what changes.
- If an interface state changes, note the exact trigger and resulting state.

## Guardrails
- Do not write "cinematic" unless you convert it into lens, light, composition, texture, and motion decisions.
- Do not mix incompatible era signals without explaining the fusion logic.
- Do not overload a shot with multiple contradictory camera verbs.
- Do not let sound notes drift away from visible action.
- Do not flatten a strong concept into generic beauty-shot language.

## Compact Output Pattern
When building a reusable film prompt package, prefer this structure:

- `Core premise:`
- `Recurring references:`
- `World and genre lock:`
- `Sound policy:`
- `Look bible:`
- `Shot 1: objective / framing / camera / action / sound / continuity`
- `Shot 2: objective / framing / camera / action / sound / continuity`

## Best Fit Cases
- a screenshot-derived film prompt that mixes world bible and shot list
- robot, creature, armor, or stylized face systems that need explicit expression states
- genre-fusion work such as atompunk western, diesel noir, wuxia steampunk, retro-future war drama
- prompts that must feel like a director treatment rather than a casual text description
