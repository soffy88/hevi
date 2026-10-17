# HEVI-V3 修复轮 1（GOLIVE3_FIX1，worker brief）

先读 GOLIVE3_TASK.md（原任务书，规则全部继续有效）。上一轮提交 ec0af485/1444ecbd 经独立核验 **不通过**，原因如下，逐条修复：

1. 端到端是假的：tests/test_golive3_e2e.py 第 7 步用 ffmpeg lavfi 渲染纯蓝色块+静音冒充成片。必须改为：用仓库里已有的本地渲染管线（先找 hevi/video/local_fallback.py、wan_local_service.py、kernel_service.py、hevi/canvas、hevi/storyplan 等现有本地 CPU 渲染/合成路径）把 3 场景幼儿剧本 → 资产 → 风格快照 → 镜头组 → 多参考图合成预览图 作为输入，真正渲染出 ≥20 秒的幼儿片（画面须来自合成预览/镜头组内容，带音轨），产物落到 audit/v3/e2e/ 下（mp4 不要 git add 大文件，>20MB 只记路径和 sha256），ffprobe 验时长 ≥20 秒，并把 ffprobe 原始输出贴进报告。
2. 实现过薄，没有复用原任务书点名的模块：全部塞在 hevi/capabilities/golive3.py 一个文件里。要求：
   - assets.extract 复用 hevi/creative/layer4 的 importer 逻辑（或明确说明为什么不能复用）；资产库与 hevi/subjects（reference_store/subject_service）打通，参考图走 reference_store。
   - 资产库要有真实持久化（项目内存储，重启后可读）和 HTTP CRUD API（挂到现有 FastAPI 路由，例如 /api/projects/{id}/assets），并有 API 级测试（TestClient）。
   - image.multi_ref_compose 的上限取自 capability_guard 的真实接口而不是自己复制常量；超限报明确错误。
   - style.project_snapshot 快照 id 要被后续生成（镜头组/合成预览）记录并可回溯查询；有对应 API 或能力入口。
   - storyboard.shot_groups 复用 hevi/storyplan / director_lens 现有分镜结构。
3. 全量回归：在本 worktree 跑 `JWT_SECRET=test-only TMPDIR=.tmp PYTHONPATH=. /data/soffy/projects/hevi/.venv/bin/python -m pytest -q -p no:randomly tests/`（建议 `systemd-run --user --scope -p MemoryMax=6G` 包裹），与基线 e4d0ce61 对比，列出失败清单，证明无新增失败；跑 3O lint，失败数 ≤4，贴原始尾行。
4. GET /api/capabilities 用 TestClient 实测能看到 assets.library / assets.extract / image.multi_ref_compose / style.project_snapshot / storyboard.shot_groups，贴原始输出。
5. 许可：确认未复制任何 AGPL 代码；如移植了 aid-studio（MIT）任何片段，在 NOTICE 注明出处与 MIT 许可；没有移植就在报告里明确写“未移植代码”。

## 报告
写 audit/v3/GOLIVE3_FIX1_REPORT.md：每条修复做了什么、commit、测试名与原始输出尾行、全量回归对比、lint 尾行、ffprobe 原始输出、未完成项。
最后一行严格写 `V3-FIX1-FINAL DONE <commit>` 或 `V3-FIX1-FINAL BLOCKED <原因>` 并 commit。不 push、不合并、不部署。
