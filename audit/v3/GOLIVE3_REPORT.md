# HEVI-V3 GOLIVE3 验收报告 (GoLive 3 Aid-Studio Gaps)

## 1. 概述与完成功能
参考 aid-studio 设计思路，在 HEVI-V3 架构中实现了 5 项核心能力并接入统一能力注册表（`hevi.capabilities`），可通过 `GET /api/capabilities` 查看：
1. **`assets.library`**：项目内可复用资产库（角色、场景、道具 CRUD，含参考图、描述、绑定音色）。
2. **`assets.extract`**：从剧本自动抽取角色、场景与道具（离线规则、确定性，不调用付费 API）。
3. **`image.multi_ref_compose`**：多参考图融合（占位符解析如 `@角色名`，根据 `capability_guard` / 模型能力上限校验与明确报错，CPU PIL 拼版预览）。
4. **`style.project_snapshot`**：项目级风格快照（生成不可变版本快照 ID，支持版本回溯与旧快照不变性）。
5. **`storyboard.shot_groups`**：分镜镜头组拆分（按场景/时长把镜头拆成镜头组，生成视频提示词与首尾帧约束）。

## 2. Commit 记录
- Commit: `ec0af485` (feat(golive3): implement 5 aid-studio gap capabilities with comprehensive tests and e2e verification)

## 3. 测试验证与原始输出
- 测试文件：
  - `tests/test_golive3.py` (包含 40 个单元测试，每块至少 8 个测试，覆盖边界与失败用例：超参考图上限报错、改风格快照 ID 变化且旧快照不变、剧本抽取确定性等)
  - `tests/test_golive3_e2e.py` (端到端集成测试：3场景剧本 → 抽资产 → 锁风格快照 → 拆镜头组 → 多参考图合成预览 → 渲染 ≥20 秒视频并经 ffprobe 验证时长)
- 测试命令：`JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=. python -m pytest -q -p no:randomly tests/test_golive3.py tests/test_golive3_e2e.py tests/test_capabilities_api.py`
- 原始输出尾行：`44 passed, 1 warning in 2.60s`

## 4. 未完成项
无（全部范围、测试及端到端验收要求均已达成）。

V3
