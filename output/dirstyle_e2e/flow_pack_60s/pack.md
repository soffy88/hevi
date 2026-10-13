# Gemini Omni Flash / Google Flow Prompt Pack

- Art style: `stickman_1a_light`
- Aspect ratio: 9:16
- Target duration: 60s (6 clips)
- Narration language: zh
- Hook window: 2-5s

## Director Proposal

**Title**: heartbeat5
**Core message**: # 长中文通用常识文 — 猫推东西行为的科学解释

## 字数参考：约 420 字

猫为什么总爱把桌上的东西推下去
**Narrative arc**: 5-stage heartbeat (黄金钩子 → 打破常识 → 拉出内幕 → 真相揭秘 → 升华互动)

## Segment Transitions (Continuity Handoff)

| Clip | Opening Frame | Closing Frame | Handoff |
|------|---------------|---------------|---------|
| Clip 00 | white background with a centered stickman standing in a neutral start pose | stickman reaching upward and pushing a cup toward the table edge | cut (opens the video) |
| Clip 01 | stickman reaching upward and pushing a cup toward the table edge | stickman holding up three separated fingers beside a small table | match-cut: previous closing frame == this opening frame |
| Clip 02 | stickman holding up three separated fingers beside a small table | stickman crouching low and pressing one palm flat against the ground | match-cut: previous closing frame == this opening frame |
| Clip 03 | stickman crouching low and pressing one palm flat against the ground | stickman leaning forward with both arms swept out to the sides | match-cut: previous closing frame == this opening frame |
| Clip 04 | stickman leaning forward with both arms swept out to the sides | stickman standing tall with arms raised high above the head | match-cut: previous closing frame == this opening frame |
| Clip 05 | stickman standing tall with arms raised high above the head | stickman crouched beside the table, one arm extended toward the cup | match-cut: previous closing frame == this opening frame |

## Global Continuity Block

- **Character DNA**: One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints.
- **Line weight**: uniform smooth stroke thickness on every line
- **Palette**: crimson red, cobalt blue, amber gold
- **Composition (9:16)**: use foreground/background depth instead of left-right staging; stack motion vertically; reveal downward or upward; keep overlay text in the interface-safe upper/lower band; switch the composition axis to the vertical center line
- **Rhythm**: avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
- **Voice profile**: Voice profile: 中文普通话女声，约 30 岁，温和清亮，中速约 4 字/秒，近讲干声，无混响。
- **Negative constraints**: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, photorealism, 3D humanoid rendering, detailed pupils or realistic eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing

## Clip Prompts

### Clip 00

**Output specification**: ~10 seconds, target 720p, 24 FPS, synchronized audio.

**Global continuity lock (repeated verbatim)**:
- Character DNA: One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints.
- Line weight: uniform smooth stroke thickness on every line
- Palette: crimson red, cobalt blue, amber gold
- Composition (9:16): use foreground/background depth instead of left-right staging; stack motion vertically; reveal downward or upward; keep overlay text in the interface-safe upper/lower band; switch the composition axis to the vertical center line
- Rhythm: avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
- Voice profile: Voice profile: 中文普通话女声，约 30 岁，温和清亮，中速约 4 字/秒，近讲干声，无混响。
- Negative: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, photorealism, 3D humanoid rendering, detailed pupils or realistic eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing

**First frame:** white background with a centered stickman standing in a neutral start pose
**Last frame:** stickman reaching upward and pushing a cup toward the table edge

**Timed visual beats**:
- [0-3s]: stickman stands centered in a wide shot, then raises one arm upward
- [3-7s]: slow push-in to a medium shot as the stickman turns side-on
- [7-10s]: stickman crouches and places a small cup on the table edge, camera holds low

**Audio voiceover (audio-only, no speech bubbles)**: "猫为什么总爱把桌上的，东西推下去，这个行为背后其实有深，刻的进化与心理原因，首先，猫的脚垫非常敏感，上面分布着大量的触觉，感受器，当它们触碰物体时。"

