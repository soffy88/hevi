---
name: narrator-ai
version: "1.0.5"
description: >
  AI 电影/短剧解说视频（Narrator AI）。用户要做影视二创解说、电影解说、原声混剪时触发。
  Hevi 入口是 `python -m hevi.skills.narrator_cli`；底层仍是 narrator-ai-cli。
  Use when the user runs /narrator-ai or asks for movie narration / film commentary.
allowed-tools: Bash, Read
user-invocable: true
---

# /narrator-ai

影视二创解说走 **Narrator AI 商业 API**，不进 Hevi 导演管线。

## 先看状态

```bash
cd "$HEVI_ROOT" && uv run python -m hevi.skills.narrator_cli --status
```

返回 `cli=false` 或 `app_key=false` 时：**停止**，把 `hint` 原文给用户。不要编造片库，不要假装已经出片。

安装 CLI：

```bash
pip install "narrator-ai-cli @ git+https://github.com/NarratorAI-Studio/narrator-ai-cli.git"
export NARRATOR_APP_KEY=...
```

## 白名单动词

只准跑这些（Hevi 代理会拒绝其它子命令）：

| verb | 作用 |
|---|---|
| `material-list` | 内置片库 |
| `search-movie` | 片名搜索（extra 里放片名） |
| `bgm-list` / `dubbing-list` / `narration-styles` | 资源 |
| `user-balance` | 余额 |

```bash
uv run python -m hevi.skills.narrator_cli material-list
uv run python -m hevi.skills.narrator_cli search-movie 肖申克的救赎 --json
```

HTTP：`GET /api/narrator/status`、`POST /api/narrator/run`。

## Agent 铁律（与上游 skill 相同）

1. **先亮内置片库**，再问要不要上传。
2. **一次只确认一项**：路径（Fast/Standard）→ BGM → 配音 → 模板。禁止把模式和路径挤在同一句。
3. Fast 才有 `target_mode`（1 纯解说 / 2 原声混剪 / 3 新剧）。Standard 不要问这个。
4. 配音语言 = 文案 `language` = magic-video 文案语言。
5. 下游任务的 `order_num` 必须是 `.task_order_num`，**禁止**提交 32 位 hex `.task_id`。
6. 轮询用 5 秒 `while`，不要固定次数 `for`。
7. 失败后问用户是否换路，禁止自动切换 Fast/Standard。
8. `magic-video` 提交前必须展示完整请求体并得到明确确认（30 pts/分钟，不可逆）。

详细参数表、错误码、Fast/Standard 逐步 JSON 见同目录 `references/`（上游 NarratorAI-Studio/narrator-ai-cli-skill 原样拷贝）。
