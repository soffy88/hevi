# Hevi 部署（唯一方式，2026-10-11 整合后）

ubuntu26 上 Hevi 只保留三组容器，其它 compose 文件都是历史遗留，**不要再用来起新副本**。

| 组 | compose | 内容 | 端口 |
|---|---|---|---|
| 数据层 `hevi-vault` | `docker-compose.yml` | pgvector pg17、MinIO | 5441、9000/9001 |
| 应用 `hevi-cftunnel` | `deploy/docker-compose-cftunnel.yml`（只起 `hevi-api`、`hevi-web`） | API、Web | 8201、3200 |
| AI 引擎 `gen_engine` | `services/gen_engine/docker-compose.yml` + `docker-compose.cpu.yml` | CosyVoice 等 | 127.0.0.1:17600 |

线上入口：hevi.kanpan.co → aegis-cloudflared → aegis-caddy :8088 → `/api/*` 到 8201，其余到 3200。

## 更新 API / Web（S8 起：固定发布 worktree）

生产镜像**只从固定发布 worktree `/data/soffy/projects/hevi-release` 构建**，
它固定跟随 `main`。不要在主仓库 `/data/soffy/projects/hevi` 直接构建——那个工作树
可能被切到别的分支（2026-11-07 曾长期停在 closure 分支，是事故隐患）。

```bash
# 0) 让发布 worktree 与 main 一致（main 只作为提交源，不直接构建）
git -C /data/soffy/projects/hevi-release fetch origin
git -C /data/soffy/projects/hevi-release checkout --detach main

# 1) 强制校验 + 构建 + 切换（脚本拒绝脏工作树 / HEAD != main）
deploy/ops/hevi-deploy api          # api/worker/scheduler
deploy/ops/hevi-deploy web          # web
deploy/ops/hevi-deploy all
deploy/ops/hevi-deploy --check      # 只校验构建源
```

`hevi-deploy` 内部就是：
```
HEVI_RELEASE_ROOT=/data/soffy/projects/hevi-release
docker compose --env-file /root/hevi-cftunnel.env --env-file /data/soffy/projects/hevi/.env \
  -f $HEVI_RELEASE_ROOT/deploy/docker-compose-cftunnel.yml build hevi-api
docker compose ... up -d --no-deps --force-recreate hevi-api hevi-worker hevi-scheduler
```
- compose 的 `hevi-api`/`hevi-web` 构建 context 走 `HEVI_RELEASE_ROOT`（默认仍是 `..`，仅本地开发用）。
- 发布 worktree 初始化（两者都在 gitignore，不影响 status）：
  `ln -sfn /data/soffy/projects/hevi/.env /data/soffy/projects/hevi-release/.env`
  `sudo cp -al /data/soffy/projects/hevi/.venv /data/soffy/projects/hevi-release/.venv`
  （`Dockerfile.api` 会把宿主 `.venv` 打进镜像；硬链接复制不额外占盘。缺任一项 `hevi-deploy` 会拒绝构建。）
- 一定要带 `--no-deps`：这个 compose 里还有一个旧的 `hevi-gen-engine` 服务，引擎由 `services/gen_engine` 单独管理。
- `/root/hevi-cftunnel.env`（权限 600）放 CFTUNNEL_DATABASE_URL 等容器内地址；`.env` 放其余配置。
- APP_ENV=production 下弱密码会拒绝启动；数据库和 MinIO 凭据已在 2026-10-11 换成强密码（旧 `.env` 备份为 `.env.bak-20261011`）。
- 发布 worktree 的 `main` 由提交方推送 `origin/main` 后再 `fetch`；**不接受从脏工作树构建**。


## main 与 worktree 规则（S26 起）

- `main` 只作为提交源，指向 `origin/main`；**不要求**在主仓库工作树里 checkout。
  主仓库 `/data/soffy/projects/hevi` 常年 detached，另一些 worktree 可能占用分支。
- 发布前校验：`git -C /data/soffy/projects/hevi fetch origin &&
  test "$(git -C /data/soffy/projects/hevi rev-parse main)" = "$(git -C /data/soffy/projects/hevi rev-parse origin/main)"`。
