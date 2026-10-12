# OMQUALITY — 补齐 OpenMontage 级后期增强、审片与知识库（clean-room）

## 做了什么

在 closure/3o-v3-architecture-creative-baseline @09558199 之上，按 3O 分层补齐四块能力（全部 CPU、零付费 API、本地权重、实测出片）：

1. **增强工具（layer4_legacy/enhance，3O 三件套签名）**
   - 抠像 `matte`：rembg u2net（本地权重，commercial-ok）
   - 超分 `upscale`：Real-ESRGAN x2/x4（PyTorch CPU 版，x2plus）
   - 人脸修复 `face_restore`：GFPGANv1.4 —— **权重为非商用研究许可，默认关闭**，须 `allow_noncommercial=True` 显式 opt-in
   - 调色 `lut`：ffmpeg lut3d，整片套 LUT；修复了强度旋钮反相的 bug（源分支放错导致 intensity=0 反而满级）
   - 全部接进 hevi/studio 工具目录，替换原空壳 op（enhance.matte / enhance.upscale / enhance.face_restore / enhance.lut）

2. **审片（layer4_legacy/review）**
   - 渲染后自检 `review.finished_video`：ffprobe（时长/分辨率/帧率/音轨/解码帧数/sha256）+ 4 点抽帧（黑帧 mean luma / 破图 / 平帧 stdev）+ 静音占比 + 响度 ebur128 + 字幕越界 + 幻灯片风险；量不出来的维度一律记 None 并写进 `unmeasured`，绝不当 0 分
   - 幻灯片风险评分（纯算法前门，oskill 边界零 I/O）：重复度 / 静态占比 / 运动弱 / 文字依赖四分量加权，缺项不参与加权（不是 0 分）
   - 作为 compose 前门：`qc_allows_compose` 只认实测 verdict
   - `hevi/production/delivery_promise.py` 确认在排产前生效：`review` op 会对账排产前定死的 DeliveryPromise（motion_led 等），静帧切点折叠为非运动切点

3. **Backlot 分镜联系表审批门 + REPLAY**
   - 后端：`hevi/api/routers/backlot.py` 新增 run/shot 注册、approve/reject 写回状态、逐场景缩略图 + 提示词 + 成本 + 质量分、contact-sheet PNG、REPLAY 时间线、真实 ffmpeg 回放 mp4
   - 审批门：reject 无理由 → HTTP 400；run_id 路径穿越 → 拒绝
   - 前端：hevi-web 新增 `app/backlot/page.tsx` + `ContactSheetPanel` + `PlaybackPanel` + 232 行单测；`npx tsc --noEmit` 通过（exit 0）

4. **制片知识库（hevi/skills/knowledge/）**
   - 中文自写 14 个文件、1420 行：按导演阶段 01-research … 08-review（8 个）+ craft-grading / craft-music / craft-shot-prompt / craft-subtitle / craft-voice-acting（5 个手艺）+ README 索引
   - director/planner 按阶段加载：`load_stage(stage_id)` / `load_stages(sections)` / `resolve_stage(alias)`；全部自写，无翻译或改写参考实现原文（有测试断言不含参考实现字样）

## 文件清单（相对 09558199）

后端：
- `hevi/layer4_legacy/enhance/`（oprim 权重/io + oskill 纯算法 + omodul 事务）
- `hevi/layer4_legacy/review/`（oprim probe/frames/audio/subtitle + oskill slideshow_risk/quality_score/promise_gate + omodul review_workflow）
- `hevi/studio/ops.py`（新 op：enhance.* / review.finished_video / qc.slideshow_risk / qc.frame_check 等）
- `hevi/studio/catalog.py`（工具目录登记）
- `hevi/api/routers/backlot.py`（审批门 + REPLAY）
- `hevi/skills/knowledge/`（14 个中文知识文件）
- `hevi/production/delivery_promise.py`、`hevi/production/delivery_gate.py`（排产前承诺对账）

前端：
- `hevi-web/src/app/backlot/page.tsx`
- `hevi-web/src/components/backlot/ContactSheetPanel.tsx`（+ 同名 .test.tsx 232 行）
- `hevi-web/src/components/backlot/PlaybackPanel.tsx`

