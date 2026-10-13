# ARTMOTION 返工 r5（审核方 2026-10-13 14:1x CST 独立复核 @e69a88d0 不通过）

复核方法：ffprobe/sha256（4 条与 DONE 一致，渲染时间 18:24–18:31 UTC，晚于 6a46ed5a，确为当前代码产物）；每条均匀抽 12 帧 4x3 拼图亲眼看；volumedetect；pytest；3O lint；读 scenes_style/*_texture.js 源码。

## 本轮已确认修好（不要回退）
- 时长 26.9–32.0s、分辨率、aac 音轨（mean -18.2~-19.8 dB）✓
- 少女/猫/虾的绘制调用已注释，画面中不再出现人物/动物 ✓
- MIT：third_party/huashu-art-motion/LICENSE 与上游 raw LICENSE 逐字一致 + NOTICE.md ✓（docs/compliance 下仍无 provenance 登记，顺手补一条）
- pytest tests/test_artmotion.py 4 passed；lint 仅基线 4 项 ✓
- texture 文件从零写，只保留纹理底子（宣纸纤维、水彩晕染、像素格纹、色块），删除一切 bg() 示范底版、家具、窗、窗帘、植物、girl*/cat*/shrimp 函数 ✓

## 阻断（必须修）
1. **"纹理模式"只是删了人物，示范房间整套还在画**。scenes_style/*_texture.js 是上游 demo 文件原样复制后注释掉 girl/cat 调用：
   - 25_ghibli_texture.js 第 225–240 行仍画窗洞+云+树+草、窗框中梃、curtain×2、tablecloth、daisies、komorebi，bg() 底版是整间屋（窗、窗帘、木架/桌腿）。task_0 自注意力每一帧背景都是这间屋，右侧木柜/桌面大块棕色贴在公式和折线上。
   - 14_8bit_texture.js 仍有 girlLayers/catLayers/plant 函数和带窗、挂画、梯子/椅子、桌子的像素房间底版；task_2 光伏每帧背景是这间像素屋，右边还有深青色+号竖条。
   - 17_ink_texture.js：task_1/task_3 约一半帧是**整屏黑底+白/金色碎弧线**（这是原示范里少女黑发/猫的笔触纹样被放大），另一半是桌面/毛笔/台案的粗墨线。与水墨写意、唐宋诗词毫无关系，且黑底上黑字不可读。
   要求：texture 文件**从零写**，只保留纸纹/水彩晕染/像素网格/色块这类全屏均匀底纹；删除（不是注释）一切 bg() 示范底版、家具、窗、窗帘、植物、girl*/cat*/shrimp 函数；加检查：texture 文件里 grep 不到 girl|cat|shrimp|curtain|window|WIN|tablecloth|daisies|plant|mug|desk|bg\(\)，否则 FAIL。
2. **语法层仍未风格化**。光伏柱子是普通蓝柱→灰柱，Roboto/黑体字，8bit 无像素化；ghibli 公式是普通衬线体；ink 文字是普通宋/黑体。按 references/风格配方/<id>.md 让柱/线/字吃风格（像素量化+像素字体、墨笔描边+毛笔/楷体、赛璐璐描边配色）。
3. **文字出框依旧（r4 B2 未修）**。12 帧里多数被左右切掉：task_0「得到查询向量…」「最后利用归一化函数计算注意力」「点积，衡」；task_1「中国传统水墨画讲究以墨代色，墨」「画师落笔如行云」「虚实相生之间，展」；task_3「苏轼屡遭贬谪黄州定」「文脉千载未曾断绝,」「1,000 载」「1,00」；task_2 标题只剩「容量 (2020-2024)」、2023/2024 柱(609/887)多数帧在画外。DONE 说"TY.fit 已有"但相机推拉/横移仍把文字推出画面。要求：文字层不随相机运动（或运动幅度保证文本框始终在 safe 区 5% 内）；**实现并提交逐帧（≥2fps）文本包围盒越界检查**并接入 produce/film_gate，越界即红灯；DONE 里贴该检查对 4 条的输出。
4. **LaTeX 源码仍上屏（r4 B3 未修）**。task_0 屏上显示「QK^T/√d_k」「ftmax(QK^T)V」：sanitize_latex 只处理反斜杠命令和花括号，没处理 ^ 与 _。要求 ^T→ᵀ、_k→ₖ（或真排版），并加检查：上屏文本含 \ ^ _ { } 即 FAIL（测试覆盖 "QK^T/\sqrt{d_k}" 与 "\text{Softmax}(QK^T)V"）。

## 非阻断
- r4 非阻断项（highlight/number cue 旁白不上屏、task_0 折线示意数据、produce 无时长门禁、audio 均分伪对齐、adapter 测试 mock 过度表述）DONE 只写"已记录"，未修。
- output/artmotion_e2e 下 *_v2、rerun_task_1_verify、test_render 未在 DONE 说明（不要删，说明即可）。

## 验收
重跑 scripts/artmotion_e2e.py 4 条；自己 2fps 抽帧看：无房间/家具/窗/黑发纹样、无出框、无 ^ _ \ { }；新检查脚本输出写入 DONE；ffprobe/sha256 写入 DONE；lint ≤ 基线 4；commit，不 push。禁止 mock/占位/写死样片。

---
（以下为 r4 复核原文，保留备查）

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
