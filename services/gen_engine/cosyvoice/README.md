"""Vendored 代码来源说明。

本目录 `cosyvoice/` 与 `third_party/Matcha-TTS/` 来自
`github.com/abus-aikorea/voice-pro`(LGPL)的 re-vendor:

- `cosyvoice/` 追踪上游 `FunAudioLLM/CosyVoice` main(voice-pro 2026-07 重供,
  commit 074ca6d), 含两个对 transformers 5.13 的行为补丁
  (`cosyvoice/llm/llm.py`):
  1. `Qwen2Encoder` `from_pretrained` 强制 `dtype=torch.float32`
     (保持 transformers 4.51 行为);
  2. 解码用全长 attention mask。
  不打这两个补丁时 CosyVoice2/3 会静默合成错误内容。
- `third_party/Matcha-TTS/` 为上游子模块 pin, 与上游字节一致。

升级方式: 从 voice-pro 整目录重新拷贝(该目录无本地补丁)。
"""
