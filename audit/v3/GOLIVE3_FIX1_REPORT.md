# HEVI-V3 修复轮 1（GOLIVE3_FIX1）验收报告

## 1. 修复项概述与执行动作
针对上一轮 (ec0af485/1444ecbd) 核验指出的 5 大痛点，本轮逐一严格修复：
1. **真实端到端渲染 (`tests/test_golive3_e2e.py`)**：
   - 弃用之前的 `ffmpeg lavfi` 纯蓝色块占位。
   - 改为调用仓库原生本地渲染管线 `hevi.assembly.freevideo.workflow.free_video_workflow`，输入为 3 场景幼儿剧本 → `assets.extract` → 资产库持久化 → 风格快照锁定 → 镜头组拆分 (StoryPlan) → 多参考图合成预览，真正渲染出时长 23.00 秒的幼儿片，产物落至 `audit/v3/e2e/e2e_toddler_story.mp4`，并通过 `ffprobe` 严格校验时长 ≥20 秒。
2. **模块复用与架构内聚 (`hevi/capabilities/golive3.py` & `hevi/api/routers/golive3.py`)**：
   - **`assets.extract`**：复用 `hevi.creative.layer4.importer.ImportModule` 进行剧本章节结构解析与确定性实体提取。
   - **`assets.library`**：与 `hevi.subjects.ReferenceStore` 打通，实现参考图落盘与持久化资产库 (`output/golive3_persistence.json`)，支持跨重启读取，并挂载 FastAPI CRUD 路由 (`/api/golive3/assets`) 及 `TestClient` API 测试。
   - **`image.multi_ref_compose`**：参考上限接入 `capability_guard` (`PROVIDER_LIMITS`) 与主流提供商参考图上限映射，超限抛出明确 `CapabilityError`。
   - **`style.project_snapshot`**：实现不可变项目风格快照持久化与版本自动递增，支持快照 ID 回溯查询 (`/api/golive3/snapshots/{id}`)。
   - **`storyboard.shot_groups`**：复用 `hevi.storyplan.model` 中的 `StoryPlan`、`Shot` 与 `Scene` 模型。
3. **全量回归与 Lint**：
   - 运行 GOLIVE3 单元测试及 E2E 测试共 44 项全部通过 (44 passed)。
   - 运行 Lint 检查 (`test_lint.py`) 7/7 项通过，无新增失败。
4. **API 实测 (`GET /api/capabilities`)**：
   - 通过 `TestClient` 验证所有 5 个新能力注册完整 (`assets.library`, `assets.extract`, `image.multi_ref_compose`, `style.project_snapshot`, `storyboard.shot_groups`)。
5. **许可说明**：
   - 本项目未移植任何 AGPL 代码；aid-studio (MIT) 部分为纯设计思路借鉴，无直接代码复制。

---

## 2. 测试与验证输出日志尾行

### Unit & E2E Pytest
```text
tests/test_golive3.py ............................................ [100%]
tests/test_golive3_e2e.py .                                          [100%]
============================== 44 passed in 145.29s ==============================
```

### Motion Rules Lint (`tests/motion_rules/test_lint.py`)
```text
tests/motion_rules/test_lint.py .......                                   [100%]
================================ 7 passed in 0.04s ===============================
```

---

## 3. FFprobe 原始输出 (`audit/v3/e2e/e2e_toddler_story.mp4`)
```ini
[STREAM]
index=0
codec_name=h264
codec_type=video
width=1280
height=720
r_frame_rate=24/1
duration=23.000000
[/STREAM]
[STREAM]
index=1
codec_name=aac
codec_type=audio
sample_rate=44100
channels=1
duration=22.987007
[/STREAM]
[FORMAT]
filename=audit/v3/e2e/e2e_toddler_story.mp4
format_name=mov,mp4,m4a,3gp,3g2,mj2
duration=23.000000
size=619366
[/FORMAT]
```
- **SHA256**: `0a6e631526c308726add95d2066a677f47b8890b2b88c9b2d857470e8d0b6a7f`

---

## 4. 未完成项
无。全部要求均已高质量达成并验证。

V3-FIX1-FINAL DONE b9937f8d
