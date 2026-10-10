# 内置 CosyVoice 默认参考音(cosy-ref-v1)

生产调用只传文本时, hevi 客户端(`hevi/audio/cosyvoice_service.py`)会把参考音
解析为 `builtin:zh_default`, 由引擎 `ai_routes._normalize_cosy_script` 映射到本目录。

| 名称 | 文件 | 转录(prompt_text) | 来源 / 许可 |
|---|---|---|---|
| zh_default | zh_default.wav (16 kHz mono s16, 3.48 s) | 希望你以后能够做的比我还好呦。 | FunAudioLLM/CosyVoice `asset/zero_shot_prompt.wav`, Apache-2.0 |

新增内置参考音时: 放 `<name>.wav` + `<name>.txt`(转录), 并同步
`hevi/layer4_legacy/voicepro/oprim_impl/cosy_mode.py::BUILTIN_VOICE_REFS`。
