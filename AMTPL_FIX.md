# AMTPL_FIX：独立核验不通过（R3 → R4）

- 核验时间：2026-10-14 CST
- 核验对象：`feat/aimotion-templates` @ 1ac1d8a0（DONE AMTPL-R3）
- 证据：Hark 项目工作区 `audit/amtpl/verify_r3/`；主机上的副本在 `/data/tmp/hark_v3/r3/`，其中 `probe.py` 和 `probe.json` 是独立探针及其结果（在原型层 hook fillText，每 0.25 s 记录实际字号和包围盒），`adv_timeline_probe.json` 是对抗 spec，`out/` 是 16 支重渲的 mp4
- 方法：8 个 spec 分别渲 9:16 和 16:9；6 帧抽帧；用 DOM 和 canvas 实测

## 已核实为真（不用返工）
- 16 个组合：文字叠压 0 处，超出画布 0 处，行首和行尾禁则标点 0 处
- timeline 正文（desc）在两个样例 spec 里的折行接缝都落在词边界上，R2 列出的 帧/间、管/线、零/幻觉、短/视频、行首「，」都已消失
- 9:16 主文字：morph_ui 卡片标题 44px，layer_build 层标题 44px，timeline 正文 32px、标题 ≥44px
- ffprobe：16 支都是 h264、yuv420p、30fps、300 帧、10.000 s
- pytest tests/motion_templates：71 项。其中 1 项 determinism 因 /tmp 临时目录消失失败，属于环境问题，单独重跑通过
- 3O lint：失败 4 项，等于基线

## 必须修复
### H1 中文分词依赖写死的样例词表，标题仍然逐字断（阻断）
**实测**：渲染用的 Chromium 151 headless 里，`Intl.Segmenter('zh',{granularity:'word'})` 基本按单字切，例如「联合|建|模」「物理|对|齐」「管|线|标准|化」。`timeline_explainer.html` 里的 `COMPOUND_WORDS` 写死的正是 R2 的金标词（帧间、管线、零幻觉、短视频……），desc 能断对全靠它和 spec 里手写的 `desc_tokens`，这是对样例过拟合。

**出错的实际折行**：
- 16:9 timeline_ai_video_evolution，标题：「扩散变换器跨模态联合**建 / 模**」「端到端音画同步与物理**对 / 齐**」
- 16:9 timeline_hevi_milestones，标题：「领域模块解耦与管线**标准 / 化**」（下一行只有一个字）
- 对抗 spec（新文案，不给 tokens）：9:16「…大型活动散场**客 / 流**…」，16:9「…识别**机动 / 车**…」

**修法**：
- 删掉模板里写死的 `COMPOUND_WORDS`。分词改为在 Python 侧完成：render.py 在 `initTemplate` 之前，用真正的中文分词器（例如 jieba，加进 pyproject 依赖，离线、确定性）给 spec 里**所有**会折行的 CJK 字段（title_zh、desc_zh、morph/layer/kinetic 里会换行的字段）生成 `*_tokens` 注入 spec。spec 里已经手写的 tokens 优先。模板只负责按 tokens 换行，tokens 缺失时才回退到 Segmenter
- 加孤字规则：最后一行不能只有 1 个 CJK 字。遇到时把上一行末尾的一个词挪下来
- 测试：
  1. 对所有 timeline spec，在 9:16、16:9、1:1 下检查 title_zh 和 desc_zh 的实际折行，断言接缝不落在 jieba 词中间，且没有单字孤行
  2. 新增一个**不含任何 tokens、文案与样例无关**的 timeline fixture spec（可以用 `/data/tmp/hark_v3/r3/adv_timeline_probe.json` 的文案），断言同样成立，例如「客流」「机动车」不被切开
  3. 先对当前代码跑出 FAIL，再修到 PASS

### H2 竖屏还有低于下限的文字（次要）
9:16 实测：
- kinetic 右上角显示 spec.title（如「Hevi 动效节拍引擎」「代码律动 // 纯函数动效」），只有 24px。这是标题，要求 ≥28px
- kinetic 歌词上方的英文标签 15px
- timeline 英文副标题 18px，PHASE 标签 20px，顶部角标 16px

**修法**：9:16 下凡是显示 spec 标题的文字都 ≥28px；所有辅助、英文、角标文字 ≥24px。把这条写进 test_text_safe_area：9:16 的所有可见文字 ≥24px，含 CJK 的标题和正文 ≥28px。

### H3 报告失实（必须纠正）
AMTPL_DONE.md 写的是「3O_V3_LINT=PASS」，实测是 FAIL，失败 4 项，与基线相同。验收报告要贴真实输出，不要改写结论。

### 低优先级（顺手修）
- morph_ui 9:16 的光标图形压住了卡片标题「引擎」和大数字「18」：光标的停留位置要避开文字包围盒
- timeline 16:9 卡片下方约 1/4 画面是空的

## 验收（写进 AMTPL_DONE.md，附真实输出）
- 重渲全部 8 个 spec × 9:16 / 16:9，再加对抗 fixture 的 9:16 / 16:9。每支给出 ffprobe、sha256，以及 6 帧 contact sheet
- 每个模板 × 画幅给出：标题和正文的实际折行文本，以及最小字号
- 新测试先 FAIL 后 PASS 的输出
- pytest 总条数（PATH 要包含 /home/soffy/.local/bin）
- lint_after 的原始结论行，失败数不能多于 4
- 不要提交 mp4、png 和日志
- 最后一行写 `DONE AMTPL-R4`

## 安全规则
- 只改本 worktree，不删 worktree 外任何文件
- 不清理磁盘；/data 剩余空间低于 5G 时，写 DISK_FULL_NOTE.md 后停止
- 内存紧张，只能单进程渲染
- 所有 python 都设 `PYTHONPATH=/data/soffy/projects/hevi-amtpl`
- 不 push，不调用付费 API