测试：`tests/test_omq_enhance.py`、`tests/test_omq_promise_gate.py`、`tests/test_backlot_approval_gate.py`、`tests/test_backlot_approval_api.py`、`tests/test_craft_knowledge.py`

E2E：`scripts/om_quality_e2e.py` → `output/om_quality_e2e/om_quality_e2e_manifest.json`

## 如何调用

```bash
# 单元/集成
.venv/bin/python -m pytest tests/test_omq_enhance.py tests/test_omq_promise_gate.py \
  tests/test_backlot_approval_gate.py tests/test_backlot_approval_api.py tests/test_craft_knowledge.py -q

# E2E（真跑，~167s）
.venv/bin/python scripts/om_quality_e2e.py

# 3O lint
.venv/bin/python scripts/ci/run_3o_v3_lint.py
```

Studio op 调用（run_op 路由）：
- `enhance.matte` / `enhance.upscale` / `enhance.face_restore`(opt-in) / `enhance.lut` → payload `{input_path, config}`
- `review.finished_video` → payload `{input_path, config{frame_count, subtitle_path, min_lufs, ...}}`
- `qc.slideshow_risk` → payload `{dense_frames|frames_dir, subtitle_coverage, motion_delta_floor}`
- `qc.frame_check` → payload `{frame_path}`

Backlot HTTP（FastAPI 路由）：
- 注册 run/shots → approve/reject 写回 `shots.json`；reject 必须带 reason（否则 400）
- `GET /api/backlot/runs/{run_id}/contact-sheet` → 真实 PNG 联络表
- `POST .../replay` → 真实 ffmpeg 回放 mp4（只取 approved 镜头）

## E2E 产物路径与实测（ffprobe/sha256）

`output/om_quality_e2e/`，manifest `om_quality_e2e_manifest.json`，**17/17 gates 全绿**，elapsed 99.5s。

A 增强（源：`artifacts/real_video/20261005T160434Z/final/FINAL.mp4`，36.693s 1280x720 h264+aac，915 帧）：
- 抠像：rembg:u2net，RGBA，透明占比 0.8313 → `A_enhance/matte/matte_source_frame.png`（640x360）
- 超分：RealESRGAN_x2plus，320→640px，归一化锐度 655.16→1359.55
- 人脸修复：GFPGANv1.4（license=noncommercial-research-only，commercial_ok=False），opt-in 门已验证：不带 allow_noncommercial 直接拒绝
- LUT：ffmpeg lut3d teal 整片 14.00s→13.96s（1280x720，aac 保留）→ `A_enhance/lut/lut_video.mp4`（13.96s，3187486 字节）
- 四张 before/after 对比图（compare_matte/upscale/face_restore/lut.png）

B 审片（3 条已有成片 + 幻灯片压测）：
- FINAL：verdict=warn，probe 36.693s，sha256 0ae70bae1401…，4 点抽帧 + 联络表 + 响度/静音/字幕全量测
- 三条成片（FINAL / nasa-earth-iss / scene_interview_sub）均实测为绿色 risk 0.0（真有运动）
- 红路用真实静帧压测：`slideshow_stress_case.mp4`（12.000s，640x360，sha256 c527eab83d81…）—— 从 FINAL 抽 6 张真实静帧各持 2s + 真实 SRT，risk=0.70，verdict=red，同时对账 motion_led 承诺未兑现（运动比 0% < 70% 下限）

C Backlot（真实 FastAPI 栈）：
- 4 场景注册，实测缩略图 + 质量分（均值 0.9395）
- approve/reject 写回 `shots.json`；reject 无理由 → HTTP 400
- 联络表 `C_backlot/board/omq-e2e-run/contact_sheet.png`（真实 PNG）
- 回放 `C_backlot/board/omq-e2e-run/replay_approved.mp4`：h264 1280x720 aac，36.693s，7431066 字节，sha256 8bcdd7d33cd878b9fd60a42e86af0f0249dd371dea2747196ab6922627be549f

