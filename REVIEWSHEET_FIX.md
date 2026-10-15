# REVIEWSHEET_FIX — R2 修复任务书（核验员 verify_r1 判 FAIL）

- worktree：`/data/soffy/projects/hevi-reviewsheet`，分支 `feat/review-sheet`，当前 HEAD 之上续做
- 完整证据：`audit/reviewsheet/verify_r1/REPORT.md`（先读）、`results_*.json`、`sheets/`、`e2e/`
- 完成文件：`REVIEWSHEET_DONE.md`（追加 R2 节）；完成标志（最后一行）：`DONE REVIEWSHEET-R2`
- 依据：`/data/soffy/projects/hevi-renoise/RENOISE_EVAL.md` §3.4–3.6、§4 K2；仍遵守 `REVIEWSHEET_TASK.md` 全部硬规则

## 总验收（硬门槛）

```
cd /data/soffy/projects/hevi-reviewsheet
bash audit/reviewsheet/verify_r1/run_all.sh ; echo exit=$?
```
**必须 exit=0、TOTAL_BAD 0**：三份 results 中不得再有任何 LEAK / FALSE_POSITIVE / ERROR，e2e problems 为空。
**不得修改 `audit/reviewsheet/verify_r1/` 下的反例脚本与 run_all.sh**（只能改产品代码与新增测试）；
合规真实片（handdraw P_1/L_1、scene3d fox_in_wheat）与对照片不得被新检查误报（scene3d through_star_sea 为观察样本，判 red 或 ok 均不计分，但须在 DONE 中写明结果）。另外：pytest 全过、3O lint 失败 ≤4、无网络、无 mock。

## 必修问题（复现 → 期望 → 实际）

### A. 审稿表 `hevi/kids/review_sheet.py`
1. **真实关键帧从不贴图**。复现：`ce_review_sheet.py` 的 `keyframe_pasted_*`。期望：关键帧存在可解码时缩略图显示该图（红色关键帧 → 缩略图区大量红像素）。实际：一律"无关键帧"灰底；`ImageDraw.bitmap()` 贴 RGB 抛 `bad transparency mask` 被 `except Exception` 吞掉。修：`img.paste(...)`；只在真正缺失/解码失败时占位。
2. **N=30 崩溃** `ValueError: y1 must be greater than or equal to y0`。期望：任意 N（至少 1–60）不崩、格数恰为 N（自适应缩放或分页；分页时每页格数之和 = N 且页脚标明页码）。
3. **9:16 页脚截断**（"总时长 22.50"后被裁）。期望：§3.4 页脚完整可见（按像素宽度量，超宽时缩字号/换行，不得越出画布）。
4. **长台词溢出邻格/画布外**（16:9 longline）。期望：按像素宽（`textlength`）截断加"…"，任何文字不越出所在格。
5. **台词行与机位行字形重叠**（9:16 N≤6）。期望：行距 ≥ 字高，两行不相交（按 `textbbox` 排版）。
6. 重复 `shot_index` 的 manifest 必须在 `load_manifest` 拒绝（`ManifestValidationError`），同时检查镜号连续性与 transition_table 一致。

### B. 标注修订 `hevi/kids/annotation_revision.py`
1. `apply_patch` 必须走 ShotSpec 校验（`merge_patch`/`ShotSpec.model_validate`），并拒绝 ShotSpec 未定义字段：`duration=-1`、`effect="explode"`、`foo`、`transition_in="zzz"`、未知 sfx 五例都要抛错。
2. `build_patch` 不得产出非法值：freehand+rect 同镜不能合成 `effect="sharpen+vignette"`（ShotSpec 判非法）。按确定性优先级取一个合法 effect 并把其余写入 advisory，或整体降为 advisory；产出的每个 patch 必须能通过 `merge_patch`。
3. arrow 无方向/非法方向（None、`diagonal`、`RIGHT` 等）不得静默丢弃 → 进 advisory（大小写可规范化后映射，但须测试）。
4. 互相矛盾的 arrow（left+right、up+down）不得合成 `pan_left+pan_right` → 进 advisory，changes 不含 camera。
5. 校验输入：坐标 nx/ny ∈[0,1]、nw/nh ∈[0,1] 且有限（NaN/inf 拒绝）、`from_revision` 为非负整数、时间码为有限数值；非法 → `AnnotationError`。
6. 镜内区间改为半开 `[start, end)`（最后一镜可含 end），镜界时刻只归一个镜。
7. 重复镜号 manifest 拒绝（同 A6）。
8. 新增 **dry-run diff** API（如 `dry_run_diff(spec, patch) -> {field: {"before":…, "after":…}}`），确定性，测试覆盖。
9. `render_annotated` 输出路径与 `authoritative_source` 相同（含 resolve 后相同）必须拒绝，原图字节不变。
10. source_refs 按 §3.5 提供 `asset_sha256`（可保留 asset 字段）。

