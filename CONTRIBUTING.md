# hevi 开发纪律(铁律，源自 v1 aegis 灾难)

## 分支策略

- **不在 main 直接改**
- 每任务流程：
  ```
  git checkout -b feat/xxx
  # 干活
  git add <files>
  git commit -m "feat(scope): description"
  git push origin feat/xxx
  # advisor verify → merge main → push main → 删分支
  ```

## Push 纪律

- 任何一段工作结束先 `git status` 确认干净
- dirty tree 立即 commit + push，**不留过夜**
- working tree 过夜 = 定时炸弹（aegis 教训）

## 完成验证（L-025）

- CC 报"完成"必须附 `git log main --oneline | head -3` 真实 HEAD hash
- 文字"已完成已推送"不算数，hash 不会骗人

## 依赖管理（L-024）

- 主库用 git+ssh B路径显式 pin 到 tag
  ```
  obase[cache] @ git+ssh://git@github.com/helios-plat/obase.git@v0.12.1
  ```
- **不用浮动版本**（`>=` 仅用于第三方 PyPI 包）
- 主库升级：grep catalog 确认变更 → 更新 tag → reviewer sign-off

## CI / GitHub Actions

- `HELIOS_DEPLOY_KEY`：repo Settings → Secrets 配置 SSH deploy key（只读，访问 helios-plat 主库）
- CI 红线：ruff + mypy --strict + pytest --cov-fail-under=80

## 目录约定

```
hevi/
├── api/         # FastAPI routers
├── core/        # config, logging
├── db/          # ORM models + alembic migrations
├── providers/   # L2 内核 provider 注册中心
├── services/    # 业务逻辑
└── workers/     # 后台任务 (L1 agentic)
```
