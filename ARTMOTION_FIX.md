# ARTMOTION 返工 r2（审核方 2026-10-12 21:3x CST 独立复核 @c11d4f88 未通过）

## 上轮 r1 已修好（不要回退）
- 时长：4 条 E2E 26.9–32.0s ✓；film_gate 阈值未改、cv2 兜底已删 ✓；record.json 写入 film_gate 全部指标 ✓。
- 静止：审核方 2fps 相邻帧差，平均 15–46，<1 灰阶的静止帧 0%（上轮 90–95%）✓。
- 测试填充语已清除，换成真实中文稿（自注意力 / 水墨写意 / 光伏装机 253→887GW 国家能源局 / 唐宋诗词）✓。
- 风格 id 真正加载 scenes/<id>.js，ghibli/ink/8bit/bauhaus 画面风格一眼可辨 ✓；同语法同风格换稿，文字随输入变化 ✓。
- pytest tests/test_artmotion.py 4 passed，lint=基线 4 项 ✓。

## 阻断（必须修）
1. **风格=上游写死的示范插画，与输入无关**。scenes/*.js 是上游 eras 演示的固定 1920×1080 画（窗、桌、少女端茶杯、猫、齐白石虾、bauhaus 里还有「katze」字样），现在被原样当背景铺在每一条片子下。结果：自注意力、光伏、诗词、银杏四个题目的画面主体都是同一个「少女喝茶」场景，只换了画法；9:16 下镜头只扫到这张横图的竖条，大段是少女黑衣/黑发（task_1/task_3 有一半帧是黑底+金发少女+茶杯）。语法层（柱状图、字、曲线）本身没有任何风格化（光伏柱子是普通蓝柱，字是普通黑体）。要求：
   - 风格要作用在**语法层内容**上（按 references/风格配方/<id>.md 的配方：配色、笔触/像素量化/纸纹、字体与描边、图元画法），而不是贴一张固定示范画；
   - 背景若保留，只能用风格的**纹理/底子**（宣纸、像素格、包豪斯色块），不得出现与稿件无关的人物/猫/虾/「katze」等示范元素；
   - 9:16 必须按竖版构图，不得裁横图。
   - 至少 17_ink、25_ghibli、14_8bit 三种重渲证明。
2. **屏幕文字大面积出框，读不全**。所有片子（尤其 9:16 kinetic）文字行宽超出画面安全区，再叠加镜头推近/横移，绝大多数帧句子左右被切（如「究以墨代色，墨」「斯屡遭贬谪黄州定」「北京的银杏大」）；task_2 标题与 2024 年柱（887 历史新高）多数时间在画外。要求：kinetic/point 文本按画幅宽度自动换行并限制在 safe 区内；相机运动时对文字层做约束（文字层不随相机推出画面，或推拉幅度保证文字框始终在画内）；加自动检查：逐帧（≥2fps）检测文字包围盒是否越出画面，越出即 FAIL。
3. **task_0 屏幕上直接显示 LaTeX 源码**：「K^T/\sqrt{d_k}」「{Softmax}(QK^T)V」（\text 被吃掉一半）。要么真正渲染 TeX（KaTeX 本地或手写排版成 Q·Kᵀ/√d_k），要么稿件 tokens 用可显示的 Unicode；加检查：上屏文本出现反斜杠/^/{} 即 FAIL。
4. **MIT 署名缺失**：TASK 要求保留上游 alchaincyf/huashu-art-motion 的 LICENSE 与版权并在 NOTICE 注明；现在 worktree 里没有该 LICENSE，provenance-ledger 也未登记。补 third_party/huashu-art-motion/LICENSE + NOTICE/ledger 条目。

## 非阻断（顺手修）
- highlight cue 词不在主词时静默不做（日志「荧光笔只刷主词…这一下什么都不做」）；number/highlight cue 那一句旁白完全不上屏（自定义银杏稿第 3 句「类胡萝卜素」从未出现，「2 亿年」挂 9s）。
- task_0 两条折线是随手写的数字（1.2/2.5/4.2…），与注意力内容无对应。
- produce 无时长门禁：自定义 4 句稿出 19.42s 仍 succeeded（只有 e2e 脚本 assert）。若 20s 是产品下限请在 produce 里判。
- audio_path 分支给每句均分时长、逐字均分，属伪对齐，应走 whisper 对齐或明确标注。
- tests 的「adapter 契约」用例 mock 掉了 produce_artmotion，DONE 写成「输入→MP4+record.json」过度表述；DONE 的「风格像素特征」只是取中心色，不能证明风格。
- output/artmotion_e2e/rerun_task_1_verify 未在 DONE 说明。

## 验收
重跑 scripts/artmotion_e2e.py（4 条 + 对照），ffprobe/sha256 写入 DONE；自查 2fps 密抽：无出框文字、无 LaTeX 源码、无示范人物/猫/katze；lint 不多于基线 4 项；commit，不 push。禁止 mock/占位/写死样片。
