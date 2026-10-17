# Hevi Live Host — E2E 实测报告

> 全部为真实测量值（CPU 降级，无 GPU）。环境见 engine_config。

## 汇总

- 提问数：3
- 平均首音频延迟：25.379 s（目标 <2.5s，CPU 降级下超出）
- 平均各阶段耗时（秒）：`{'vad': 0.314, 'stt': 13.911, 'llm_first_token': 4.516, 'llm_total': 22.487, 'tts': 6.638}`
- TTS 输出往返 CER（合成→再转写）：0.2649
- 提问合成耗时（Piper）：[1.71, 1.604, 1.381] s
- GPU 可用：False

## 逐轮明细

### 第 1 轮

- 提问文本：`小雅你好,能介绍一下你自己吗?`
- STT 转写：`小雅你好能介绍一下你自己吗`
- 回复：`我好！我叫小雅，简称雅雅，今年23岁，研究生正在读中文语言学。我的直播间名称是“赛博小雅”，这个名字来自于我的 AI 生成的主持人身份和我的中文语言学背景。我喜欢在直播间与观众互动，探讨关于中文语言、文化等主题。我也非常乐意接受观众提问，回答问题 anytime。`
- 句数：5
- 各阶段耗时：{'vad': 0.9015, 'stt': 16.6691, 'llm_first_token': 0.6741, 'llm_total': 22.4796, 'tts': 8.0822}
- 首音频：26.327 s
- 逐句 CER：[0.3333, 0.3214, 0.1489, 0.1071, 0.5]（均值 0.2821）

### 第 2 轮

- 提问文本：`今天天气怎么样,你有什么穿搭建议?`
- STT 转写：`今天天气怎么样你有神魔穿大剑衣?`
- 回复：`(笑声) 今天的天气很不错！白天阳光明媚，下午偶尔会有一点阴影。(拍打自己衣服) 我的神魔穿大剑衣，确实很适合在这样天气里出发冒险！但是，记得我还是一个直播主持人，不太爱上太多冒险事物（捂口)。`
- 句数：4
- 各阶段耗时：{'vad': 0.0266, 'stt': 12.519, 'llm_first_token': 5.9393, 'llm_total': 26.3319, 'tts': 7.0214}
- 首音频：25.506 s
- 逐句 CER：[0.4286, 0.1667, 0.2353, 0.1935]（均值 0.256）

### 第 3 轮

- 提问文本：`可以讲一个关于科技的冷知识吗?`
- STT 转写：`可以讲一个关于科技的冷知识吗?`
- 回复：`嗯，很有趣的一个冷知识是，微波炉里的那不停翻动的磁铁是什么呢？答案是“磁铁”其实并不是真正的磁铁，而是一种特殊的非铁类材料，这些材料在微波炉中会出现这种奇怪的行为。`
- 句数：2
- 各阶段耗时：{'vad': 0.014, 'stt': 12.5454, 'llm_first_token': 6.9348, 'llm_total': 18.6501, 'tts': 4.8101}
- 首音频：24.304 s
- 逐句 CER：[0.3226, 0.1569]（均值 0.2398）

## 引擎配置

```json
{
  "stt": "whisper",
  "llm": "ollama",
  "tts": "piper",
  "whisper_model": "/home/soffy/models/faster-whisper-large-v3-turbo",
  "whisper_device": "cpu",
  "whisper_compute": "int8",
  "ollama_base_url": "http://localhost:11434",
  "ollama_model": "llama3.2:3b",
  "persona": "小雅",
  "max_reply_chars": 120,
  "piper_binary": "/data/soffy/projects/hevi-zero/.venv/bin/piper",
  "piper_model": "/data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx",
  "cosyvoice_base_url": "http://localhost:17600/api/ai/cosyvoice",
  "aigc_label_enabled": true,
  "aigc_label_text": "AI生成"
}
```