**Compiled generation prompt**:
```
One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints., uniform smooth stroke thickness on every line, crimson red, cobalt blue, amber gold, 9:16: foreground/background depth, stacked motion, vertical reveals, foreground passes, interface-safe overlay space; subject placed on vertical center axis or rule-of-thirds grid, avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
```

**Negative prompt**: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, , 3D humanoid rendering, detailed pupils or eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing


### Clip 01

**Output specification**: ~10 seconds, target 720p, 24 FPS, synchronized audio.

**Global continuity lock (repeated verbatim)**:
- Character DNA: One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints.
- Line weight: uniform smooth stroke thickness on every line
- Palette: crimson red, cobalt blue, amber gold
- Composition (9:16): use foreground/background depth instead of left-right staging; stack motion vertically; reveal downward or upward; keep overlay text in the interface-safe upper/lower band; switch the composition axis to the vertical center line
- Rhythm: avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
- Voice profile: Voice profile: 中文普通话女声，约 30 岁，温和清亮，中速约 4 字/秒，近讲干声，无混响。
- Negative: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, photorealism, 3D humanoid rendering, detailed pupils or realistic eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing

**First frame:** stickman reaching upward and pushing a cup toward the table edge
**Last frame:** stickman holding up three separated fingers beside a small table

**Timed visual beats**:
- [0-3s]: tilt up to a full shot while the stickman straightens and steps back
- [3-7s]: stickman extends an arm and pushes the cup; camera drifts slowly downward
- [7-10s]: pull back to a wide shot as the stickman rocks onto the back foot

**Audio voiceover (audio-only, no speech bubbles)**: "实际上是在用脚垫探测，物体的质地，温度和移动性，轻轻一推，如果物体会滚动或发出，声响，就说明它可能是活物或，值得追踪的目标，这是猫科动物刻在基因。"

**Compiled generation prompt**:
```
One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints., uniform smooth stroke thickness on every line, crimson red, cobalt blue, amber gold, 9:16: foreground/background depth, stacked motion, vertical reveals, foreground passes, interface-safe overlay space; subject placed on vertical center axis or rule-of-thirds grid, avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
```

**Negative prompt**: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, , 3D humanoid rendering, detailed pupils or eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing


### Clip 02

**Output specification**: ~10 seconds, target 720p, 24 FPS, synchronized audio.

**Global continuity lock (repeated verbatim)**:
- Character DNA: One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints.
- Line weight: uniform smooth stroke thickness on every line
- Palette: crimson red, cobalt blue, amber gold
- Composition (9:16): use foreground/background depth instead of left-right staging; stack motion vertically; reveal downward or upward; keep overlay text in the interface-safe upper/lower band; switch the composition axis to the vertical center line
- Rhythm: avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
- Voice profile: Voice profile: 中文普通话女声，约 30 岁，温和清亮，中速约 4 字/秒，近讲干声，无混响。
- Negative: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, photorealism, 3D humanoid rendering, detailed pupils or realistic eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing

**First frame:** stickman holding up three separated fingers beside a small table
**Last frame:** stickman crouching low and pressing one palm flat against the ground

**Timed visual beats**:
- [0-3s]: stickman lifts a hand and unfolds three fingers one at a time; camera eases in
- [3-7s]: cut to a low angle as the stickman paces a few steps toward the frame edge
- [7-10s]: stickman pivots and raises the open hand higher; camera arcs gently sideways

**Audio voiceover (audio-only, no speech bubbles)**: "里的狩猎本能，在野外，小猫需要通过推，抓，拍来学习如何捕捉猎物，其次，高处跌落产生的声音和，运动轨迹，对猫的神经系统是强烈，刺激，物体坠落时的抛物线。"

**Compiled generation prompt**:
```
One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints., uniform smooth stroke thickness on every line, crimson red, cobalt blue, amber gold, 9:16: foreground/background depth, stacked motion, vertical reveals, foreground passes, interface-safe overlay space; subject placed on vertical center axis or rule-of-thirds grid, avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
```

**Negative prompt**: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, , 3D humanoid rendering, detailed pupils or eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing


### Clip 03

**Output specification**: ~10 seconds, target 720p, 24 FPS, synchronized audio.

**Global continuity lock (repeated verbatim)**:
- Character DNA: One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints.
- Line weight: uniform smooth stroke thickness on every line
- Palette: crimson red, cobalt blue, amber gold
- Composition (9:16): use foreground/background depth instead of left-right staging; stack motion vertically; reveal downward or upward; keep overlay text in the interface-safe upper/lower band; switch the composition axis to the vertical center line
- Rhythm: avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
- Voice profile: Voice profile: 中文普通话女声，约 30 岁，温和清亮，中速约 4 字/秒，近讲干声，无混响。
- Negative: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, photorealism, 3D humanoid rendering, detailed pupils or realistic eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing

**First frame:** stickman crouching low and pressing one palm flat against the ground
**Last frame:** stickman leaning forward with both arms swept out to the sides

**Timed visual beats**:
- [0-3s]: stickman sinks into a low crouch and lays one palm on the floor; tilt down
- [3-7s]: slow push-in to a tight medium shot as the stickman leans over the object
- [7-10s]: stickman presses the palm flat and slides it forward; camera settles low

**Audio voiceover (audio-only, no speech bubbles)**: "碰撞声，滚动节奏，都会触发猫大脑中的奖，赏回路，即使没有真正的猎物，这种，模拟狩猎，也能释放多巴胺，让猫感到满足和愉悦，最后，猫咪敏锐地观察到。"

**Compiled generation prompt**:
```
One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints., uniform smooth stroke thickness on every line, crimson red, cobalt blue, amber gold, 9:16: foreground/background depth, stacked motion, vertical reveals, foreground passes, interface-safe overlay space; subject placed on vertical center axis or rule-of-thirds grid, avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
```

**Negative prompt**: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, , 3D humanoid rendering, detailed pupils or eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing


### Clip 04

**Output specification**: ~10 seconds, target 720p, 24 FPS, synchronized audio.

**Global continuity lock (repeated verbatim)**:
- Character DNA: One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints.
- Line weight: uniform smooth stroke thickness on every line
- Palette: crimson red, cobalt blue, amber gold
- Composition (9:16): use foreground/background depth instead of left-right staging; stack motion vertically; reveal downward or upward; keep overlay text in the interface-safe upper/lower band; switch the composition axis to the vertical center line
- Rhythm: avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
- Voice profile: Voice profile: 中文普通话女声，约 30 岁，温和清亮，中速约 4 字/秒，近讲干声，无混响。
- Negative: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, photorealism, 3D humanoid rendering, detailed pupils or realistic eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing

**First frame:** stickman leaning forward with both arms swept out to the sides
**Last frame:** stickman standing tall with arms raised high above the head

**Timed visual beats**:
- [0-3s]: stickman straightens and sweeps both arms outward; camera widens to full shot
- [3-7s]: medium shot as the stickman tilts the head down toward the object
- [7-10s]: stickman steps forward and points at the object; camera dollies in slowly

**Audio voiceover (audio-only, no speech bubbles)**: "只要东西掉到地上，主人就会立刻冲过来，哪怕被责备两句，对独居的猫来说也是极，好的社交互动，在猫的认知里，负面关注也是关注，远比主人无视它要好得，多。"

**Compiled generation prompt**:
```
One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints., uniform smooth stroke thickness on every line, crimson red, cobalt blue, amber gold, 9:16: foreground/background depth, stacked motion, vertical reveals, foreground passes, interface-safe overlay space; subject placed on vertical center axis or rule-of-thirds grid, avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
```

**Negative prompt**: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, , 3D humanoid rendering, detailed pupils or eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing


### Clip 05

**Output specification**: ~10 seconds, target 720p, 24 FPS, synchronized audio.

