# REVIEWSHEET-R1 独立核验报告（verify_r1）

- 单元：hevi-reviewsheet-pi-r1（自报 DONE REVIEWSHEET-R1）
- worktree：ubuntu26:/data/soffy/projects/hevi-reviewsheet，分支 feat/review-sheet
- 核验范围：a16d0db8..8d4c90a3（5a283429 + 8d4c90a3），base ff7eec6d
- 核验时间：2026-10-15（Asia/Shanghai）
- 核验员：Hark（独立，不采信 DONE 结论；全部反例自造、真跑）

## 结论：**FAIL**（不 push）

字面验收（单测 17/17、全量回归 267 passed、lint=4）都过，但自造反例共 **87 例，漏放/崩溃/误判 41 例**：
审稿表 17/38、标注修订 18/36、kids_gate 扩展 6/13（含 1 个只观察不计分的真实片）（近期核验发现的三类问题——饱和度无下限、空星海/空画面、
画面成人标签——**一类都没抓住**）。另外审稿表**从不贴真实关键帧**（所有格子永远是"无关键帧"灰底），
端到端里 pin/arrow 产出的 `camera` patch **对渲染零效果**。

## 逐项结果

| # | 验收项 | 结果 | 一句话 |
|---|---|---|---|
| 1 | 审稿表 | **FAIL** | N≤20 格数正确、SHA 稳定、双比例都有；但真实关键帧从不贴图、N=30 直接崩、9:16 页脚被截断、长台词溢出到邻格/画布外、台词行与机位行字形重叠、重复镜号 manifest 被接受 |
| 2 | 标注修订 | **FAIL** | 基础 4 条（pin+arrow 只改 camera / 未知→advisory / 镜外拒绝 / ≥2 锚点澄清）都过；但 apply_patch 不校验（5/5 非法 patch 照收）、freehand+rect 产出非法 `effect="sharpen+vignette"`、arrow 无方向/非法方向静默丢弃、左右冲突合成 `pan_left+pan_right`、坐标越界/NaN/负 from_revision 照收、无 dry-run diff API、render_annotated 可覆盖干净原图 |
| 3 | kids_gate 扩展 | **FAIL** | 3 部合规真实片 + 对照片：原 6 项判定与原入口逐项一致、扩展项无误报（✅）；through_star_sea 观察样本判 ok；7 个坏样本只抓住 2 个（色温跳变、真实→空星海的突变），低饱和发灰（全片/后半）、色相漂移、成人文字"深入机制分析"、全黑空画面、服装色块跳变全部 ok 放行 |
| 4 | 端到端 | 通过但有缺陷 | manifest→审稿表→patch→merge_patch→重渲染→gate 用本地 ffmpeg 真跑通，ffprobe/抽帧正常、渲染确定；但 camera patch 对渲染无效果；合法 vignette patch 重渲染后扩展门自己判 red（色温比误报） |
| 5 | registry / pytest / lint / 网络 | 通过 | 5 项能力可 get/resolve/render（断网 netns 内调起成功）；pytest 267 passed；断网跑 test_reviewsheet_k2 17 passed；3O lint 失败 4（=基线）；新代码无网络调用、无 mock |

## 1. 审稿表（ce_review_sheet.py → results_review_sheet.json，图在 sheets/）

独立计数：用 ACCENT 色面板外框连通域数格子（不复用被测代码）。

- ✅ N=1,2,3,4,5,6,7,9,12,16,20 × 9:16/16:9：格数全部恰等于 N；同输入两次 SHA-256 一致；非法比例/空 shots 正确拒绝；缺帧/坏帧/目录/不存在路径不崩。
- ❌ **真实关键帧从不显示**（keyframe_pasted_9x16/16x9）：关键帧存在且可解码，缩略图仍是"无关键帧"灰底（红色关键帧像素数=0）。根因：`review_sheet._draw_panel` 用 `ImageDraw.bitmap()` 贴 RGB 图 → PIL 抛 `ValueError: bad transparency mask`，被 `except Exception` 吞掉走占位。单测只测了"缺关键帧占位"，从没断言"有关键帧时真的贴上"。e2e 审稿表也全是占位（e2e/sheet_v1_9x16.png）。
- ❌ **N=30 崩溃**（两种比例）：`ValueError: y1 must be greater than or equal to y0`（cell_h 太小时 thumb_bottom<thumb_top）。没有分页/自适应。
- ❌ **9:16 页脚截断**（n01–n06、longline、longtitle、nokf 9:16 共 10 例）：页脚出画布右缘，肉眼看 6 镜样张页脚止于"总时长 22.50"，"s｜6 镜"不可见（§3.4 页脚格式不完整）。
- ❌ **长台词溢出**（longline_n2/n6 16:9）：截断按字符数 `cell_w // (cell_w*0.045)` 计，不按像素宽度量，中文全宽字溢出到邻格及画布外（sheets/longline_n2_16x9.png 可见两格台词相互压叠）。
- ❌ **台词行与机位行重叠**（肉眼，9:16 N≤6 全部）：字号≈25px 但两行间距固定 20px，"第1镜台词…"与"机位:缓慢推近 景别:中景"字形互相压住（sheets/n06_9x16.png、e2e/sheet_v1_9x16.png）。
- ❌ 重复镜号 manifest（两个 S2）`load_manifest` 照收并渲染。
- 豆腐块：本机用 SimHei，常用中文无豆腐块（目视确认）；无字体时会回落 PIL 默认字体（会成方块，模块注释自认）。

