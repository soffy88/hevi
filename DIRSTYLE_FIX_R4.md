# DIRSTYLE_FIX r4 — 主审独立核验 fix-r3（HEAD 55574a7a）不通过（2026-10-13 15:5x CST）

规则同 DIRSTYLE_FIX_R3.md：CPU-only、无付费 API、禁止 mock/占位/写死产物、**不 push、不合并**、lint 只允许基线 4 项失败、DONE 如实（不自评通过）。不要询问，直接执行到底。PATH 含 /home/soffy/.local/bin。
**硬规则**：只动本 worktree（/data/soffy/projects/hevi-dirstyle）；绝不删除 worktree 以外任何文件；不要清理磁盘；不 rm 已跟踪文件/artifacts/output；`df /data` 剩余 <5G 立即停止写 DISK_FULL_NOTE.md 退出。只 `git add` 自己改的文件，禁止 `git add -A`。

## 已核实通过（不要回退）
- B3 源片：source_clean.mp4 为 PIL 自生成（渐变天空+山丘+火柴人剪影走动），亲看 6 帧无任何文字/字幕/水印 ✓
- F5：Lock block 与 6 段 + pack.json 均含同一行 Voice profile ✓（但见下方 F5 小瑕疵）
- B5：stickman_9x16.mp4 字幕两行，亲看在框内 ✓；≥4 种姿态 + 桌子/杯子道具 ✓
- B2 四风格 9:16 构图各异 ✓；SHA256SUMS `sha256sum -c` 全 OK，沙箱下载复算一致 ✓；contact_sheet.png 与当前成片一致 ✓
- 王家卫 reframe 测试通过 ✓

## 阻断项（必须修）

### F2 旁白是机械切字，不是改写/重组（第 4 次失败）
pack.json 6 段旁白是把原文去标点后按固定字数切窗，再每 ~12 字硬插逗号，导致**词被逗号劈开**、句子跨段断裂：
- Clip00「桌上的，东西推下去」「有深，刻的进化」「触觉，感受器」，结尾「当它们触碰物体时。」半句
- Clip01 结尾「这是猫科动物刻在基因。」→ Clip02 开头「里的狩猎本能」（一句话被劈到两段）
- Clip03「奖，赏回路」；Clip04「极，好的」「要好得，多。」；Clip05「强，化」「习得性行，为模式」「三，重机制」
要求：
1. 每段旁白由**原文完整子句**组成（按原文 。！？；， 边界切分子句，再按字数 40–66 装箱），可删减/重排子句，但**不得在词中间插标点、不得把一个子句劈到两段**。
2. 每段以 。/？/！ 结尾，是能独立朗读的完整句。
3. 测试（tests/test_flow_pack.py 新增，不准放水）：
   - 把旁白按 [，。！？；、：] 切成子句，**每个子句（去空白）必须是原文某个子句的完整匹配或原文中以标点为边界的连续片段**（即子句两端在原文中紧邻标点或文首/文尾）。
   - 旁白末字符 ∈ {。, ？, ！}。
   - 相邻段之间不存在「上一段末子句 + 下一段首子句」拼接后才是原文一个子句的情况。
   - 用一个**反例**断言测试有效：构造「桌上的，东西推下去。」这种劈词旁白，断言校验函数判其不合格。

### Core message / plan.topic 泄漏 Markdown 元信息
pack.md「Core message」与 pack.json `plan.topic` 是「# 长中文通用常识文 — 猫推东西行为的科学解释\n\n## 字数参考：约 420 字\n\n猫为什么总爱…」。必须剥离 Markdown 标题行（`#` 开头）和「字数参考」类元信息，Core message 为一句中文论点（≤40 字，出自原文）。测试：Core message 不含 `#`、`字数`、换行。

### F1 火柴人节拍仍有横向运动
Clip02 [7-10s]「camera arcs gently sideways」、[3-7s]「paces a few steps toward the frame edge」= 横向运动。禁用词表补充：sideways、side to side、pan left、pan right、toward the frame edge、arc（镜头弧移）、横向、侧移；测试同步。

