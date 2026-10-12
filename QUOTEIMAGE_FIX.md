# QUOTEIMAGE 第三轮返工（2026-10-12 00:20 UTC 独立核验未通过）
核验对象：HEAD 1d0f6a3d，output/quoteimage_e2e 8 组成图（sha256 与 DONE 一致，pytest 7/7，lint 仅基线 4 项）。逐张亲眼看图后结论：第二轮 FIX 中 vid_0 的黑条/头像碎片已修好，但仍有下列硬伤，DONE 写"无未解决问题"不属实。

## 必须修复
1. **vid_1_native/01_quote_image.jpg 人物碎片重复**：底部 3 条 strip 仍是整幅画面的底部切片，左侧主持人的白 T 恤领口/西装被切成 3 段重复叠放（y≈800-948），右下还有一个橙色小色块残影。FIX 第 2 条早已要求"每条 strip 只截取字幕带本身"。要求：strip 只取字幕带区域（检测出的 band 上下各留少量余量），非字幕区域不得带入人物/图形碎片；做不到干净输出就把这条标 failed 并在 DONE 说明，不得 succeeded。
2. **vid_2_native 重复字幕**："LET'S SEE, LET'S FIND" 连续出现两次（时间点 6.48 与 7.02 取到同一句字幕）。subtitle_duplicate 门禁却 PASS（value 184.76）——现在的实现只是把底部区域等分 4 份做像素差，根本不是按 strip 比较字幕内容。要求：按实际 strip 边界逐对比较字幕带（或用 ASR/OCR 文本去重），相邻取样落在同一句字幕时换下一句时间点；门禁 value 要报真实的最小差异而不是 255-diff 的"相似度"；加一个"两条相同字幕"的真实图片 fixture，验证门禁 FAIL。
3. **vid_3_script/quote_script.jpg 字号不可读且不一致**：720 宽画面上两行文字约 12px，且第一行比第二行更小——长句被按宽度硬缩小。FIX 第 1 条要求统一字号。要求：script 模式所有行统一字号（720 宽时 ≥ 32px），长句按标点/宽度自动换行（每条 strip 高度随行数增加），不得缩字；加门禁：渲染字号/字高低于下限 → FAIL。
4. **script 模式 strip 背景观感差**：vid_0_script 第 3 条 strip 中间有绿色模糊色块、第 4 条有深灰污渍；vid_1_script 下方 3 条是人物皮肤/西装被高斯模糊后的棕色大色团，strip 之间有明显硬接缝和色阶跳变。要求：strip 背景改为从 hero 帧取样的统一干净底（如 hero 底部区域的平均色/轻渐变，或统一半透明深色底板），所有 strip 背景一致，无色块污渍。另外 vid_1_script 的 hero 帧上绘制的第一行字幕横跨人物/分隔线/幻灯片三个区域且与画面中原有的"而是一整篮子股票"大字重复，hero 帧上不要再叠绘与画内文字相同的句子（或把第一句也放进独立 strip）。
5. **MIT 署名缺失（TASK 通用规则）**：vendor_stitch.py 等改写自 /data/soffy/projects/vendor/chengyi-ai__native-subtitle-quote-image，但仓库里没有 third_party/ 或 NOTICE，也没有保留原作者版权与 LICENSE。要求：新增 third_party/native-subtitle-quote-image/LICENSE（原文复制）并在 NOTICE（或 third_party/README）注明来源与改动；改写文件头注明出处。
6. vid_3_native 只有 2 条字幕、sample times 为 [0.0, 20.0]（与 DONE 中"英雄帧"描述不符，0.0 秒不是字幕时间点）。核对时间点选择逻辑：hero 和每条 strip 都应落在真实字幕时间点上；若该视频可用字幕不足 3 句，在 record.json 和 DONE 中写明原因。

## 交付要求
- 重跑 scripts/quoteimage_e2e.py 全部 8 组；**逐张 read 图片**检查：无黑条、无人物/头像碎片、无重复字幕、无叠字、无裁字、字号统一可读、背景无污渍，再写 DONE。任何一条不干净就标 failed 如实写，不得硬过。
- 新增门禁/修改阈值都要有真实 fixture 测试（好图 PASS、缺陷图 FAIL），禁止 mock 门禁。
- DONE 更新：路径 + sha256 + ffprobe + 真实 gate 数值；lint 新失败数为 0（基线 4 项仅来自 .venv）。git status 干净后 commit。
- 不得复制 /data/soffy/projects/vendor/calesthio__OpenMontage（AGPL）的任何代码。
