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

`output/om_quality_e2e/`，manifest `om_quality_e2e_manifest.json`，**16/16 gates 全绿**，elapsed 167.5s。

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
