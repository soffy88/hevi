# REPO FIT REPORT - 候选开源项目适配评估报告

本报告评估了6个候选开源项目对目标项目（`hevi`、`Easel`、`AII`/`stratum`）的适配性与集成路线。

## 一、 候选开源项目适配评估总表

| 候选开源项目 | 最适配目标项目 | 补充的具体能力 | 已有重叠 / 已集成情况 | 集成难度 | 优先级 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. DigUp**<br>`ARahim3/DigUp` | **AII / stratum** | 本地多模态向量检索、基于EmbeddingGemma 2的精准文件/图像/代码索引能力 | 基础文本检索已有，但缺少端侧多模态嵌入与统一文件搜索引擎 | 中 | P2 |
| **2. local-deep-research**<br>`LearningCircuit/local-deep-research` | **AII / stratum** | 本地深度研究代理工作流、95% SimpleQA 准确率、多搜索引擎集成 | 知识库已有检索与RAG，缺少全自动端到端深度研究网状推理代理 | 中 | P1 |
| **3. kokoro**<br>`hexgrad/kokoro` | **hevi** | 高质量端侧神经TTS语音合成、多语言超轻量配音生成 | 现有TTS较为基础或依赖外部API，缺少高质量本地端侧合成 | 低 | P1 |
| **4. short-video-factory**<br>`YILS-LIN/short-video-factory` | **Easel** | 一键产品营销与泛内容短视频、AI批量自动剪辑客户端 | 现有hevi/Easel侧有svfactory但偏后端渲染，缺少桌面端一体化自动剪辑工厂能力 | 中 | P2 |
| **5. AI-Youtube-Shorts-Generator**<br>`Anil-matcha/AI-Youtube-Shorts-Generator` | **Easel / hevi** | 长视频切片、LLM高光检测、Whisper转录与9:16自动智能裁切 | 现有`hevi-svfactory`已部分具备视频剪辑能力，但缺少高光检测与自动化短片裁切管线 | 低 | P1 |
| **6. podcastfy**<br>`souzatharsis/podcastfy` | **hevi / Easel** | 多模态内容转多语种播客音频对话（NotebookLM开源替代） | 现有有文转影/文转音，但缺少双人对话式播客生成管线 | 低 | P2 |

---

## 二、 各目标项目建议落地顺序

### 1. `hevi` 项目组落地顺序
1. **Kokoro (3)**：接入本地端侧语音合成，替换/增强基础TTS，满足品牌短片与视频旁白的高质量、低延迟需求。
2. **AI-Youtube-Shorts-Generator (5)**：与现有`hevi-svfactory`融通，引入高光检测、Whisper对齐与自动9:16竖屏裁切能力。
3. **Podcastfy (6)**：为长文/长视频素材增加播客式双人对话音频生成能力。

### 2. `Easel` 项目组落地顺序
1. **AI-Youtube-Shorts-Generator (5)**：增强Easel社媒内容工作流中的长视频转短视频切片自动化能力。
2. **Short-video-factory (4)**：引入批量桌面端一键营销短视频工厂管线。

### 3. `AII / stratum` 项目组落地顺序
1. **Local-deep-research (2)**：引入端到端深度研究代理与多引擎检索，大幅提升个人知识系统的智能研究深度。
2. **DigUp (1)**：增强本地多模态（PDF、图像、音视频、代码）嵌入与端侧快速精准搜寻能力。