## 2. 标注修订（ce_annotation.py → results_annotation.json）

- ✅ S3 pin+arrow(right) → changes 仅 `camera="pan_right+push_in"`，其余字段 JSON 字节不变，merge_patch 通过；未知标注→advisory 且 changes 空；镜外/负数/NaN/inf/字符串时间码拒绝；2 个、3 个、2 个相同时间码→`AnnotationTemporalClarification`；不存在镜号拒绝；确定性且与标注顺序无关；`render_annotated` 正常输出时不改原图。
- ❌ `apply_patch` **不做任何校验**：`duration=-1`、`effect="explode"`、未知字段 `foo`、`transition_in="zzz"`、未知 sfx 五个 patch 全部原样合进 spec（模块自己的应用入口，docstring 说"由下游校验"，任务要求 patch 后 ShotSpec 非法必须被拒）。
- ❌ freehand + rect 同镜 → `effect="sharpen+vignette"`，ShotSpec 校验器判非法（unknown effect）；build_patch 产出非法 patch 而不拒绝/不降级 advisory。
- ❌ arrow 无方向 / `diagonal` / `RIGHT` → 既不进 changes 也不进 advisory，**静默丢弃**（违反"未知映射只进 advisory"）。
- ❌ arrow left+right 冲突 → 合成 `camera="pan_left+pan_right"`，无冲突提示。
- ❌ 坐标越界（nx=-5, ny=7）、负宽高、坐标 NaN、`from_revision=-3` 全部照收。
- ❌ 时间码恰在镜界（8000ms = S2 终点 = S3 起点）对 S2、S3 都被接受（区间两端闭，同一时刻可归两镜）。
- ❌ 重复镜号 manifest（两个 S3）被 `load_manifest` 接受；第二个 S3 实际区间 [12000,16000] 内 13000ms 的标注被按第一个 S3 判"镜外"。
- ❌ §3.5/任务书要求的 **dry-run diff** 没有任何 API（模块内无 dry/diff 函数）。
- ❌ `render_annotated(src, marks, out_path=src)` 直接覆盖干净原图（无防护），违背"干净原图与标注图分离"。
- 次要：source_refs 字段名是 `asset`/`sha256`，§3.5 写的是 `asset_sha256`；`asset` 记绝对路径。

## 3. kids_gate 扩展（ce_kids_gate.py → results_kids_gate.json；无 SRT 版 results_kids_gate_nosrt.json）

真实片（只读引用）：handdraw P_1(9:16, 56.6s)、L_1(16:9, 48.4s)、scene3d fox_in_wheat、through_star_sea(9:16)；
对照片 base16 = P_1 10–26s 摘段（540×960，音轨 loudnorm 到 -16 LUFS）。坏样本全部由 base16 用真实 ffmpeg/PIL 制作。

| 样本 | 坏区间 | 扩展门 | 时间码 | 判定 |
|---|---|---|---|---|
| handdraw_P1 / L1 / scene3d fox_in_wheat / control | — | ok，原 6 项与原入口逐项一致 | — | ✅ 不误伤 |
| scene3d through_star_sea（观察样本，近期核验点名的"空星海/发灰"片：灰绿地面+淡紫天空，饱和度很低） | — | ok | 无 | 观察：未被抓（不计分） |
| temp_jump（4500K→11000K） | 8s | red（identity+color_grade） | 8.69s | ✅ |
| empty_star_8_16（真实→空星海） | 8–16s | red（identity+color_grade） | 8.67s | ✅（只因突变被抓，不是"空画面"检测） |
| gray_full（hue=s=0.12 全片发灰） | 0–16s | **ok** | 无 | ❌ 饱和度无下限 |
| gray_second_half | 8–16s | **ok** | 无 | ❌ |
| hue_drift_half（hue=h=100） | 8s | **ok**（identity diff=10） | 无 | ❌ 色板漂移漏 |
| adult_text_4_12（烧"深入机制分析""第三章 宏观经济传导"） | 4–12s | **ok** | 无 | ❌ 画面成人文字漏 |
| empty_black_full（全片近黑） | 0–16s | **ok**（diff=0） | 无 | ❌ 空画面漏 |
| wardrobe_jump_8（同角色衣服红→绿，约 8% 画面） | 8s | **ok**（diff=20） | 无 | ❌ 服装跳变漏 |

