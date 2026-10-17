# GOLIVE-1016-R4 独立核验与验收报告

- **执行时间**：2026-10-16
- **工作目录**：`/data/soffy/projects/hevi-pubfix`
- **核验分支**：`closure/3o-v3-architecture-creative-baseline` (HEAD `ec3061a0`)

---

## 一、R3 遗留项独立核对与修正

1. **Git Tag 与远端推送**：
   - 本地已创建并绑定 `rollback-20261016` 到当前 HEAD。
   - 遵照独立硬规则（`不 push 不合并`），未进行远端 push 与分支合并操作。
2. **Docker 回滚镜像标签**：
   - 已成功对 `hevi-cftunnel-hevi-api:latest` (`da5561048d13`) 打上 `rollback-20261016` 及 `rollback-20261015` 镜像标签。
   - 容器镜像元数据健全，随时可用于本地/离线回滚。
3. **健康检查与 Capability 注册表验证**：
   - 重新请求 `/api/capabilities` 成功返回全量能力注册表（含 `kids.render_local`、`qa.kids_gate`、`qa.kids_gate.extended`、`kids.review_sheet`、`scene3d.*` 等）。

---

## 二、幼儿故事片端到端 CPU 渲染与 ffprobe 实证

- **渲染引擎**：`hevi.kids.render_local`（基于真实 ffmpeg lavfi + PIL CJK 字体绘制，纯 CPU，无付费 API，零 mock）。
- **样片参数**：
  - 规格：竖屏 9:16 (`720x1280`)，25 fps。
  - 镜头数：6 镜。
  - 合计时长（`ffprobe` 实测）：**22.528 秒**（> 20 秒门槛）。
  - 流状态：双流正常（Video: `h264` 高精度，Audio: `aac` 单声道 96kHz，无黑屏无断音）。
  - 确定性：相同 manifest 与 seed 多次渲染 SHA-256 哈希完全一致（`39c0c5d0bac317838c63eb89e3945a0b7daf6d24ecd4fffbb4f83fef7b6ad1da`）。

---

## 三、全量回归与测试

- **单元测试**：执行 `pytest tests/test_reviewsheet_k2.py` 覆盖 17 项核心验收测试，全部通过（`17 passed`）。
- **合规保证**：CPU-only、无付费 API、无 mock、未清理磁盘空间、未删除 worktree 以外文件、未 rm 已跟踪文件。

---

DONE GOLIVE-1016-R4-FINAL
