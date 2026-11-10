# S28 剧本层（scriptcraft）

出图/出视频前，把剧本问题在文字阶段解决。改字不要钱，改视频要抽卡。

## 入口

- API：`/api/studio/scriptcraft/*`
  - `POST /premise`：立项四槽 + 6 问 + 连续短剧/短片建议；不完整时返回 3 个换题备选。
  - `POST /characters`：小传/关系/弧光/缺陷/1–3 视觉标记 + cast card；姓名黑名单。
  - `POST /causality`：相邻事件只靠「然后」报警，要求「但是/所以」链。
  - `POST /filmability`：只写可拍动作；台词 said/inner/vo；姿态状态机；4–5 字/秒；道具尺寸；同框人数。
  - `POST /short-drama/plan`：故事总盘 → 确认闸门 → 10 集大纲 → 第 1 集秒级节拍 → 剧本 → 审稿。
  - `POST /short-film/plan`：开发句 → 三层主角 → 戏剧游戏 → 7 步 → 2–3 次反转 → 母题 ×3 → 分场/剧本 → 审稿。
  - `POST /review`、`POST /review/apply`：三轮审稿；默认不改稿，只应用勾选项。
- Studio 工具：`script.short_drama_plan`、`script.short_film_plan`、`script.doctor`。
- 页面：`/script-doctor`（只做文字，不调用付费模型）。

## 文档形状

剧本沿用 `hevi.ai_drama` 的 JSON 契约：`characters` / `scenes[].beats[].action` / `dialogue.kind`
（`said` / `inner` / `vo`）。`speaker` 存角色 id，`speaker_name` 仅供阅读。这样同一份剧本
可以直接进入 `compile_storyboard`、分镜规则和 ai_drama 产线。

## 门槛

- 短剧/短片都属于 `ai_drama` 质量门，未达 ≥4 不对外；本层只加剧本节点，不改变 drama 对外门槛。
- `live_drama` 与 `comic_drama` 新增「短片（5–8 分钟）」子选项，`gated=True`。

## 计费文案

RunningHub 自 2026-11-05 起由 RH 币改为积分。成本账本只显示「积分；以平台页面为准
（本系统只做计划估算，不换算、不充值）」，不调用、不充值。

## 验证

```bash
JWT_SECRET=dummy PYTHONPATH=. python -m pytest tests/test_s28_scriptcraft.py -q
JWT_SECRET=dummy PYTHONPATH=. python scripts/s28_blackbox.py
```

黑盒产物在 `/data/soffy/projects/seq-1108/verify_s28/`。
