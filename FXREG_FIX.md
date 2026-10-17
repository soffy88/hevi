# FXREG_FIX — 独立核验不通过（第 1 轮返工，2026-10-13 15:45 CST）

核验对象：feat/fx-registry @ 6548ade3（DONE FXREG-R1）。已确认合格、**不要破坏**的部分：注册表 171 条（talkcraft 108 = tplMeta.ts 实际条目数（7 类合计 22+27+14+14+13+10+8=108，任务里写的 109 是笔误）、xfade 58、sfx 5），id 唯一、category 合法；真实 app 上 API 列表/过滤/详情/404/400/preview/thumbnail 都正常；41 个测试真实通过；lint 仍是基线 4 项；xfade 预览抽帧看确实是各不相同的真实转场；talkcraft 预览是真实的卡片动画。

## 必须修的问题

1. **sfx 缩略图是 4 张完全相同的纯黑图（占位级缺陷）**：`sfx__ding/impact/pop/whoosh.jpg` 的 sha256 都是 `821ae959…`，1354 字节，画面全黑。sfx 预览 mp4 用滚动 `showwaves`，声音一结束后面就全黑（ding/impact/pop 在 2s 里大部分时间是黑屏），缩略图恰好取在黑帧上。
   - 修法：sfx 预览改成整段静态波形（`showwavespic` 或等价方式，整段 2s 一直可见）+ 随时间移动的播放头/进度条，或其它在整个 2s 内都可见且每条各不相同的画面；缩略图取完整波形图。
   - 验收：5 张 sfx 缩略图 sha256 两两不同，且都不是纯色（像素标准差 >5）；每个 sfx mp4 抽 6 帧，没有一帧是纯黑。

2. **"非静帧"阈值用错量纲，实际等于没检查**：`DIFF_MIN=0.01` 是拿 0–255 刻度的 YAVG 去比，相当于只要求"不是逐位完全相同"。按 0–1 归一化后，166 条成功预览里有 146 条 <0.01（index.json 自己的 `below_strict_diff_norm: 146`）。
   - 修法：换一个有意义的运动指标，并写进文档和测试，例如：对**前景区域**（talkcraft 是居中的 960x540 舞台缩放区，不是整张模糊背景）算 ①首尾帧差，或 ②最大相邻帧差/运动帧占比，并给出可解释的阈值（例如归一化前景帧差 >0.01，或运动帧占比 ≥10%）。index.json 记录新指标。
   - 测试里按新指标断言，不能只断言 `>0.01（0–255 刻度）`。

3. **5 张 talkcraft 卡判成失败，很可能是取帧窗口不对，不是"天然低运动"**：hand-drawn-ellipse / scribble-annotation / converging-arrows / ink-underline / strike-and-replace 的原生时长有 2.97–3.63s，但预览只截前 60 帧；画线动作可能发生在 2s 之后，或者被整屏模糊背景稀释了。
   - 修法：对长于 2s 的卡，选运动最大的 2s 窗口（逐帧算前景差后滑窗取最大值），或把整卡等比加速压到 2s（二选一，写进文档）。重新渲这 5 张，并用同样规则重渲所有 talkcraft 卡。
   - 验收：这 5 张要么成功（抽帧能看到画线过程），要么在 index.json 里写出带数据的具体原因；失败数如实统计。

4. **未知分类被悄悄丢掉**：`sources/talkcraft.py` 遇到 `_CATEGORY_MAP` 里没有的中文分类直接 `continue`，没有日志也没有计数（实测在临时 ts 里塞一个"未知类"条目，结果被静默丢弃）。
   - 修法：记 `logger.warning`，并把被跳过的 id 暴露出来（例如 `load_talkcraft` 返回或记录 skipped 列表 / loader 汇总里加 `skipped`）；加测试：未知分类会告警且不进表，已知分类正常进表；tplMeta 缺失或格式坏时也要有明确报错测试。

5. （建议，顺手做）talkcraft 预览的前景只有 540x304，竖屏画面大部分是模糊背景，缩略图看不清。可以把前景放大到宽度占满后适当裁切，或改成 540x960 内前景占 ≥50% 面积；不强制，但做了更好。

## 返工要求
- 只改本 worktree；遵守 FXREG_TASK.md 和通用规则（不碰主 checkout、不删 worktree 外任何东西、不清理磁盘、不 push、不 merge，CPU-only，不调付费 API）。
- 重新批量渲染（nohup setsid 后台跑，并发 ≤2），重新生成 index.json 和 contact_sheet.png（每类 ≥4 张，含 sfx 缩略图），亲自查看。
- 注意：这个 worktree 的 `.venv` 是主 checkout 的 venv，在 worktree 外跑 python 时 `hevi` 会解析到主 checkout；跑脚本/核对时要设 `PYTHONPATH=<worktree>`（pytest 不受影响）。
- 跑 `JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/test_fx_registry.py -q` 全部通过，lint_after 仍只有基线 4 项。
- 更新 FXREG_DONE.md（新增"R2 返工"一节，逐条对照本 FIX 第 1–4 条写真实结果和数据），commit，并把文件最后一行改成 `DONE FXREG-R2`。
