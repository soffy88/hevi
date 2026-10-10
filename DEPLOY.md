# Hevi 部署（唯一方式，2026-10-11 整合后）

ubuntu26 上 Hevi 只保留三组容器，其它 compose 文件都是历史遗留，**不要再用来起新副本**。

| 组 | compose | 内容 | 端口 |
|---|---|---|---|
| 数据层 `hevi-vault` | `docker-compose.yml` | pgvector pg17、MinIO | 5441、9000/9001 |
| 应用 `hevi-cftunnel` | `deploy/docker-compose-cftunnel.yml`（只起 `hevi-api`、`hevi-web`） | API、Web | 8201、3200 |
| AI 引擎 `gen_engine` | `services/gen_engine/docker-compose.yml` + `docker-compose.cpu.yml` | CosyVoice 等 | 127.0.0.1:17600 |

线上入口：hevi.kanpan.co → aegis-cloudflared → aegis-caddy :8088 → `/api/*` 到 8201，其余到 3200。

## 更新 API
```
cd /data/soffy/projects/hevi
docker compose --env-file /root/hevi-cftunnel.env --env-file .env \
  -f deploy/docker-compose-cftunnel.yml build hevi-api
docker compose --env-file /root/hevi-cftunnel.env --env-file .env \
  -f deploy/docker-compose-cftunnel.yml up -d --no-deps --force-recreate hevi-api
```
- 一定要带 `--no-deps hevi-api`：这个 compose 里还有一个旧的 `hevi-gen-engine` 服务，引擎由 `services/gen_engine` 单独管理。
- `/root/hevi-cftunnel.env`（权限 600）放 CFTUNNEL_DATABASE_URL 等容器内地址；`.env` 放其余配置。
- APP_ENV=production 下弱密码会拒绝启动；数据库和 MinIO 凭据已在 2026-10-11 换成强密码（旧 `.env` 备份为 `.env.bak-20261011`）。

## 已废弃
`hevi/deploy/docker-compose-{dev,live,prod}.yml`、`docker-compose-release-overlay.yml`、手动 `docker run` 的 `hevi-vnext-*`。
2026-10-11 下线前的数据备份在 `/data/soffy/backups/hevi-20261011/`。