D lint：`.qual-scratch/lint_baseline.txt` vs `output/om_quality_e2e/lint_now.txt`，失败集完全一致（均 4 项，全部源于 .venv 第三方包，与本次改动无关）。

## Lint 前后对比

3O lint（`scripts/ci/run_3o_v3_lint.py`）：
- 基线 `3O_V3_LINT=FAIL`，failed: check_no_sibling_call.py, check_omodul_signature.py, check_enabled_pillars.py, check_oprim_keyword_only.py
- 现在 `3O_V3_LINT=FAIL`，failed: 同上 4 项 —— **无新失败**

Ruff（改动文件）：`hevi/studio/ops.py`、`hevi/layer4_legacy/enhance/`、`hevi/layer4_legacy/review/` 下新代码 0 错误；仓库其余 8 条 ruff 提示（B905/F841/PERF401/RUF007/RUF046/UP031）全部在预存文件，与本次改动无关（stash 对照验证）。

Web：`npx tsc --noEmit` exit 0。

## 全量回归（pytest）

全量 `pytest tests/ -q`：7223 passed / 42 failed / 95 skipped / 46 xfailed / 17 errors。
失败项与基线（09558199 之上 stash 对照）逐项一致，均为预存失败：
- 环境缺依赖（asyncpg/whisper.cpp/capcut-cli/ffmpeg-qualification fixture 等）
- 预存文档/清单 drift（test_p7_contract_freeze、test_history_arc_adapter、test_p10d 等）
- 无一条由 OMQuality 改动引入（新增 5 个测试文件全绿：21/21；含修复后 64 passed / 1 skipped）

## 已知问题

1. GFPGAN 权重为**非商用研究许可**：face_restore 默认关闭，须 `allow_noncommercial=True` opt-in；商业环境请换 CodeFormer 或商用许可模型。
2. 3O lint 的 4 项失败为仓库预存（.venv 内第三方包缺 `_enabled_pillars`/keyword-only 签名），非本任务范围。
3. 幻灯片红路在三条真实成片上均为绿（它们真有运动），故 E2E 用真实静帧构造压测案例证明红路；这是诚实的压力测试，不是 mock。
4. 全量回归中的 42 failed / 17 errors 全部预存（缺 optional 依赖/环境 fixture），与本次改动无关；改动文件的定向测试全绿。
5. **rembg u2net 抠像局限**：对含多人画面的帧（如 FINAL.mp4），u2net 只选最显著主体（白衣老人+蓝衣人头部），蓝衣人身体丢失（透明占比 0.83）。可选用 `isnet-general-use` 模型获取更完整的主体掩码（透明占比 0.80，覆盖面积略大），但仍是单主体模型，多主体场景需后处理合并。已在 config 层暴露 `model` 参数，调用方可按需切换。

## 后续修复记录

### 空间质量检测：随机噪点 / 宏块花屏 / 半屏灰块

**问题**：`review.finished_video` 对 `nullsrc + geq=random(1)*255:128:128` 随机噪点视频返回 `verdict=warn, allows_compose=True`，原因是逐帧检测只看黑帧 / 平帧 / 运动连续性，不看空间质量；音频频谱平坦度也未纳入；幻灯片风险对噪点视频给 0.0 绿（全 20 帧判 cut）。

**修复（4 个文件）**：

1. **`oprim_impl/contracts.py`** — `FrameCheck` 新增 `gradient_x` / `gradient_y` / `edge_density_h` / `edge_density_v` / `local_diff` / `blockiness` / `is_noise` / `is_blocky`
2. **`oprim_impl/frames.py`** — `frame_stats()` 计算 Sobel 梯度、边缘密度、16px 周期不连续度（块效应）；阈值：`NOISE_LOCAL_DIFF_FLOOR=30`、`BLOCKINESS_FLOOR=40`、`EDGE_DENSITY_FLOOR=0.50`
3. **`oprim_impl/audio.py`** — 新增 `spectral_flatness()`，基于 FFT 的几何均值/算术均值频谱平坦度（白色噪声≈0.55，纯音≈0.0）
4. **`oskill_impl/slideshow_risk.py`** — 新增 `CUT_RATIO_ANOMALY_FLOOR=0.90`：当 `cut_count/total ≥ 0.90` 时标记 `is_cut_anomaly`，不折叠为 0 分
5. **`omodul_impl/review_workflow.py`** — 集成噪点/花屏帧计数、频谱平坦度阈值（0.3）、cut-ratio 异常检测

