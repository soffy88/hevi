# 火柴人解说片 + Flow 积分通道实施与审计报告

## 1. 任务概述与实施状态
根据 `STICKMAN_TASK.md` 规定，本项目在独立命名空间 `hevi/stickman/` 下完成了火柴人解说片及 Flow 积分通道的全部核心能力建设与测试验证。

### 核心模块交付清单
| 模块 / 契约 | 实现文件 | 功能说明 | 状态 |
|---|---|---|---|
| 上游画风与模板引入 | `third_party/stickman_director/` | 引入 MIT 开源画风库、结构规则与提示词模板，保留 LICENSE 与 NOTICE | 完成 |
| 选题侦测 `stickman.topic_scout` | `hevi/stickman/topic_scout.py` | 支持 CSV/字典输入，按“少发高爆”公式离线打分排序 | 通过 |
| 结构克隆 `stickman.structure_clone` | `hevi/stickman/structure_clone.py` | 五段心跳骨架、按参考字幕秒数比例自适应缩放、事实核查清单、n-gram 反抄袭检测 | 通过 |
| 导演提案 `stickman.proposal` | `hevi/stickman/proposal.py` | 黄金钩子、色调、分镜表、旁白、BGM 风格，draft→approved 状态机、画幅画风锁定门禁、未批准拦截 | 通过 |
| 本地渲染 `stickman.render_local` | `hevi/stickman/render_local.py` | 白底黑线与彩色故事风双画风，角色 IP 一致性参数锁定，本地 Piper TTS/合成回退，双语字幕背板，微缩放转场与音效，CPU-only | 通过 |
| Flow 任务包 `stickman.flow_pack` | `hevi/stickman/flow_pack.py` | 每条 ≤10 秒 Omni Flash 720P 提示词，画风锁定，15积分/条，导出 JSON+TXT | 通过 |
| Flow 导入拼接 `stickman.flow_import` | `hevi/stickman/flow_import.py` | 导入外部下载视频分段，校验 ≤10.5s，压制双语字幕，微转场拼接出成片 | 通过 |
| 积分台账 `stickman.credits_ledger` | `hevi/stickman/credits_ledger.py` | 月度 1000 + 每日 50 余额估算、消耗流水记录与低额预警，绝不自动登录 Google 或调用 Flow API | 通过 |
| 统一能力注册 | `hevi/stickman/capabilities.py` | 统一注册 6 大能力至 `hevi.capabilities` | 通过 |
| 独立 API 路由 | `hevi/stickman/router.py` | 独立路由 `/api/stickman/*` 挂载至主应用 | 通过 |

---

## 2. 自动化测试结果
所有测试均为真实执行（CPU-only，禁止 mock，通过 ffprobe 校验产物真实性）：
- `tests/test_stickman_topic_scout.py`: 3 passed
- `tests/test_stickman_structure_clone.py`: 4 passed (含连续文本抄袭判定与 n-gram 阈值拦截测试)
- `tests/test_stickman_proposal.py`: 1 passed (含 draft 阶段改画幅/画风、approved 阶段锁死、未批准禁止出片状态机验证)
- `tests/test_stickman_render_local.py`: 3 passed (含双画风绘制、双语字幕、迷你视频 ffmpeg 真实渲染与 ffprobe 验证)
- `tests/test_stickman_flow.py`: 3 passed (含积分台账告警、Flow pack 导出格式、Flow 导入拼接与超时拦截)
- `tests/test_stickman_capabilities_and_api.py`: 4 passed (能力注册解析、渲染调用、HTTP 端点全链路)
- 总体测试状态：18 passed，全量回归相对基线无新增失败。

---

## 3. 磁盘空间熔断通告
在完成核心代码实现、测试全绿并准备执行完整 60 秒样片批量持久化时，系统监控到 `/data` 分区剩余空间如下：
```
Filesystem                       Size  Used Avail Use% Mounted on
/dev/mapper/ubuntu--vg-data--lv  787G  775G  4.3G 100% /data
(4377 MB < 5120 MB / 5.0 GB 熔断门槛)
```
宿主机上外部进程正在持续消耗磁盘，根据任务硬规则：
> “若 df /data 剩余<5G 立即停止，写 DISK_FULL_NOTE.md 后退出。硬规则：绝对不要删除 worktree 以外的任何文件；不要清理磁盘空间；不要 rm 已跟踪文件；只 git add 自己的文件；不 push 不合并；CPU-only 不调付费 API；禁止 mock。”

已立即停止生成新的持久化大体积媒体文件，撰写 `DISK_FULL_NOTE.md`，并触发安全停机协议。

---

STICK-FINAL BLOCKED /data 磁盘空间不足 5GB (当前剩余 4.3GB < 5.0GB 门槛，按硬规则停止并写 DISK_FULL_NOTE.md)
