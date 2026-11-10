# S22 许可审计：TTS / 配乐 / 模型

日期：2026-11-10（UTC）
范围：hevi 线上代码里实际可被调用的配音、配乐与生成模型。
性质：工程审计，不是法律意见；许可以各项目仓库 `LICENSE` 与官方发布页为准。

## 结论

- **公测期继续用**，但以下高风险项必须在对外商用前替换或拿到书面授权：
  `edge-tts`、`f5-tts`、`fish-speech`、`indextts`、`bgm-library`（未登记来源的 BGM）。
- 能直接替换的低风险选项：`kokoro`（Apache-2.0）、`chatterbox`（MIT，克隆声音需被克隆人授权）、
  `procedural-bgm`（hevi 自己合成，零第三方素材）、`qwen-tts-maas`（阿里云商用 API，按量付费）。
- `piper` 引擎 MIT，但音色模型逐个不同，必须逐音色登记；NC 音色不得商用。
- 配乐默认走 `procedural_bgm`：自带精确拍点，正好满足 S22“先定整首配乐再按拍点剪”。

## 逐项

| 项目 | 类型 | 许可 | 可商用 | 风险 | 线上位置 | 替换 / 行动 |
|---|---|---|---|---|---|---|
| edge-tts | TTS | Microsoft Edge 朗读接口，无独立商用授权文本 | 未知 | 高 | `hevi/video/presets.py`、`hevi/api/routers/tasks.py`（默认 edge_tts） | 换 `kokoro`/`chatterbox`/`qwen-tts-maas`；公测期继续用 |
| piper | TTS | 引擎 MIT；voice 模型各异（部分 CC BY-NC） | 未知 | 中 | `hevi/audio/piper_tts_service.py` | 只选 MIT/CC-BY 音色并登记来源 |
| kokoro | TTS | Apache-2.0（代码与 82M 模型） | 是 | 低 | `hevi/audio/kokoro_service.py` | 可直接替换 edge-tts |
| chatterbox | TTS | Resemble AI，MIT（以仓库 LICENSE 为准） | 是 | 低 | `hevi/audio/chatterbox_service.py` | 可用；克隆声音需授权 |
| cosyvoice | TTS | 代码 Apache-2.0；权重许可随版本 | 未知 | 中 | `hevi/audio/cosyvoice_service.py` | 锁权重版本并保留 LICENSE |
| f5-tts | TTS | 代码 MIT；权重训练于 Emilia（CC BY-NC 4.0） | 未知 | 高 | `hevi/audio/f5_tts_service.py` | 对外商用前换掉 |
| fish-speech | TTS | 权重 CC BY-NC-SA | 否 | 高 | `hevi/audio/fish_speech_service.py` | 不用于对外商用成片 |
| indextts | TTS | 权重许可随版本，常见为非商用 | 未知 | 高 | `hevi/audio/indextts_service.py` | 未确认前只做内部测试 |
| qwen-tts-maas | TTS | 阿里云百炼商用 API | 是 | 低 | `hevi/audio/qwen_tts_maas.py` | 有预算时替换 edge-tts |
| procedural-bgm | 配乐 | hevi 自己用 numpy 合成 | 是 | 低 | `hevi/audio/procedural_bgm.py` | 默认配乐优先用它 |
| bgm-library | 配乐 | `assets/audio/bgm` 来源未逐条登记 | 未知 | 高 | `hevi/audio/bgm_library.py` | 入库前登记来源与许可 |
| sdxl | 图像模型 | CreativeML OpenRAIL-M | 是 | 低 | `hevi/image/*` sdxl worker | 保留使用限制说明 |
| sd-turbo | 图像模型 | Stability AI Community License | 是 | 中 | ai_drama 离线关键帧 | 超过营收阈值需企业授权 |
| wan-2.7 | 视频模型 | 阿里 Wan 许可（以发布页为准） | 未知 | 中 | `hevi/cost/pricing_table.py` | 对外商用前锁许可版本 |
| h3-local | 视频模型 | 本地 ComfyUI H3，权重许可随来源 | 未知 | 中 | `hevi/capabilities/fasth3_local.py` | 登记权重来源 |

## 线上默认值与风险

- 视频预设与任务接口默认 `audio_provider="edge_tts"`，这是当前最大的未确认商用项。
- 知识讲解/口播的配乐优先 `procedural_bgm`，无第三方素材风险；一旦运营往
  `assets/audio/bgm/` 放歌，就必须走“入库登记”。
- 生成模型（wan / h3 / sd-turbo）的权重许可需要随部署版本锁定；本审计只记录，
  不替法务做结论。

机器可读版本：`GET /api/studio/craft/license-audit`。
