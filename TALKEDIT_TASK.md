# TALKEDIT_TASK — 口播成片能力查漏补缺

目标：让 hevi 具备以下 5 个 GitHub 项目的完整能力。先审计 hevi 现有代码/已集成模块，逐项对照，缺什么补什么（可直接参考/集成上游仓库，注意许可证）。

1. browser-use/video-use：原始素材文件夹 → 剪掉"嗯啊"和静音、同句多遍自动挑最佳；可选调色、字幕、音效、关键处插讲解动画。
2. nateherkai/herk-edit-kit：剪停顿、口误挑出供人工确认、叙事规划、字幕、B-roll、音效、直出 9:16；动效卡片库（上游 406 张）。
3. kurbaitaev/ghost-editor：自动配 B-roll，逐镜头校验与该句语义匹配，优先用户自有素材，色调匹配主画面；字幕自动避开人脸。
4. huangbai-AI/one-prompt-video-skills：一句话→写稿→数字人（用户照片+声音）口播→B-roll→合成→质检（即梦积分）。
5. Vincentwei1021/video-talkcraft：口播稿+音频（TTS或自录）→动效解说视频，动效逐字卡点，无需露脸；免费素材站清单。

交付：
- TALKEDIT_GAP.md：5×能力点矩阵（已有/部分/缺失 + 对应 hevi 文件路径）。
- 补齐实现 + 测试，用一段样例口播跑通端到端，产出样片。
- TALKEDIT_DONE.md：做了什么、怎么用、样片路径、剩余限制。
卡住超过两轮就写进 TALKEDIT_DONE.md 说明阻塞点后停止。
