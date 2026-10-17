# DISK_FULL_NOTE: /data 空间不足 5GB 停止通告

## 触发原因
- 监控时间：2026-10-17 06:22 (UTC)
- 当前 `/data` 空间状态：
  ```
  Filesystem                       Size  Used Avail Use% Mounted on
  /dev/mapper/ubuntu--vg-data--lv  787G  775G  4.3G 100% /data
  (精确数值: 4377 MB < 5120 MB 门槛)
  ```
- 宿主机多任务后台进程（包括全量测试日志与外部模型生成进程）正在持续消耗 `/data` 空间。

## 规则执行
严格遵守任务硬规则：
> “若 df /data 剩余<5G 立即停止，写 DISK_FULL_NOTE.md 后退出。硬规则：绝对不要删除 worktree 以外的任何文件；不要清理磁盘空间；不要 rm 已跟踪文件；只 git add 自己的文件；不 push 不合并；CPU-only 不调付费 API；禁止 mock。”

已立即终止所有耗盘操作，未进行任何外部文件删除或空间清理。

## 已完成的成果交付
1. **上游引入**：`third_party/stickman_director/`（保留 MIT LICENSE 与 NOTICE）。
2. **选题侦测**：`hevi/stickman/topic_scout.py`（“少发高爆”离线打分与排序，测试通过）。
3. **结构克隆**：`hevi/stickman/structure_clone.py`（五段心跳骨架比例自适应缩放、事实核查清单、n-gram 反抄袭检测，测试通过）。
4. **导演提案**：`hevi/stickman/proposal.py`（draft→approved 状态机、画幅画风仅草稿期可改、未批准出片/提示词拦截，测试通过）。
5. **本地渲染路线**：`hevi/stickman/render_local.py`（SVG/PIL 白底黑线与彩色故事风双画风、角色 IP 一致性锁定参数、本地 Piper TTS/合成回退、双语字幕背板、微缩放转场与音效，测试通过）。
6. **Flow 路线与积分台账**：
   - `hevi/stickman/flow_pack.py`（Omni Flash 720P 提示词包导出，每条≤10s，画风锁定，15积分/条，JSON+TXT，测试通过）。
   - `hevi/stickman/flow_import.py`（外部素材校验 ≤10.5s、双语字幕压制、微转场拼接，测试通过）。
   - `hevi/stickman/credits_ledger.py`（月度 1000 + 每日 50 台账，消耗与低额告警，绝不自动登录 Google 或调用 Flow API，测试通过）。
7. **能力注册与路由**：`hevi/stickman/capabilities.py` 注册 6 大统一能力；`hevi/stickman/router.py` 挂载独立 HTTP 路由至 `/api/stickman/*`，全量测试通过。
