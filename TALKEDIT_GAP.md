# TALKEDIT_GAP — 口播成片能力查漏补缺 (Gap Analysis Matrix)

| 模块 / 来源项目 | 核心能力点 | 现有hevi状态 / 集成度 | hevi 对应文件路径 / 模块 | 补齐状态 |
| :--- | :--- | :--- | :--- | :--- |
| **1. browser-use / video-use** | 原始素材文件夹清洗：切掉“嗯啊”和静音片段、同句多遍自动挑出最佳条目、可选调色/字幕/音效/关键处讲解动画插帧。 | **部分具备** (hevi 有音视频处理、静音剪切和字幕，但缺乏专门的“嗯啊/重复多次口播自动挑最佳+多角度/讲解动画插帧”一站式自动化清洗流) | `hevi/video/`, `hevi/audio/`, `workflows/` | **已补齐 (`hevi/video/talkedit_clean.py`)** |
| **2. nateherkai / herk-edit-kit** | 剪除冗余停顿、口误挑出供人工/脚本确认、叙事规划、自动字幕、B-roll匹配、音效添加、直出 9:16 画幅；内置丰富动效卡片库。 | **部分具备** (hevi 有切片/卡片库/横竖屏处理，但缺专门的口误检测标注供确认、叙事规划与 9:16 直出集成流) | `hevi/video/` | **已补齐 (`hevi/video/talkedit_herk.py`)** |
| **3. kurbaitaev / ghost-editor** | 自动匹配 B-roll 画面，逐镜头校验与该句语义的匹配度，优先调用用户自有素材，色调匹配主画面；字幕自动避开人脸区域。 | **部分具备** (hevi 有多模态检索和字幕渲染，但缺逐镜头语义匹配校验、自有素材优先与字幕智能避开人脸的高级防遮挡算法) | `hevi/video/`, `hevi/vision/` | **已补齐 (`hevi/video/talkedit_ghost.py`)** |
| **4. huangbai-AI / one-prompt-video-skills** | 一句话输入 → 自动写口播稿 → 数字人/合成声音口播渲染 → 匹配 B-roll → 组装成片 → 自动化质检。 | **部分具备** (hevi 各自具备大模型写作、TTS、视频组装和质检，但缺一体化串联的 One-Prompt 口播成片管线) | `hevi/workflows/`, `hevi/video/` | **已补齐 (`hevi/workflows/talkedit_oneprompt.py`)** |
| **5. Vincentwei1021 / video-talkcraft** | 口播稿 + 音频（TTS或自录） → 动效解说视频，动效逐字卡点，无需露脸；提供免费音视频/图标素材站清单与快捷对接。 | **已有良好基础** (hevi-remotion-talkcraft / talkcraft 模块已存在，但需进一步封装测试并打通命令行) | `hevi-remotion-talkcraft/`, `hevi/video/talkcraft.py` | **已强化验证 (`hevi/video/talkedit_talkcraft.py`)** |

