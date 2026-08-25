---
name: hevi-story
version: "0.1.1"
description: Convert Chinese story copy or ordered images into a hand-drawn diary-comic animation plan — sentence-by-beat storyboard, text→bw→color three-state reveal or page-flip, contain-not-cover framing, silent picture track.
argument-hint: "--text <故事> 或 --images <有序图片>"
allowed-tools: Bash, Read
homepage: https://github.com/helios-plat/hevi
license: MIT
user-invocable: true
---

# /hevi-story

手绘日记漫画技能（内化自 gnipbao/story-to-handdrawn-video）：中文故事/有序图片 →
分句成 beat → 分镜计划（直切三态揭示或卷页翻书）→ 渲染交 hevi-remotion。
核心引擎 `hevi/assembly/story_to_animation_workflow.py`。

## 调用

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.story_cli \
  --text "故事文本" --mode plan [--transition cut|page-flip]
# 或有序图片:
cd "$HEVI_ROOT" && uv run python -m hevi.skills.story_cli \
  --images /abs/01.jpg /abs/02.jpg --mode preview --transition page-flip
```

`--mode`: `plan`（只出计划）/ `preview`（720×960 快验）/ `full`（1080×1440 正式）。
`--transition`: `cut`（文字→黑白→彩色三段从左到右）/ `page-flip`（右下角卷页，保留母版）。

## 执行流程

1. 输入只能二选一：`--text` 或 `--images`；图片按命令行顺序处理，不重排。
2. 文本按中文句号、问号、感叹号、分号及自然叙事转折切成 beats；尽量一句一拍，不为凑时长拆碎短句，也不擅自改写、补充故事事实。
3. 为每个 beat 生成可执行分镜：原文/图片编号、画面动作或构图、字幕、状态与时长、转场。文本未提供的角色外观、地点和动作保持概括，不虚构关键情节。
4. `cut`：同一 beat 依次呈现文字稿、黑白线稿、彩色完成稿；不得把字幕误当画面内容。`page-flip`：将每个 beat 作为完整母版页面，用右下角卷页转入下一页，不做三态揭示。
5. 运行对应 CLI；`plan` 返回计划，`preview/full` 还应完成可渲染的预览/成片检查。若输入或路径无效，先报告明确错误，不猜测替代资源。

## 计划最少包含

- 全局：画布尺寸、纵横比、帧率/时长策略、转场、音频为静音；
- 每 beat：编号、来源句或图片路径、画面/动作、字幕文本及安全区、状态/转场、持续时长；
- 资源约束：图片顺序、原图尺寸与缩放方式、任何无法执行的假设或警告。

## 纪律（渲染契约）

- `contain` 不 `cover`：保持原图比例，允许留白，禁止裁切、拉伸或改变上传构图。
- 字幕置于上安全区，避免遮挡主体；字幕只使用输入文本（必要时仅做标点与排版整理）。
- 默认静音画面轨；配音、音乐和音效属于后期工序，不在本技能中臆造或加入。
- 画面不得因转场覆盖下一 beat 的主体；`page-flip` 保留当前母版内容直到翻页完成。
- 输出必须可追溯到输入：每个 beat 对应原句或图片；缺失信息标为“待定”，不伪造。