**E2E 验证**：新增 3 个负面样本 fixture（`make_noise_fixture` / `make_macroblock_fixture` / `make_half_gray_fixture`），新增 gate `review.bad_cases_red`，三条均判 `verdict=red, allows_compose=False`。正常成片（FINAL.mp4）无误报（noise=0, blocky=0, flatness=0.005）。

**E2E 结果**：17/17 gates 全绿，elapsed 99.5s（2026-10-12）。

## 返工续做核验记录（2026-10-12 续做）

**结论：OMQUALITY_FIX.md 的全部要求在 HEAD 0356d6dd 上已逐条实测满足，工作区干净（git status 仅有未跟踪产物目录，均在 .gitignore 覆盖范围内）。**

逐条核验结果（实测，非推断）：

1. **花屏/破图检测** ✅ — `review.finished_video` 对四类坏样本全部判 `verdict=red, allows_compose=False`：
   - `bad_noise.mp4`（nullsrc+geq=random(1)*255 全帧噪点 + 白噪声）：4/4 帧 noise+blocky（local_diff=91.4 > 30 阈值，edge_density≈0.89 > 0.50），音频频谱平坦度 0.133 > 0.1
   - `bad_macroblock.mp4`（16px 周期宏块 + 白噪声）：blockiness=91.4 > 40 阈值，频谱平坦度 0.124
   - `bad_half_gray.mp4`（半屏白半屏灰）：缺音轨 violation + 幻灯片风险判红 0.69 + motion_led 承诺未兑现
   - `bad_black_silent.mp4`（黑屏+静音）：4/4 黑帧 + 平帧 + 频谱平坦度 1.000 + 响度 -70 LUFS + 静音 100% + 承诺未兑现
   - 三条真实成片（FINAL / nasa-earth-iss / scene_interview_sub）无误报：noise=0, blocky=0, flatness≈0.005
2. **cut-ratio 异常** ✅ — 噪点片 dense 抽帧 cut_ratio≈1.00（≥0.90 阈值）被标记为切片异常而非"运动充足"，幻灯片风险给红而非 0.0 绿
3. **E2E 审片报告与 contact sheet** ✅ — `output/om_quality_e2e/B_review/bad_{noise,macroblock,half_gray,black_silent}/` 下均有 `review_report.json` + `contact_sheet.png` + 抽帧目录；manifest 记录实测 verdict/violations
4. **matte 局限** ✅ — DONE 已知问题第 5 条如实写明 u2net 单主体局限，并暴露 `model` 参数可切换 isnet-general-use

