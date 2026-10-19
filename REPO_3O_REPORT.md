# 候选开源项目 3O 范式内化与适配评估报告

本报告严格依据 **3O 范式 (HELIOS_3O_SPEC_v3_0)**，对 `~/projects/hevi/REPO_FIT_REPORT.md` 中的 6 个候选开源项目（DigUp、local-deep-research、kokoro、short-video-factory、AI-Youtube-Shorts-Generator、podcastfy）进行工程复用评估。明确区分**“内化为主库原生 3O 元素（oprim/oskill/omodul/obase/oservi）”**与**“仅作外部服务接入或不值得做”**。

---

## 一、 候选开源项目 3O 内化与适配评估总表

| 候选开源项目 | 目标项目 | 可内化的具体能力 | 3O 范式内化方案 (对应 oprim/oskill/omodul/obase/oservi) | 不内化/外接的部分及原因 | 工作量 | 优先级 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. DigUp**<br>`ARahim3/DigUp` | **AII / stratum** | 本地多模态向量检索、EmbeddingGemma 2 文件/图像/代码索引 | • **obase**: 封装 EmbeddingGemma 2 客户端与多模态 embedding 适配器。<br>• **oprim**: `multimodal_embed`, `vector_cosine_search` 原子操作。<br>• **oskill**: `multimodal_index_pipeline`（技能组合）。 | CLI 界面与独立搜索前端外接；不作为独立 monolith 服务打包，保持统一库调用。 | 3人天 | P2 |
| **2. local-deep-research**<br>`LearningCircuit/local-deep-research` | **AII / stratum** | 全自动端到端深度研究网状代理工作流、多搜索引擎集成 | • **obase**: 集成多个本地/联网搜索 API 适配器。<br>• **oskill**: `search_synthesize_loop`、`query_expansion` 纯算法逻辑。<br>• **omodul**: `deep_research_workflow`（业务事务处理）。<br>• **oservi**: `sequential_composer` 编排多步骤代理迭代。 | 复杂的 Web UI 界面不内化，复用核心 Python Agent 代理逻辑。 | 5人天 | P1 |
| **3. kokoro**<br>`hexgrad/kokoro` | **hevi** | 高质量端侧神经 TTS 语音合成、多语言超轻量配音 | • **obase**: Kokoro ONNX/PyTorch 模型运行时的底层内存/设备（CPU/GPU）初始化与音频文件输出适配。<br>• **oprim**: `synthesize_speech_chunk`（单段文本转语音原子操作）。 | 上层大文本切片流式播放调度留给项目服务层，核心推理算法内化为 oprim。 | 2人天 | P1 |
| **4. short-video-factory**<br>`YILS-LIN/short-video-factory` | **Easel** | 营销短视频批量自动剪辑与模版化生成管线 | • **oskill**: `video_subtitle_align`, `template_scene_compose`。<br>• **omodul**: `marketing_video_generation_transaction`。 | 桌面端 Electron/GUI 客户端完全不内化（属项目前端/客户端层，非 3O 范式复用单位）。 | 4人天 | P2 |
| **5. AI-Youtube-Shorts-Generator**<br>`Easel / hevi` | **Easel / hevi** | 长视频高光检测、Whisper 转录、9:16 智能竖屏裁切 | • **oprim**: `whisper_transcribe`, `crop_video_to_portrait`。<br>• **oskill**: `highlight_detection_algorithm`。<br>• **omodul**: `long_to_short_video_workflow`。<br>• 与现有 `hevi-svfactory` 单源收敛合并。 | 冗余的 YouTube 下载爬虫逻辑外接或复用现有 obase 基础设施。 | 3人天 | P1 |
| **6. podcastfy**<br>`souzatharsis/podcastfy` | **hevi / Easel** | 多模态内容转多语种播客音频对话（NotebookLM 替代） | • **oskill**: `dialogue_script_generation`, `multi_speaker_tts_merge`。<br>• **omodul**: `podcast_generation_workflow`。<br>• **oservi**: 编排长文解析、对话大纲生成、双人语音合成。 | 前端 SaaS 界面不内化；底层多语种大模型对话脚本生成逻辑内化。 | 3人天 | P2 |

---

## 二、 各目标项目落地顺序与 3O 内化实施指南

### 1. `hevi` 项目组落地顺序

1. **Kokoro (3) [优先级 P1]**
   - **内化动作**：将模型权重与推理包装为 `obase` 运行时适配器，并在 `oprim` 实现 `synthesize_speech_chunk`。
   - **单源收敛**：替代原有的基础 TTS 实现，确保全局仅有一份高质量端侧语音合成入口。

2. **AI-Youtube-Shorts-Generator (5) [优先级 P1]**
   - **内化动作**：在 `oskill` 实现高光检测与 Whisper 时间戳对齐算法，在 `omodul` 构建 `long_to_short_video_workflow`。
   - **与现有 hevi-svfactory 融合**：遵循 §1.4 单源约束，将重叠的视频切片剪辑逻辑收敛合并，避免多份代码漂移。

3. **Podcastfy (6) [优先级 P2]**
   - **内化动作**：在 `omodul` 封装播客对话生成事务，结合 Kokoro 的 TTS 能力形成完整的 `podcast_generation_workflow`。

### 2. `Easel` 项目组落地顺序

1. **AI-Youtube-Shorts-Generator (5) [优先级 P1]**
   - **内化动作**：作为社媒内容自动化的底层 `omodul` 供 Easel 项目服务层调用。

2. **Short-video-factory (4) [优先级 P2]**
   - **内化动作**：提取其核心营销视频自动排版与模版组合算法为 `oskill`，剥离桌面客户端代码。

### 3. `AII / stratum` 项目组落地顺序

1. **Local-deep-research (2) [优先级 P1]**
   - **内化动作**：将搜索与深度研究代理逻辑沉淀为 `omodul` 与 `oservi`（采用 `sequential_composer` 编排多轮迭代搜索），大幅增强知识系统的网状深度研究能力。

2. **DigUp (1) [优先级 P2]**
   - **内化动作**：将 EmbeddingGemma 2 客户端封装入 `obase`，原子多模态 embedding 沉淀至 `oprim`。

---
REPO3O DONE
