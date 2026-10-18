# 解说视频流水线（We-Video 思路，worker brief）
参考思路：https://github.com/hongqun/we-video（无许可证，且基于 Remotion，禁止复制代码/引入 Remotion，只借流程）。
Hevi 已有：hevi/layer4_legacy/artmotion 口播(koubo)、motion 模板、sound_design、字幕、本地 TTS/音色库、storyplan、anatomy、v3 资产库/镜头组。先读再复用。
要补（全部 CPU、本地合成，不调付费 API）：
1. 文稿：文章/资料→口播稿（本地模型或规则，分段、口语化、时长估算），可编辑并版本化；能力 explainer.script。
2. 配音确认闸：选音色生成本地 TTS，状态机 script→voice_approved→plan→render，未确认不能进下一步；每步可回退修改，只重算受影响部分。
3. 节奏驱动视觉规划：依据音频词级时间戳（本地对齐，如 whisper.cpp/现有对齐工具）自动排镜：关键词同步高亮、配图按节奏出现、关系图/流程图逐层展开（SVG/PIL 程序化）、主讲人全屏/侧边小窗布局切换、转场淡入/滑动/缩放/擦除；能力 explainer.visual_plan。
4. 预览与渲染：低清快速预览帧 + 最终 MP4（ffmpeg），能力 explainer.render。
5. 端到端：一篇 800 字科普文章→口播稿→本地配音→视觉规划→≥60 秒 mp4，ffprobe 验时长；高亮时间与词时间戳误差<200ms 的测试。
测试：每项真实测试（禁止 mock 渲染/音频结果），全量回归相对基线无新增失败。
CPU-only，不 push/合并/部署，不删 worktree 外文件，/data<5G 停。
报告 audit/wevideo/REPORT.md，末行 `WEVID-FINAL DONE <commit>` 或 `WEVID-FINAL BLOCKED <原因>` 并 commit。
