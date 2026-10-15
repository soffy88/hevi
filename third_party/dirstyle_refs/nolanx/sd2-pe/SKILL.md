---
name: sd2-pe
description: Use for Seedance 2.0 video generation, image-to-video, video-to-video extension, ordered multimodal @video/@image reference prompting, prompt review, continuity enforcement, and engineered 15-second video prompts.
tags:
  - seedance
  - prompt-engineering
  - multimodal
  - video-to-video
  - image-to-video
agents:
  allow:
    - planner
    - script_writer
    - image_designer
    - image_edit_agent
    - video_designer
    - flf_video_designer
---
# Seedance 2.0 Prompt Engineering

Use this skill whenever the workflow sends images or videos into Seedance-style generation.

## Ordered Reference Binding
- Input video URLs are ordered from top to bottom as @video 1, @video 2, @video 3.
- Input image URLs are ordered from top to bottom as @image 1, @image 2, @image 3, etc.
- Prompt text must reference those labels exactly. Do not invent labels or reorder references.
- Raw asset IDs are not enough. Map every important asset to @video N or @image N plus a semantic name.

## V2V Extension Rule
- If @video 1 is a previous tail or continuation source, explicitly write that the new video must extend @video 1.
- Do not repeat @video 1. Do not restart the action. Do not use it as style-only reference.
- Continue final frame state, story state, camera motion, action momentum, eyeline, blocking, lighting, ambience, and sound carry.
- Then advance the next script beat.

## Prompt Structure
1. Global asset/reference lock.
2. 15-second time-sliced storyboard.
3. Per-slice action, camera, performance, dialogue, and sound.
4. Continuity instruction.
5. Quality/style/negative constraints.

## Review Fallback
- Before generation, check missing asset mapping, missing continuity instruction, contradictory camera moves, weak action timing, and absent quality constraints.
- If any are weak, strengthen them in the generated prompt instead of silently passing vague prose downstream.