### C. kids_gate 扩展 `hevi/quality/kids_gate.py`（原 6 项判定逻辑不得改变）
对 `ce_kids_gate.py` 的坏样本都要 red 且给出落在坏区间（±0.6s）内的时间码，且在 checklist 里有对应项：
1. **饱和度下限**：逐段（≥每秒 1 帧）测 HSV/YUV 饱和度，均值低于阈值 → fail + 时间码（gray_full、gray_second_half）。阈值要让 3 部合规真实片与对照片不误报。
2. **空画面/空星海**：低亮度+低细节（边缘密度/方差/前景占比）持续 ≥N 秒 → fail + 时间码（empty_black_full、empty_star_8_16 的后半段要靠"空画面"项本身命中，不能只靠突变）。
3. **画面成人文字/标签**：CPU 本地 OCR（venv 已装 `rapidocr_onnxruntime`，不得联网下模型；也可复用 `hevi/layer4_legacy/comicnarr/oprim_impl/subtitle_ocr.py`）抽帧识别画面文字，命中成人/非幼儿词表（至少含"机制""分析""宏观""经济""章"等，词表可配置）或非字幕区大段文字 → fail + 时间码（adult_text_4_12）。
4. **色板/色相漂移**：在 8×8 均色之外加入色相直方图/主色板（如 k-means 或 HSV 直方图距离）相邻比较（hue_drift_half）。
5. **服装/局部色块跳变**：不能只看整帧均色；做分块（如 4×4 网格）或前景区域的颜色变化检测（wardrobe_jump_8 衣服红→绿约 8% 画面）。
6. 色温/调色检查不得把产线合法 effect（单镜 vignette）误判为段间色温跳变：e2e 中 S3 vignette 重渲染后 gate 须为 ok（如在亮度归一化/去暗角后再比 R/B，或排除近黑像素）。
7. 不传 SRT 时，`kids_gate_extended` 不得把 mp4 二进制当台词扫禁用词（既有缺陷；可在扩展入口中无 SRT 时跳过/标记 `dialogue_content: "skipped"` 并在报告中写明；原 `kids_gate_workflow` 行为如需改动，在 DONE 中说明理由并保证 test_kids_gate 全过）。
8. 报告保持完整 checklist（新增项加入 `CHECKLIST_ITEMS`），每个 fail 都带时间码。

### D. 端到端 / 渲染
1. `render_local` 必须让 `camera` 字段生效（push_in → 缓慢 zoompan/scale 推近，pan_left/right、tilt_up/down → 平移），只改 camera 的 patch 重渲染 SHA 必须变化且 S3 帧可测地变化、其它镜帧不变。不得为过门而写死底色以外的"作弊"逻辑；按镜可用 manifest 的 scenes.palette / 关键帧作为底图。
2. e2e（`e2e_verify.py`）全部 problems 为空。

## 必须新增的测试（tests/，真跑、无 mock）
- 审稿表：有关键帧时像素断言贴图成功；N=1..60 不崩且格数=N（独立像素计数，不复用被测布局常量）；页脚/台词/机位文字 bbox 不越格不越画布、两行不相交；重复镜号拒绝。
- 标注：上面 B1–B10 每条至少一个正例/反例；所有 build_patch 产物 `merge_patch` 必过；dry-run diff；render_annotated 覆盖原图拒绝。
- kids_gate：用真实 ffmpeg 现做的低饱和、空画面、画面成人文字、色相漂移、局部服装跳变五类坏样本 red+时间码；至少 2 部合规真实片（handdraw/scene3d fox_in_wheat 只读引用，路径不存在时在测试内用 ffmpeg 现渲一条有内容的片替代）不误报；e2e vignette patch 后 gate ok。
- 端到端：camera-only patch 改变渲染。

## 约束
- 只改本 worktree；临时文件 `.tmp/`；不提交 `.tmp/`、`pi_r*.jsonl`、`*.err`、日志、mp4。
- CPU-only、单进程渲染、pytest 不开 -n；可用内存紧（约 6G），OCR 抽帧控制分辨率与帧数。
- 不 push、不合并、不改写历史；只 `git add` 自己的文件；不要询问，执行到底。

## 安全规则
只改本 worktree；不删 worktree 外任何文件；不清理磁盘（/data <5G 写 DISK_FULL_NOTE.md 停止）；所有 python 设 PYTHONPATH=/data/soffy/projects/hevi-reviewsheet；不 push；不调付费 API；不要把 lint 日志提交进仓库。完成后在 REVIEWSHEET_DONE.md 最后一行写 DONE REVIEWSHEET-R2。