### F6 首尾帧与节拍语义矛盾
逐字相等已满足，但 First/Last frame 是独立的一条姿态链，与本段节拍对不上：
- Clip00 [7-10s]「crouches and places a small cup on the table edge」 vs Last「reaching upward and pushing a cup」
- Clip01 节拍结尾「rocks onto the back foot」 vs Last「holding up three separated fingers」；Clip02 [0-3s] 又是「unfolds three fingers one at a time」（First 已是三指）
- Clip04 [7-10s]「points at the object」 vs Last「arms raised high above the head」
- Clip05 [7-10s]「drops an object and flinches」 vs Last「crouched beside the table, one arm extended toward the cup」
要求：节拍与首尾帧从**同一条姿态链**生成：[0-3s] 从 First frame 状态开始，[7-10s] 以 Last frame 状态结束（Last frame 的姿态关键词须出现在 [7-10s] 节拍中）。测试：对每段断言 Last frame 的核心姿态短语（定义一组 pose token，如 three fingers / arms raised / crouch / push cup）出现在 [7-10s] 节拍里，First frame 的 pose token 出现在 [0-3s] 节拍里。

### F3 编译提示词周边字段
- 9:16 包里 `prompt.aspect_note` = "9:16 or 16:9" ✗ → 只写 "9:16"。
- `prompt.camera` = "rapid scene changes, kinetic motion-graphic transformations… touching glass, drawing luminous lines, opening doors" 与本段无关、与火柴人 1A 线条风格冲突 → 用本段节拍推导的竖向镜头描述。
- negative 里有空 token「broken line weight, , 3D humanoid」→ 去掉空项。
- 火柴人锁定块写「One classic black line stickman on white」+ negative 含 gradients，但 Palette = crimson red, cobalt blue, amber gold，且实际火柴人样片是纯黑白 → Palette 与角色描述一致（例：black line, white background, crimson red accent；≤3），编译提示词同步。
- 测试：prompt 的所有字段（不只 positive）不含 "16:9"；negative 无空 token（`", ,"`）。

### F5 小瑕疵
pack.md 中显示为「Voice profile: Voice profile: 中文普通话女声…」（前缀重复）。值里不要再带 "Voice profile:" 前缀，或 md 渲染时不重复加；测试断言 md 中不出现 "Voice profile: Voice profile:"。

### 测试过松（硬门 6）
1. **B3 烧录字检测形同虚设**：`test_source_frames_have_no_burned_text` 阈值是行内强水平边缘占比 <0.25。主审实测：在 source_clean 帧上用 56px 白字黑边画一行中文字幕 + 左上 "SHOT 02"，得分 bottom 0.097 / top 0.019；r2b 带烧录字幕的长城成片帧 0.065–0.127 —— **全部通过**，检测器不能发现字幕。要求：换成有效检测（例如字幕带区内「边缘密度 >0.03 的行数」连续 ≥15 行即判有字，或连通域/笔画宽度分析），并在测试里加**正例对照**：用 PIL/ffmpeg drawtext 在源帧上画一行中文字幕和 "SHOT 02"，断言检测器判为有字；原始源帧判为无字。
2. **B5 测试读自报 JSON**：`test_subtitle_boxes_in_safe_band` / `test_pose_metadata_has_four_plus_poses` 只读 stickman_poses.json（渲染脚本自己写的数）。要求：从 stickman_9x16.mp4 实际抽帧（≥6 帧），在字幕带内按像素找文字墨迹 bbox，断言左右在 [90, 990]、行数 ≤2；姿态数从帧中火柴人区域像素差异计算（相邻姿态段帧差显著）。
3. E2E 产物类测试 `pytest.skip("... not present")`：产物已提交，缺失应 **fail** 而非 skip（本次全套 1 skipped，查明是哪一条并消除）。
4. F2/F1/F6/F3 新增断言见上，各自配一个反例确认测试能抓住问题。

## 产物一致性
修完后重生成 flow_pack_60s（pack.md/pack.json），如重渲成片则**最后一步**重生成 SHA256SUMS、record.json、contact_sheet.png，`sha256sum -c` 全 OK 后 commit。

## 运行
`JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/test_flow_pack.py tests/test_heartbeat5.py tests/test_dirstyle_*.py -q -rs`（不得 skip 新加用例）；跑重任务用 `ulimit -v 3000000` 或分批，单元有 MemoryMax=5G。
`.venv/bin/python scripts/ci/run_3o_v3_lint.py > lint_after_r4.txt 2>&1`（失败 ≤4 项基线）。

## 交付
- 每项一个 commit（`feat/director-styles: fix-r4 <项>`），只 add 自己的文件，不 push。
- DIRSTYLE_DONE.md 追加「FIX r4」节：逐条写怎么修的、测试命令与真实输出（含反例测试）、旁白 6 段全文、成片 sha256（如有变化）；日期 2026-10-13；不自评通过；最后一行写 `DONE FIX-R4`。
