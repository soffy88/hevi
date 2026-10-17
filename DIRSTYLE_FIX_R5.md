# DIRSTYLE_FIX r5：主审第 4 轮独立核验 fix-r4（HEAD 7a64cc28）不通过（2026-10-14 08:5x CST）

规则同 R4：CPU-only、无付费 API、禁止 mock/占位/写死产物、**不 push、不合并**、lint 只允许基线 4 项失败（check_no_sibling_call / check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only）、DONE 如实写，不自评通过。不要询问，直接执行到底。PATH 含 /home/soffy/.local/bin。
**硬规则**：只动本 worktree（/data/soffy/projects/hevi-dirstyle）；绝不删除 worktree 以外的任何文件；不要清理磁盘；不 rm 已跟踪的文件、artifacts 和 output；`df /data` 剩余 <5G 时立即停止，写 DISK_FULL_NOTE.md 后退出。只 `git add` 自己改的文件，禁止 `git add -A`。

## 已核实通过（不要回退）
- F1：pack.json 和 pack.md 里 sideways / side to side / pan left / pan right / frame edge / arc / 横向 / 侧移 / lateral / truck 均为 0 次；镜头只用 holds / tilts / tracks only vertically / pushes in along the vertical axis / rises。stickman_9x16.mp4 以 2fps 抽 40 帧，火柴人质心 x 落在 540–554，没有横移。✓
- F3：6 段的 aspect_note 都是 "9:16"；camera 由本段节拍推导；所有 prompt 字段都不含 16:9；negative 没有空 token；Palette 为 "black line, white background, crimson red accent"。✓
- F5：md 里没有出现 "Voice profile: Voice profile:"；锁定块每段都有。✓
- F6：Last(i) 与 First(i+1) 逐字相同；First 的姿态出现在 [0-3s]，Last 的姿态出现在 [7-10s]。✓
- B3：b3_sub.png（r3 证据：tofu 字幕 + SHOT 02）被判为有字，top_run=42、bottom_run=25；source_clean 以 5fps 扫 60 帧，0 误报。✓（但有漏检，见下）
- B5（像素实测）：40 帧字幕墨迹 x∈[93,983]，行数 ≤2，y∈[1591,1715]；帧间聚类得 6 种姿态。✓
- 成片在干净副本里从零重渲，10 个 mp4 的 sha256 与 SHA256SUMS 逐字节一致；pack.json 和 pack.md 重生成后 sha 一致。✓
- 3O lint：4 项基线，没有新增。✓

## 阻断项（必须修）

### R5-1 F2 旁白段落仍在句子中间截断（第 5 次失败）
子句级校验通过了，但 6 段里有 5 段的边界落在原文句子中间。每段结尾都被硬改成「。」，读起来像完整句，实际不是：
- Clip00 结尾「当它们触碰物体时。」：原文这里是逗号，句子在 Clip01「实际上是在用脚垫探测…」才结束。**R4 已经点名，这次没修。**
- Clip03 结尾「…让猫感到满足和愉悦，最后。」：「最后」是下一句的开头，被塞进了上一段。
- Clip04 结尾「负面关注也是关注。」，Clip05 开头「远比主人无视它要好得多」：同一句话被劈成两段。
- Clip05 结尾「简而言之，猫推东西是狩猎本能。」：原文在「、」处被截断（原句是「…是狩猎本能、神经刺激与社交需求三重机制共同驱动的结果。」），**意思被改了**，而且全片丢掉了结论「三重机制」。火柴人样片的字幕写的却是「三个原因」，两者对不上。
- 另外：「这种"模拟狩猎"也能」被渲染成「这种，模拟狩猎，也能」，在词组中间插了逗号。
- 现有测试 `sentences_are_not_split` 永远抓不到这种问题：逗号分出来的子句本来就是合法片段，条件 `left[-1] not in pieces and right[0] not in pieces` 恒为假。

要求：
1. 先按原文的 。！？ 切出**整句**，再按 40–66 个 CJK 字把整句装进段落。一句话不得跨段。整句超过 66 字时，只能在原文 ；或 ， 处拆开，并且拆出来的两半必须留在同一段，或者把这一句改写成两个独立的完整句。改写只能删字或重排，不得新增事实。
2. 最后一段必须包含原文最后一句的完整结论，也就是要包含「三重机制」。
3. 引号和 → 不得转成逗号：可以删掉引号，「推东西→主人出现」可以写成「推东西，主人就出现」，但「这种，模拟狩猎，也能」这类在词组中间插逗号的写法不允许。

机器验收（加进 tests/test_flow_pack.py，各配一个反例）：
- `segment_boundaries_on_sentence_end(narrations, source)`：对每段，先把旁白里的子句依次映射回原文，再看最后一个子句在原文中紧跟的字符，必须 ∈ {。, ？, ！} 或位于文末；第一个子句在原文中的前一个字符，必须 ∈ {。, ？, ！} 或位于文首。反例：用当前 pack 的 Clip00 和 Clip03 断言判为不合格。
- 拼起全部旁白，`"三重机制" in joined`。
- 旁白中不出现长度 ≤2 的子句夹在两个逗号之间、而原文对应位置并无标点的情况。反例：「这种，模拟狩猎，也能」必须判为不合格。
- 主审会用同一脚本复验，即本目录下的 verify_r4 F2 检查：每段首尾都必须是 OK，不得出现 MID-SENTENCE。

