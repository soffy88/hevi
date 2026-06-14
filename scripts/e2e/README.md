# E2E 真跑脚本执行指南

资源就位顺序和脚本执行步骤。

## 前提条件

```bash
# 1. 服务已启动 (dev 模式)
docker compose -f hevi/deploy/docker-compose-dev.yml up -d
uv run alembic upgrade head
uv run uvicorn hevi.api.main:app --reload &

# 2. .env 已填写
cp .env.example .env
# 编辑 .env,填写 FAL_API_KEY / MINIO_ACCESS_KEY / MINIO_SECRET_KEY
```

## 执行顺序

### Step 1 — 单元素真跑 (F1 最小闭环验证)

**资源**: FAL_API_KEY + PostgreSQL + MinIO

```bash
uv run python scripts/e2e/step1_single_element.py
```

**期望输出**:
```
[step1.1] ✓ 生成完成: shots=8 video_path='/tmp/hevi/out.mp4'
[step1.2] ✓ DB 记录: id=... status=completed
[step1.3] ✓ MinIO 证据: endpoint=localhost:9000 obj='out.mp4'
[step1] ✓ 单元素 E2E 完成
```

---

### Step 2 — 全链路真跑 (1-5min 完整视频)

**资源**: Step 1 全部 + hevi API 服务已启动

```bash
# 确认 API 健康
curl -s http://localhost:8000/api/health

uv run python scripts/e2e/step2_full_pipeline.py
```

**期望输出**:
```
[step2.1] ✓ task_id='...' status='pending'
[step2.2]   5% generating — 生成分镜...
[step2.2]  40% generating — 视频合成...
[step2.2] 100% completed
[step2.3] ✓ 产物验证: video_path='s3://hevi-assets/...'
[step2] ✓ 全链路 E2E 完成
```

---

### Step 4 — 断点续传验证

**资源**: Step 2 全部

```bash
# 可选: 设置中断点百分比 (默认 30%)
export INTERRUPT_AT_PCT=30

uv run python scripts/e2e/step4_resilience.py
```

**期望输出**:
```
[step4.1] ✓ 任务启动: task_id='...'
[step4.2]  30.0% — 到达 30%,模拟中断...
[step4.3] ✓ 恢复成功
[step4.4] 100% completed
[step4.4] ✓ 断点续传验证通过 — 产物完整
```

---

## 脚本行为说明

| 情况 | 行为 |
|------|------|
| env var 未设置 | 友好提示缺少哪个资源,`exit(1)` |
| API 未启动 | httpx `ConnectError`,提示检查服务 |
| 任务失败 | 打印 `❌` 并 `exit(1)` |
| 所有验证通过 | 打印 `✓` 并 `exit(0)` |

## 资源对照表

| 脚本 | FAL_API_KEY | DATABASE_URL | MinIO | API 服务 |
|------|:-----------:|:------------:|:-----:|:--------:|
| step1 | ✅ | ✅ | ✅ | ❌ |
| step2 | ✅ | ✅ | ✅ | ✅ |
| step4 | ✅ | ✅ | ✅ | ✅ |
