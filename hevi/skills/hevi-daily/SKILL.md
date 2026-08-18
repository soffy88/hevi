---
name: hevi-daily
version: "0.1.0"
description: 解说线与历史现场日更。按选题日历每天排一条并写发布交接单。
argument-hint: "[explainer-daily|history-scene-daily]"
allowed-tools: Bash, Read
homepage: https://github.com/soffy88/hevi
license: MIT
user-invocable: true
---

# /hevi-daily

两条日更，不新开管线。

| 日历 | 产线 | 默认发布 |
|---|---|---|
| `explainer-daily` | `explainer` | 抖音 / B 站交接单 |
| `history-scene-daily` | `history_scene` | B 站 / 视频号交接单 |

教科书连载仍可用 `POST /api/history-series/produce-daily`。本 skill 管「系列选题日历」。

## 调用

```bash
# 加选题
curl -X POST "$HEVI_API/api/studio/daily/calendars/explainer-daily/topics" \
  -d '{"topics":[{"title":"盐税是什么","scheduled_date":"2026-08-19"}]}'

# 今日一拍
curl -X POST "$HEVI_API/api/studio/daily/tick" -d '{"now":"2026-08-19"}'
```

MCP:`hevi.tick_daily`

Veya 单条成品走 `hevi.produce_finished`，不要用日更日历冒充点播。