### R5-2 E2E 脚本从干净状态跑不通（新发现，阻断）
在干净副本里删掉所有产物后，依次跑 gen_clean_source.py → render_stickman_sample.py → render_dirstyle_e2e.py，最后一步崩溃：
```
scripts/render_dirstyle_e2e.py line 201: Image.open(OUT / f"{sid}_frame{frac}.png")
FileNotFoundError: .../wong_kar_wai_frame0.0.png
```
原因：`frame_path()` 写入时用的是 `{frac:g}`，文件名为 `frame0.png`；拼 contact sheet 时却按 `{frac}` 读，文件名为 `frame0.0.png`。结果 contact_sheet.png、record.json、SHA256SUMS 都不会生成。也就是说，已提交的 contact_sheet 不是由当前脚本产出的。
要求：contact sheet 改用 `frame_path(sid, frac)`。
机器验收：在 worktree 外的临时副本里，先删掉 output/dirstyle_e2e 下全部 mp4、png、json、SHA256SUMS，再依次运行上面 3 个脚本和 export_flow_pack，3 个脚本的 rc 都必须为 0。重生成的 10 个 mp4 必须通过 `sha256sum -c SHA256SUMS`。contact_sheet.png、record.json、SHA256SUMS 必须重新生成。DONE 里贴出完整命令和输出。

### R5-3 删掉产物后 E2E 测试仍然通过（硬门：缺产物必须 fail）
主审实测：删除 stickman_9x16.mp4、source_clean.mp4、record.json 后测试会 fail ✓；但分别删除 **wong_kar_wai_subbed.mp4、contact_sheet.png、fincher.mp4** 后，`tests/test_flow_pack.py tests/test_dirstyle_integration.py` 仍然 **60 passed**。
要求：新增产物完整性测试，内容如下：
- 读 SHA256SUMS，断言列出的每个文件都存在且哈希匹配；
- 断言 4 个风格片、4 个 _subbed、contact_sheet.png、record.json、flow_pack_60s/pack.{md,json} 都存在；
- 产物缺失时用 assert，不得用 skip。

机器验收：任意删除上述一个文件后，全套测试至少有 1 个 failed，且 0 skipped。

### R5-4 B2 构图测试不稳定（flaky）
同一 HEAD 下 `tests/test_dirstyle_reframe.py` 连跑 3 次，有 2 次失败，每次都是同样 3 条：
`test_mid_frame_foreground_present[fincher]`（"No foreground edges detected in frame"）、`test_four_styles_have_different_y_top`、`test_four_styles_have_different_heights`。DONE 里写的「156 passed」不能稳定复现。成片构图亲眼看是各不相同的，问题出在守护测试本身：芬奇的暗场前景检测不稳。
要求：查清不确定性的来源，修好检测或固定输入，不得放宽阈值来掩盖问题。
机器验收：`for i in 1 2 3 4 5; do pytest tests/test_dirstyle_reframe.py -q -p no:cacheprovider; done` 必须 5/5 全过，在负载约 7 的机器上跑；DONE 里贴出 5 次的输出。

## 需要修的非阻断项（本轮一起修）

### R5-5 B3 检测器余量太小，并且漏检了仓库自己的字幕片
- `wong_kar_wai_subbed.mp4` 在 t=9s 的帧上清楚烧着「王家卫风格」，检测器给出 bottom_run=13，判为无字（证据：verify_r4/b3_missed_wkw_subbed_t9.png）。
- 无描边白字「SHOT 02」在 28px 和 36px 时判为无字，top_run 分别为 7 和 9。
- 阈值 14 与 DONE 自报的干净片最大值 13 只差 1。

要求：提高检测灵敏度，或者换用连通域、笔画方法，并补充正例。
机器验收：
- 4 个 *_subbed.mp4 在 t∈{1,3,6,9,11}s 抽帧，共 20 帧，必须 20/20 判为有字；
- 28px 和 36px 的白字「SHOT 02」（左上角，无描边）必须判为有字；
- source_clean 以 5fps 全片扫描，误报必须为 0。

### R5-6 Core message 不是论点；source_facts 泄漏了元信息
- Core message 和 plan.topic 是「猫为什么总爱把桌上的东西推下去？」，这是一个问句。R4 要求的是「一句中文论点（≤40 字，出自原文）」，可以用原文结论句「猫推东西是狩猎本能、神经刺激与社交需求三重机制共同驱动的结果。」。测试应断言 Core message 不以 ？ 结尾，长度 ≤40，并且是原文某一整句。
- `plan.source_facts == ['420']` 来自「## 字数参考：约 420 字」元信息。`_extract_facts` 应先剥离 Markdown 标题和字数参考，再提取事实。测试应断言 source_facts 里不含 '420'。

## 运行
```
JWT_SECRET=test-secret-local PYTHONPATH=$PWD .venv/bin/python -m pytest tests/test_flow_pack.py tests/test_heartbeat5.py tests/test_dirstyle_*.py -q -rfs -p no:cacheprovider
```
要求 0 failed、0 skipped，并按 R5-4 连跑 5 次。重任务用 systemd-run，参数 MemoryMax=3G。
```
.venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_after_r5.txt 2>&1
```
失败项只能是上述 4 项基线。

## 产物一致性
修完后重生成 flow_pack_60s。如果重渲了成片，最后一步重生成 SHA256SUMS、record.json、contact_sheet.png，`sha256sum -c` 全部 OK 后再 commit。

## 交付
- 每项一个 commit（`feat/director-styles: fix-r5 <项>`），只 add 自己的文件，不 push。
- DIRSTYLE_DONE.md 追加「FIX r5」节：逐条写怎么修的、测试命令和真实输出（含反例）、6 段旁白全文、R5-2 干净重渲的完整输出、R5-4 的 5 次运行输出，日期 2026-10-14，不自评通过。最后一行写 `DONE FIX-R5`。
