# SVFACTORY-R1：吸收 YILS-LIN/short-video-factory（AGPL-3.0，Electron 桌面端）可迁移能力
来源：https://github.com/YILS-LIN/short-video-factory （git clone 走 ghfast.top 到 /data/soffy/refs/short-video-factory，只读参考）。
AGPL：只读思路，clean-room 重写，不复制源码/UI/素材到 Hevi。产品定位：Hevi = 2–6 岁幼儿教育动画短片，必须过 kids_gate（audit/kids/KIDS_ANIME_DIRECTION.md 规则）。

## 第一步：差距分析（写 audit/svfactory/GAP.md）
读它 src/electron 的流程：提示词→文案（OpenAI 兼容）→EdgeTTS→按文案时长从分镜素材文件夹自动混剪→字幕特效→批量预设持续合成。逐项对照 Hevi 已有能力（zerolines、talkcraft、sfxbad、xfadepack、shotspec、publishkit、capabilities registry），只列 Hevi 真缺的。

## 第二步：只实现缺口（预期重点，按 GAP 结论增删）
1. 批量预设生产：一个 preset（主题列表/风格/时长/画幅/音色/字幕样式）→ 队列持续出片，单进程 CPU 串行，断点续跑，每片独立 manifest + kids_gate 结果；API `POST /api/batch` + 状态查询。
2. 素材文件夹自动混剪：给一个本地素材目录（视频/图片），按旁白分句时长自动选段、裁 9:16/16:9、去重、避免同段重复，确定性 seed。
3. 字幕样式预设（幼儿大字、描边、逐字高亮），与现有字幕/text-overlap 门共用。
TTS 用现有 CosyVoice/本地方案；EdgeTTS 只作可选、默认关闭（不能成为上线依赖）。
全部注册到 capabilities（audit/CAPABILITY_CONTRACT.md），任何产品线可调用。

## 验收（工人自测，巡检会独立重做）
- 批量 preset 3 个主题真实出 3 支 1080p 片（至少 1 支 9:16），每支 ffprobe、抽帧非黑、有声、字幕不溢出、kids_gate pass；中途 kill 后续跑不重做已完成片。
- 混剪同 seed 两次 SHA 一致；换 seed 选段不同。
- 新增 pytest 全过；全量回归无新增失败；3O lint ≤4。
- 报告 audit/svfactory/REPORT.md：命令、数字、样片路径；最后一行 `DONE SVFACTORY-R1`。

## 规则
worktree /data/soffy/projects/hevi-svfactory，分支 feat/svfactory（基于当前 closure 远端 HEAD）；只 git add 自己的文件；不 push（巡检核验后才 push）。CPU-only，单进程渲染；禁止付费 API；禁止 mock 伪造验收；不删 worktree 外任何文件，不清理磁盘，/data<5G 写 DISK_FULL_NOTE.md 停止；不改主 checkout /data/soffy/projects/hevi；不碰生产容器。
