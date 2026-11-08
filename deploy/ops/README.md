# Hevi 上线运维脚本

宿主级（systemd）备份与健康告警。脚本只依赖 bash / curl / docker / systemd，
不需要应用容器内部权限。

## 安装

```bash
sudo install -m 755 deploy/ops/hevi-backup /usr/local/sbin/hevi-backup
sudo install -m 755 deploy/ops/hevi-restore-drill /usr/local/sbin/hevi-restore-drill
sudo install -m 755 deploy/ops/hevi-healthcheck /usr/local/sbin/hevi-healthcheck
sudo install -m 644 deploy/ops/hevi-alert.env.example /etc/hevi-alert.env
sudo install -m 644 deploy/ops/systemd/*.service deploy/ops/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hevi-backup.timer hevi-healthcheck.timer
systemctl list-timers --all | grep hevi
```

## 备份

- 每日 04:00 Asia/Shanghai（`hevi-backup.timer`，`OnCalendar=*-*-* 04:00:00 Asia/Shanghai`）。
- `pg_dump --format=custom --compress=9` 在 `hevi-vault-postgres-1` 容器内执行，
  输出到 `/data/soffy/backups/hevi-daily/hevi-<UTC>.dump`（含 sha256）。
- 保留最近 7 份；只删除本脚本命名的 `hevi-*.dump` 与其 `.sha256`。
- 日志：`/data/soffy/backups/hevi-daily/backup.log`。

恢复演练（临时库，校验后自动删除，绝不碰生产库）：

```bash
sudo /usr/local/sbin/hevi-restore-drill            # 最新一份
sudo /usr/local/sbin/hevi-restore-drill <dump>     # 指定一份
```

## 健康告警

- 每 5 分钟（`hevi-healthcheck.timer`，`OnCalendar=*:0/5`）。
- 检查：首页（307/200）、`/api/health` 200、api/worker/scheduler/web/redis
  容器 healthy、`/data` 可用空间 ≥ 15G。
- 失败时追加 `/var/log/hevi-alert.log` 与
  `/data/soffy/projects/hevi-alerts/ALERTS.md`，并以非零状态退出。
- Webhook 预留：`/etc/hevi-alert.env` 的 `HEVI_ALERT_WEBHOOK_URL`，
  **默认留空 = 关闭**，不配置任何外部地址。设置后以 JSON POST 失败详情。

配置项见 `hevi-alert.env.example`（全部支持环境变量覆盖，方便手工演练）。