**Global continuity lock (repeated verbatim)**:
- Character DNA: One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints.
- Line weight: uniform smooth stroke thickness on every line
- Palette: crimson red, cobalt blue, amber gold
- Composition (9:16): use foreground/background depth instead of left-right staging; stack motion vertically; reveal downward or upward; keep overlay text in the interface-safe upper/lower band; switch the composition axis to the vertical center line
- Rhythm: avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
- Voice profile: Voice profile: 中文普通话女声，约 30 岁，温和清亮，中速约 4 字/秒，近讲干声，无混响。
- Negative: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, photorealism, 3D humanoid rendering, detailed pupils or realistic eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing

**First frame:** stickman standing tall with arms raised high above the head
**Last frame:** stickman crouched beside the table, one arm extended toward the cup

**Timed visual beats**:
- [0-3s]: wide shot while the stickman raises both arms high overhead
- [3-7s]: stickman recoils and steps back sharply; camera pulls back with him
- [7-10s]: low shot as the stickman drops an object and flinches; tilt follows downward

**Audio voiceover (audio-only, no speech bubbles)**: "因此，推东西，主人出现，这一因果关系被不断强，化，逐渐变成一种习得性行，为模式，简而言之，猫推东西是狩猎本能，神经刺激与社交需求三，重机制共同驱动的结果。"

**Compiled generation prompt**:
```
One classic black line stickman on white. Its head is a black circular outline surrounding an entirely white empty interior. Its torso is a single black line, with two black line arms joined to the upper torso and two black line legs joined to the bottom. All five body lines remain connected during movement. Draw the entire character with the same smooth, uniform stroke thickness. Arms and legs end directly without separate hand or foot shapes. The head interior stays completely white and blank in every frame. Preserve this exact line drawing throughout: no filled head, facial marks, body silhouette, outlined limbs or detached joints., uniform smooth stroke thickness on every line, crimson red, cobalt blue, amber gold, 9:16: foreground/background depth, stacked motion, vertical reveals, foreground passes, interface-safe overlay space; subject placed on vertical center axis or rule-of-thirds grid, avg 10.0s/clip, one 10s clip = three timed beats [0-3s][3-7s][7-10s]; visual change every 2-3 seconds; never idle
```

**Negative prompt**: gray tint, paper texture, gradients, shadows, lighting, bloom, fog, 3D depth, filled head, facial marks, body silhouette, outlined limbs, detached joints, separate hand or foot shapes, changed proportions, broken line weight, , 3D humanoid rendering, detailed pupils or eyes, extra limbs, malformed anatomy, visible words, letters, numbers, captions, subtitles, interface copy, logos, watermarks, speech bubbles, dialogue text boxes, abstract liquid or shape morphing


## Stitching Guide

1. Generate each clip independently in Google Flow using the standalone prompt above.
2. Name clips in sequence: clip_00.mp4, clip_01.mp4, ..., clip_05.mp4.
3. Check first/last frame continuity at every cut: the ending visual state of clip i must match the opening state of clip i+1.
4. Stitch with ffmpeg concat (no re-encode):
   ffmpeg -f concat -safe 0 -i filelist.txt -c copy output.mp4
   where filelist.txt contains:
     file 'clip_00.mp4'
     file 'clip_01.mp4'
     ...
5. Or use Hevi's video-assemble step to concatenate the clip files in order.
6. Keep audio (voiceover + BGM) continuous across cuts; if using separate audio, crossfade 0.5s at each junction.

## Voice & Music Continuity

- Voiceover language: Chinese (default for Hevi users).
- One frozen narrator voice profile for the whole video (identity/age, accent, timbre, register, resonance, texture, delivery, pace, recording treatment). Do not change voice per clip.
- Voiceover is audio-only: no speech bubbles, no dialogue boxes, no visible text in the generated clips.
- BGM: clip 1 establishes the musical theme; clips 2-N continue the identical BGM seamlessly (same tempo, instrumentation, mood).
- SFX: synchronized crisp SFX on physical character actions.
- Word-count scaling: ~20-25 English words or ~45-60 Chinese characters per 10s clip.

## Optional Post-Production Overlays

(Kept OUT of the generation prompts — add these in post-production only.)

- clip_05: "你的选择是什么？" — interface-safe lower band