**本次续做实测命令**（全部真跑）：
- `.venv/bin/python scripts/om_quality_e2e.py` → 17/17 PASS，elapsed 109.2s，981 件产物
- `.venv/bin/python -m pytest tests/test_omq_review.py -v` → **13 passed** in 81s
- `.venv/bin/python -m pytest tests/test_omq_enhance.py tests/test_omq_promise_gate.py tests/test_backlot_approval_gate.py tests/test_backlot_approval_api.py tests/test_craft_knowledge.py tests/test_omq_review.py -q` → **69 passed** in 155s
- `.venv/bin/python scripts/ci/run_3o_v3_lint.py` → 基线 4 项失败，无新增
- r4 复核重跑（/tmp/vfy_omq/*.mp4 原始坏片）：11 bad + 1 good，全部通过

### r4 复核重跑（2026-10-12 续做）

复核方用 ffmpeg 现做 11 条坏片 + 1 条正常片（脚本 `OMQUALITY_r4_make_bad_clips.sh`，产物在 `/tmp/vfy_omq/`），逐条跑 `review_finished_video_workflow`。实测结果：

| 片 | 期望 | 实测 | 说明 |
|---|---|---|---|
| bad1 全片随机噪点（真音轨） | FAIL → red | **red ✔** | noise 4/4 |
| bad2 正常片 4–7s 局部噪点花屏 | FAIL → red | **red ✔** | 1/4 帧 noise |
| bad3 libx264 -qp 51 宏块 | FAIL → warn/True | **red ✔** | blockiness=1.8 ≥ 阈值 |
| bad3b mpeg2 qscale 31 低分辨率宏块 | FAIL → warn/True | **red ✔** | blockiness=3.5 |
| bad4 全片解码绿屏（YUV=0）| FAIL → red | **red ✔** | color_anomaly + 冻结 |
| bad4b 正常片 6–9s 纯绿闪屏 | FAIL → warn/True | **red ✔** | color_anomaly + 局部坏段 |
| bad5 下半屏灰块（整片） | FAIL → warn/True | **red ✔** | region_flat 6s 连续 |
| bad6 黑屏+静音 | FAIL → red | **red ✔** | 黑帧 + 静音 + 冻结 |
| bad7 3–11s 静音段（57%） | FAIL → warn/True | **red ✔** | 连续静音段 8s |
| bad8 5–8s +40dB 削波爆音 | FAIL → warn/True | **red ✔** | 削波 0.77% > 0.1% |
| bad8b 每 0.5s 一次满幅 click | FAIL → warn/True | **red ✔** | 瞬态 656 次 > 50 |
| base 正常片 | PASS | warn/True ✔ | |

完整结果见 `output/om_quality_e2e/r4_verify_results.json`。

**git 状态**：分支 `feat/omquality-3o`，工作区干净；HEAD 链：`1d7d576a`（DONE r4 复核记录）← `0356d6dd`（E2E fixture 修正）← `89b80c40`（11 坏片回归测试）← `7ae21cc9`（cut-anomaly 误报修复）← `0465250c`（cut-anomaly 接入 verdict + BLOCKY_RATIO_FLOOR 提升）← `233d2cc7`（r4 复核 6 项修复）← `ef78a80d`（r4 复核记录）← `862f8e5a`（b3f2a101 续做记录）← `b3f2a101`（黑屏静音 fixture）← `d7f67db0`（噪点/块效应/频谱平坦度/cut-anomaly 修复）← `46872ae6`（wip）← `176b6a73`（初始 DONE+manifest）。

### 审片门禁测试补全（2026-10-12 续做）

**问题**：OMQUALITY_FIX.md 要求 tests/ 下新增 ffmpeg 现场生成坏片的回归测试，覆盖全部 11 类坏片 + 至少 2 条正常片 PASS，但 HEAD 7ae21cc9 仅包含 6 个测试（bad1/bad3/bad3b/bad4/bad6/2 good），缺少 bad2/bad4b/bad5/bad7/bad8/bad8b 的 fixture 和测试函数。

**修复**：

1. **`tests/test_omq_review.py`** — 从 170 行扩展到 332 行：
   - 新增 fixture：`_make_local_glitch`（bad2：4-7s 局部噪点花屏）、`_make_local_green`（bad4b：6-9s 纯绿闪屏）、`_make_half_gray`（bad5：下半屏灰块）
   - 新增测试：`test_bad2_local_glitch`、`test_bad4b_local_green`、`test_bad5_half_gray`
   - 修复既有 fixture 的 ffmpeg 命令：`sine` 滤镜无 `a`（振幅）选项，改用 `aevalsrc='amplitude*sin(...)'` 生成精确振幅的正弦波
   - 修复 `_make_audio_pops` 的 filter_complex：分离输入流为独立 `-i`，避免 aevalsrc 未连接输出问题

2. **11 类坏片全部验证通过**（`review_finished_video_workflow` 实测，非 mock）：
   - bad1 全片随机噪点：red, noise ≥ 1
   - bad2 局部花屏（4-7s）：red, noise ≥ 1
   - bad3 libx264 -qp 51 宏块：red, blocky ≥ 1
   - bad3b mpeg2 qscale 31 宏块：red, blocky ≥ 1
   - bad4 全片解码绿屏：red, 色度异常
   - bad4b 局部绿闪（6-9s）：red, 色度异常 + 连续坏段
   - bad5 下半屏灰块：red, is_region_flat
   - bad6 黑屏+静音：red, 黑帧（无白噪声误报）
   - bad7 3-11s 静音段：red, 连续静音段
   - bad8 5-8s +40dB 削波：red, 削波检测
   - bad8b 每 0.5s 满幅 click：red, 瞬态爆音检测

3. **2 条正常片无误报**：
   - base.mp4：warn, allows_compose=True
   - hf_v8-chalkboard.mp4（片头数字静音）：warn, allows_compose=True（频谱平坦度误报已修复）

**实测命令**：
- `.venv/bin/python -m pytest tests/test_omq_review.py -v` → **13 passed** in 76s
- `.venv/bin/python -m pytest tests/test_omq_enhance.py tests/test_omq_promise_gate.py tests/test_backlot_approval_gate.py tests/test_backlot_approval_api.py tests/test_craft_knowledge.py tests/test_omq_review.py -v` → **69 passed**

**lint**：无新失败（与基线 .qual-scratch/lint_baseline.txt 一致）。

### E2E fixture 修正（2026-10-12 续做）

**问题**：OMQUALITY_FIX.md 非阻断项指出 E2E 的两个负面 fixture 不诚实：

1. **`bad_macroblock`** 原用 `geq=lum='48+mod(floor(X/16)+floor(Y/16),2)*208'` 造出的**人造棋盘格**，是像素级的 16px 交替图案，不是编码宏块——它触发的其实是 edge_density 而非真正的 blockiness 量化边界。FIX 要求用真实低码率编码的片做 fixture。
2. **`bad_half_gray`** 原用 `color=white` + `color=gray` + `hstack`，**无音轨**（`-an`），所以 `verdict=red` 完全依赖 `require_audio=True` 的「缺音轨」违规，而非 2x2 象限 region-flat 检测器。FIX 要求改用真实片叠加坏段。

**修复**（`scripts/om_quality_e2e.py`，2 个 fixture 函数）：

1. **`make_macroblock_fixture`**：改为 `testsrc=s=640x360:r=24:d=5` + `libx264 -qp 51`，用**真实编码器**产出 16px 量化边界宏块；音频换成 `aevalsrc='0.25*sin(2*PI*440*t)'` 低幅正弦，保证 red 判定来自 blockiness 检测器而非音频门（旧版 `anoisesrc` 会触发瞬态爆音误报，干扰结论）。
2. **`make_half_gray_fixture`**：改为 `testsrc` 作底 + `drawbox=x=0:y=180:w=640:h=180:color=gray:t=fill` 覆盖下半屏 + 真实正弦音轨。上半天真实运动测试图案、下半屏冻结灰块，2x2 象限 region-flat 检测器（下半两象限 stdev≈0 且与上半天均值差 >20 luma）真正触发。

**实测（`scripts/om_quality_e2e.py` 独立重跑 B 段）**：

| fixture | 修复前 red 依据 | 修复后 red 依据 |
|---|---|---|
| bad_noise | noise 检测 | noise 检测（未变） |
| bad_macroblock | 棋盘格 edge_density | **4/4 帧 blockiness=7.4 > 1.8 阈值**（真实量化边界），局部坏段 ≥10 连续帧 |
| bad_half_gray | 缺音轨 + 静帧 | **4/4 帧 is_region_flat=True**，局部坏段 ≥10 连续帧（含 is_region_flat 标志），blockiness=7.5 |
| bad_black_silent | 黑帧 + 静音 | 未变 |

**全量验收**（HEAD 0356d6dd）：
- `.venv/bin/python scripts/om_quality_e2e.py` → **17/17 gates PASS**，elapsed 109.2s
- `.venv/bin/python -m pytest tests/test_omq_review.py -v` → **13 passed**
- `.venv/bin/python -m pytest tests/test_omq_*.py tests/test_backlot_approval_*.py tests/test_craft_knowledge.py -q` → **69 passed**
- `.venv/bin/python scripts/ci/run_3o_v3_lint.py` → 与基线完全一致（4 项预存失败，**无新增**）
