---
name: hevi-story
version: "0.1.0"
description: Convert Chinese story copy or ordered images into a hand-drawn diary-comic animation plan — sentence-by-beat storyboard, text→bw→color three-state reveal or page-flip, contain-not-cover framing, silent picture track.
argument-hint: "--text <故事> 或 --images <有序图片>"
allowed-tools: Bash, Read
homepage: https://github.com/helios-plat/hevi
license: MIT
user-invocable: true
---

# /hevi-story

手绘日记漫画技能(内化自 gnipbao/story-to-handdrawn-video):中文故事/有序图片 →
分句成 beat → 分镜计划(直切三态揭示 或 卷页翻书)→ 渲染交 hevi-remotion。
核心引擎 `hevi/assembly/story_to_animation_workflow.py`。

## 调用

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.story_cli \
  --text "故事文本" --mode plan [--transition cut|page-flip]
# 或有序图片:
uv run python -m hevi.skills.story_cli \
  --images /abs/01.jpg /abs/02.jpg --mode preview --transition page-flip
```

`--mode`: plan(只出计划)/ preview(720×960 快验)/ full(1080×1440 正式)。
`--transition`: cut(文字→黑白→彩色 三段从左到右)/ page-flip(右下角卷页,保留母版)。

## 纪律(渲染契约)

- contain 不 cover;字幕上安全区;默认静音画面轨(配音/音乐是后期工序)。
- 文本输入保持一句一拍;长句只在自然叙事转折处分。
- 图片输入保留上传顺序与构图,不裁切。