- 旧 worktree `/data/soffy/wt/hevi-merge-atlas` 有未提交改动，已原样保留，分支改名为
  `archive/main-stale-20261111`（staged/unstaged patch 存
  `/data/soffy/projects/seq-1108/verify_s26/main_stale_*.patch`）。
- 新的功能分支从 `origin/main` 起；合并顺序：分支 → `main`（fast-forward）→ `origin/main` → 发布 worktree fetch。

## 可选音色包（S30）

anidoodle 的录制音色包是一个 **374 MB 的独立下载**，不进 git、不进镜像，宿主机装好后
只读挂载进容器；不挂载时所有作曲模板自动回退纯代码乐器，不会阻塞渲染。

```bash
# 安装（一次；官方工具会校验每个 FLAC 的 sha256）
cd /data/soffy/projects/hevi/third_party/anidoodle/engine
node tools/soundfetch.mjs get all --out /data/soffy/projects/anidoodle-sounds
node -e "const m=require('/data/soffy/projects/anidoodle-sounds/manifest.json');console.log(Object.keys(m.instruments),Object.keys(m.rooms))"

# 宿主直接核验（467 个文件；也可 GET /api/anidoodle/sounds?verify=true）
.venv/bin/python -c "from hevi.anidoodle import soundpack; print(soundpack.pack_status(verify=True)['verify'])"
```

- 挂载：`deploy/docker-compose-cftunnel.yml` 给 `hevi-api` / `hevi-worker` /
  `hevi-render-worker` 加了 `- /data/soffy/projects/anidoodle-sounds:/anidoodle-sounds:ro`，
  并设 `ANIDOODLE_SOUNDS` / `HEVI_ANIDOODLE_SOUNDS=/anidoodle-sounds`。
  容器内路径 `/anidoodle-sounds`，只读。
- 许可：8 个乐器全部 **VCSL CC0 1.0**（公有领域，可商用、可再分发，无需署名）；
  3 个 room 为 **OpenAIR / University of York CC BY 4.0**（可商用，发布时需署名，
  署名文本见 `NOTICE` 与 `hevi.anidoodle.soundpack.CREDIT`）。包内没有非商用或
  禁止再分发的条目；`/api/anidoodle/sounds` 的 `withheld` 列表为空，非 CC0 的
  乐器会被列出且永不出声。
- 回退：`sound=auto`（默认）逐槽位用包、缺哪个槽位就退回该槽位的代码乐器；
  `sound=code` 完全复现 S29 纯代码编排；`sound=pack` 要求用包并在结果里报告回退原因。
  响应里的 `sound.recordings / modeled / fallback_reason` 写明实际用了什么。
- 资源：解码后的包按 1 个 worker（`ANIDOODLE_THREADS=1`）控制在约 1–2 GB；
  4 worker 曾把宿主吃到 7 GB 并抖动（2026-11-11 实测）。

## 已废弃
`hevi/deploy/docker-compose-{dev,live,prod}.yml`、`docker-compose-release-overlay.yml`、手动 `docker run` 的 `hevi-vnext-*`。
2026-10-11 下线前的数据备份在 `/data/soffy/backups/hevi-20261011/`。

## 运维（宿主，2026-11-08 S6）

- **每日备份**：systemd `hevi-backup.timer`，`04:00 Asia/Shanghai`，`pg_dump -Fc` 到
  `/data/soffy/backups/hevi-daily/`，保留 7 份；恢复演练 `hevi-restore-drill`。
- **健康告警**：systemd `hevi-healthcheck.timer` 每 5 分钟检查首页/`/api/health`/
  容器 healthy/`/data` 可用空间（<15G）；失败写 `/var/log/hevi-alert.log` 与
  `/data/soffy/projects/hevi-alerts/ALERTS.md`。Webhook 预留（`/etc/hevi-alert.env`，
  默认关闭）。S8 起同一故障集合 1 小时内只告警一次，恢复时发一次恢复通知（状态文件
  `/data/soffy/projects/hevi-alerts/.healthcheck-state`，窗口 `HEVI_ALERT_DEDUPE_S`）。
- 脚本与安装步骤：`deploy/ops/README.md`。
- `hevi-web` 由本 compose 的 `hevi-web` 服务托管（`3200:3000`，node HTTP 探活）。
