# hevi v6 — E2E 真跑配置指南

本文档说明如何将 hevi v6 从"零资源"状态升级到真实 E2E 可跑状态。  
脚本位置: `scripts/e2e/`。执行顺序参见 [scripts/e2e/README.md](../scripts/e2e/README.md)。

---

## 快速检查清单

```bash
# 确认 .env 已填写
grep -E "^(FAL_API_KEY|DATABASE_URL|MINIO_ACCESS_KEY|MINIO_SECRET_KEY)=" .env | \
  awk -F= '{print $1": "($2==""?"❌ 未填":"✓ 已填")}'

# 确认服务已启动
docker compose -f hevi/deploy/docker-compose-dev.yml ps

# 确认数据库 migration 已跑
uv run alembic upgrade head

# 确认 E2E 脚本解析正常
uv run python -c "
import ast, glob
[ast.parse(open(f).read()) for f in glob.glob('scripts/e2e/*.py')]
print('✓ E2E scripts parse OK')
"
```

---

## F1 最小闭环资源

### 1. fal.ai — LTX-2 视频生成

| 字段 | 说明 |
|------|------|
| `FAL_API_KEY` | fal.ai 控制台 → Account → API Keys |
| `FAL_PRICE_PER_SECOND` | fal.ai 定价页,LTX-2 当前约 $0.04/s |

```bash
# 验证 fal.ai key 有效
uv run python -c "
import os; from dotenv import load_dotenv; load_dotenv()
key = os.getenv('FAL_API_KEY','')
print('FAL_API_KEY:', key[:8]+'***' if key else '❌ 未设置')
"
```

### 2. PostgreSQL

```bash
# 启动 dev DB
docker compose -f hevi/deploy/docker-compose-dev.yml up -d postgres

# 跑 migration
uv run alembic upgrade head

# 验证表已创建
psql postgresql://hevi:hevi@localhost:5432/hevi -c "\dt"
```

### 3. MinIO

```bash
# 启动 MinIO + 自动建 bucket
docker compose -f hevi/deploy/docker-compose-dev.yml up -d minio minio-init

# 访问 Web Console: http://localhost:9001
# 默认账号: hevi / hevi1234 (dev only)
```

---

## F2 扩展资源

### DashScope (Wan 视频)

```bash
# 验证
uv run python -c "
import os; from dotenv import load_dotenv; load_dotenv()
key = os.getenv('DASHSCOPE_API_KEY','')
print('DASHSCOPE_API_KEY:', key[:8]+'***' if key else '❌ 未设置')
"
```

### VoiceBox TTS (本地模型)

```bash
# VIBEVOICE_MODEL_PATH 指向下载好的权重目录
export VIBEVOICE_MODEL_PATH=/opt/models/vibevoice-1.5b
ls $VIBEVOICE_MODEL_PATH   # 应看到 config.json, model.safetensors 等
```

### Duix Digital Avatar

```bash
# 启动 Duix Docker (参考 Duix 官方文档)
docker run -d -p 8088:8088 duix/avatar-service:latest
export DUIX_SERVICE_URL=http://localhost:8088
```

---

## 生产部署

### 域名 & HTTPS

1. 修改 `hevi/deploy/nginx/hevi.conf` 中的 `server_name`
2. 申请 Let's Encrypt 证书:
   ```bash
   # 参考 hevi/deploy/certbot/README.md
   ```
3. 启动 prod compose:
   ```bash
   docker compose -f hevi/deploy/docker-compose-prod.yml up -d
   ```

### 首次部署 migration

```bash
# 在 app 容器内跑 migration
docker compose -f hevi/deploy/docker-compose-prod.yml \
  exec app uv run alembic upgrade head
```

### systemd 部署 (裸机)

```bash
# 1. 安装到 /opt/hevi
cp -r . /opt/hevi && cp .env /opt/hevi/.env

# 2. 安装 systemd unit
cp hevi/deploy/systemd/hevi.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable hevi
systemctl start hevi
systemctl status hevi
```

---

## 备份

```bash
# 手动备份
bash hevi/deploy/backup/backup.sh /opt/hevi/backups

# 自动备份 (crontab)
echo "0 3 * * * bash /opt/hevi/hevi/deploy/backup/backup.sh" | crontab -
```

---

## E2E 脚本执行顺序

详见 [scripts/e2e/README.md](../scripts/e2e/README.md)。