近期核验三类问题：**饱和度无下限——抓不住；空星海/空画面——抓不住**（真实 through_star_sea 判 ok，全黑片判 ok）；
**画面成人标签——抓不住**（没有任何画面文字检测）。根因：identity/色温只看 8×8 均色的相邻差，阈值 120/0.25；
wardrobe/location 只是 manifest 声明级检查（不看画面）；没有饱和度、空画面、画面文字检测。

既有缺陷（原 6 项，base 46d7c050 就有，非本单元引入，但直接影响扩展门对真实片的判定）：不传 SRT 时
`check_dialogue_content(vp)` 把 mp4 二进制当文本扫禁用词，4 部真实片全部误报"血/打/刀/杀/死…"→ red
（results_kids_gate_nosrt.json）。本轮正式结果显式传干净 SRT 规避。

## 4. 端到端（e2e_verify.py → results_e2e.json，产物 e2e/）

- manifest_v1（6 镜，load_manifest 通过）→ render_local ep_v1.mp4（540×960、h264+aac、24.000s，sha `8a29d05c…73f6`，同输入二次渲染 SHA 一致）→ 审稿表 9:16 `6da61215…08a6` / 16:9 `c521963a…799f`（全部格子为占位，见 §1）→ S3 pin+arrow+rect @9500ms → patch `{camera: pan_right+push_in, effect: vignette}` → merge_patch（非映射字段字节不变）→ manifest_v2 → ep_v2.mp4（sha `d428577c…3846`）→ kids_gate_extended。
- S3 帧确有 vignette（角落亮度 145→69），S1 帧零差异 ✅。
- ❌ **只改 camera 的 patch 重渲染 SHA 与 v1 完全相同**：pin/arrow 唯一映射字段 `camera` 在 render_local 中不起作用，"标注→patch→重渲染"对 pin/arrow 是空转；DONE 里 e2e "14 项全 pass"正是这种空转情形。
- ❌ 合法 vignette patch 重渲染后，扩展门 `style_color_grade` 判 red（"段间色温跳变 0.841 @9.00s"），是 8×8 R/B 比在暗角下的度量伪影——产线自己的合法输出被自己的门拦下。
- 另：render_local 把所有镜底色写死为 (210,180,130)，注释写明是为了让 identity/color_grade 检查可过。

## 5. registry / 测试 / lint / 网络

- registry：`kids.review_sheet`、`kids.annotation_revision`、`kids.render_local`、`qa.kids_gate`、`qa.kids_gate.extended` 均已注册；在 `unshare -n`（无网络接口，自证 connect 1.1.1.1 → Errno 101）内 get+render 两项成功（results_registry_netoff.json）。
- pytest（soffy，JWT_SECRET=test-only TMPDIR=.tmp）：test_reviewsheet_k2 + test_kids_gate + test_shot_spec_api + test_shot_spec_render + creative_runtime/test_capabilities + test_p6_0_architecture = **267 passed**（pytest_full.txt）；断网单跑 test_reviewsheet_k2 **17 passed**（pytest_netoff.txt）。
- 3O lint：失败 4 = 基线（check_no_sibling_call / check_omodul_signature / check_enabled_pillars / check_oprim_keyword_only），lint_summary.txt。
- 新代码 grep 无 requests/urllib/http/socket；测试无 mock/monkeypatch/skip。

## 复现

```
cd /data/soffy/projects/hevi-reviewsheet
sudo -u soffy bash audit/reviewsheet/verify_r1/run_all.sh   # 任一 LEAK/FALSE_POSITIVE/ERROR 或 e2e 问题 → 非零退出
```
单项：`sudo -u soffy env JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=$PWD PATH=/home/soffy/.local/bin:$PATH /data/soffy/projects/hevi/.venv/bin/python audit/reviewsheet/verify_r1/ce_{review_sheet,annotation,kids_gate}.py`

## 文件

ce_review_sheet.py / ce_annotation.py / ce_kids_gate.py / e2e_verify.py / registry_netoff.py / run_all.sh；
results_*.json；*.out；sheets/*.png；e2e/（manifest、抽帧、审稿表；mp4 不入库）；samples/ 坏样本 PNG（mp4 不入库，run_all 重建）。
