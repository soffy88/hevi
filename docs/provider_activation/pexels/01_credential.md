# Pexels — Stage 1 credential/config

## 段位
`Stage 1 of 9` — credential/config

## 检查方式

```bash
# 1) .env 文本层
grep "^PEXELS_API_KEY=" .env
# 2) 进程环境层（dotenv 加载后）
uv run python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(len(os.getenv('PEXELS_API_KEY','')))"
# 3) HEVI provider_policy 视角
uv run python -m hevi.skills.providers_cli status --provider pexels --no-probe
```

## 原始证据

| 渠道 | 值 | 长度 |
|---|---|---|
| `.env` 行 | `PEXELS_API_KEY=`（截到 `=` 后为空） | 0 |
| `dotenv` 加载后 `os.getenv` | `""` | 0 |
| `providers_cli status --no-probe` JSON | `"configured": false`, `"missing": ["PEXELS_API_KEY"]` | — |

## 判定

- **Status:** `BLOCKED_CONFIG`
- **Reason:** `PEXELS_API_KEY` 未设置（值为空字符串，HEVI 视为未配置）
- **Action required:** 在 `.env` 中填入真实 Pexels API Key（来源：https://www.pexels.com/api/ 控制台）

## 复跑脚本

```bash
uv run python -m hevi.skills.providers_cli status --provider pexels --no-probe
```

期望看到 `"configured": true` 且 `"missing": []`。
