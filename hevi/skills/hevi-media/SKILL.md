---
name: hevi-media
version: "0.1.0"
description: Media OS for hevi — resolve any media need (bgm, sfx, image, icon, logo, voice, grade, lut, video) into a frozen local file + ledger record; reuse across projects. One verb: resolve.
argument-hint: "resolve --type <t> --intent \"<描述>\""
allowed-tools: Bash, Read
homepage: https://github.com/helios-plat/hevi
license: MIT
user-invocable: true
---

# /hevi-media

媒体台账技能(内化自 HyperFrames media-use):任何媒体需求 → 一个 `resolve` 动词 →
冻结文件 + 台账记录;台账复用优先,供应链 = 本地库 → 素材检索 → 生成。核心引擎在
`hevi/sourcing/media_use.py`。

## 前置

`HEVI_ROOT` 指向 hevi 仓库根(见 hevi-watch)。

## 调用

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.media_cli resolve \
  --type bgm --intent "温暖背景钢琴" [--ledger <path>]
```

`--type`: bgm / sfx / image / icon / logo / voice / grade / lut / video。

## 真实 provider 链

CLI 缺省空链(为可测);agent 环境按需求组装 providers 后调用
`hevi.sourcing.media_use.resolve_media`:

| kind | hevi 现有零件 |
|---|---|
| local | `hevi.audio_library`(BGM/SFX 库)|
| stock | `hevi.sourcing.stock_search` / `browser_broll`(Pexels 等)|
| generate | edge-tts(voice)/ TTS 音乐 / 图生成 |
| grade / lut | `hevi.motion.color_grade`(预设 / .cube 校验)|

台账 JSON 落盘后 `--ledger` 可复用(同一 intent 先命中 reuse)。

## 纪律

- resolve 永远返回**冻结本地文件路径 + 台账记录**,不返回搜索结果 URL 噪音。
- 找不到 → 明确报错,不假装成功;由 agent 判断换 intent 或换 provider。
