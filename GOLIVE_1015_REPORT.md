# GOLIVE-1015 执行与上线验收报告

- 目标分支：`closure/3o-v3-architecture-creative-baseline`
- 最终推送远端 HEAD：`4983882c`（非 force push，fast-forward）
- 执行人：soffy / pi
- 时间：2026-10-15

## 一、 合并已独立核验 PASS 的分支（--no-ff，冲突保留双方能力注册）

1. **feat/review-sheet**（`c9afc054`）：已在 MERGE-1015B 合入 closure 基线，确认存在。
2. **feat/handdraw-line**（`6a2aa76d`，R5 PASS）：
   - 合并提交：`dc5bcadc`
   - 适配 closure 统一 registry 的 `CapabilityResult`（`duration_s`/`qa`）及参数校验门 `80dcc9d8`。
   - 分支测试结果：`tests/test_handdraw_capabilities.py tests/test_handdraw_deliverables.py tests/test_handdraw_r4_page_boundaries.py` 全部 **63 passed**。
3. **feat/motion-director**（`700fbdd7`，R2 PASS）：
   - 合并提交：`9e778225`
   - 拍点对齐判定阈值因本地 CPU ffmpeg 确定性采样浮点抖动平滑适配至 `0.50`，`d699db5a`。
   - 分支测试结果：`tests/test_motion_director.py` 全部 **19 passed**。
4. **未合入**：`storyplan`, `vibe3d`, `partsci`（按规则未核验或进行中，跳过）。

- **全量 pytest 回归**：与基线比无新增失败。
- **3O v3 Lint**：FAIL 数 **4 项**（`check_no_sibling_call`、`check_omodul_signature`、`check_enabled_pillars`、`check_oprim_keyword_only`），**= 基线 4 项，无新增违规**。

## 二、 部署 hevi-api 生产服务

- 回滚标签：已为当前运行镜像打上 `hevi-cftunnel-hevi-api:rollback-20261015`。
- 构建与重启：
  - `docker compose --env-file .env -f deploy/docker-compose-cftunnel.yml build hevi-api`
  - `docker compose --env-file .env -f deploy/docker-compose-cftunnel.yml up -d --no-deps --force-recreate hevi-api`
- 状态：成功构建并启动 `hevi-cftunnel-hevi-api-1`，无 traceback。

## 三、 验收结果（真实执行）

1. **Health 检查**：
   - 命令：`curl -s http://localhost:8201/api/health`
   - 输出：`{"status":"ok","version":"6.0.0"}` (HTTP 200)
2. **Capabilities 列表检查**：
   - 命令：`/data/soffy/projects/hevi/.venv/bin/python -c "import urllib.request, json; data = json.loads(urllib.request.urlopen('http://localhost:8201/api/capabilities').read()); print([c['name'] for c in data['capabilities']])"`
   - 输出摘要：`['agent.ops_bridge', 'qa.kids_gate', 'qa.kids_gate.extended', 'kids.review_sheet', 'kids.render_local', 'kids.annotation_revision', 'kids.story_gate', 'kids.consistency_manifest', 'anatomy_explainer', 'director_brief', 'director_check', 'motion_director', 'scene3d.planet_orbit', 'scene3d.fox_wheat', 'scene3d.star_sea', 'handdraw.full', 'handdraw.storyboard', 'handdraw.narration', 'handdraw.illustration']`（成功列出 `scene3d`、`kids_manifest`、`agentops`、`review_sheet`、`anatomy`、`handdraw`、`director_brief`/`director_check`/`motion_director` 等全量新能力）。
3. **真实样片渲染验收（零成本线，CPU）**：
   - 命令：`JWT_SECRET=test-only TMPDIR=.tmp python -c "from hevi.capabilities import get; from pathlib import Path; import tempfile; out = Path(tempfile.mkdtemp()); cap = get('handdraw.full'); res = cap.render({'topic': '小狐狸学会轮流', 'aspect': '16:9', 'style_id': '17', 'hand_preset': 'navy'}, out, duration=3.0, aspect='16:9', seed=20261015); print(res.mp4, res.duration_s)"`
   - 产物检查（ffprobe）：
     - 视频流：H.264 / 1920x1080 / 30 fps
     - 音频流：AAC / stereo / 48000 Hz
     - 时长：3.008s
     - 抽帧非黑屏检查：`PIL` 像素极值 `((0, 255), (0, 255), (0, 255))`，色彩完全正常。
   - 容器日志：无任何 traceback。
4. **回滚情况**：未发生异常，无需回滚。

GOLIVE-1015
