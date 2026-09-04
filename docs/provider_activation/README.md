# HEVI Provider Activation Track

9 段真实验收链，每个 Provider 都跑完才能从 `EXTERNAL PROVIDERS PENDING` 升级到
`HEVI FULL SYSTEM — ALL CAPABILITIES VERIFIED`。

```
1. credential/config    → 凭证 / 配置就位
2. readiness probe      → 健康探测通过
3. real submit          → 真实任务提交（非 mock）
4. ACK / job_id         → 拿到服务侧确认
5. real artifact/result → 真实产物 / 结果回传
6. local freeze         → 本地落盘、固化
7. provenance           → 来源 / 参数 / 时间戳全留痕
8. evaluation           → 质量 / 验收指标判定
9. billing/usage        → 计费 / 用量记录（如适用）
```

每跑完一段必须把证据落到 `docs/provider_activation/<provider>/<NN>_<step>.{json,md}`，
只把 9 段都 PASS 的 Provider 标 `VERIFIED`。

## 统一入口

- 配置诊断：`uv run python -m hevi.skills.providers_cli status --provider <id>`
- Readiness 终审：`uv run python -m hevi.skills.providers_cli readiness --provider <id> ...`
- 媒体 resolve：`uv run python -m hevi.skills.media_cli resolve --type image|video --intent "..."`
- 真实 sub-agent 调用：见每个 Provider 自己的子目录

## Provider 队列与当前状态

| # | Provider | 9 段状态 | 下一段 | 阻塞原因 |
|---|---|---|---|---|
| 1 | Wan / local | ✅ VERIFIED（先前基线） | — | — |
| 2 | Pexels | ✅ **VERIFIED** | — | 9/9 PASS；详见 `pexels/REPORT.md` |
| 3 | JoyAI | 🔴 Stage 1 BLOCKED | Stage 1 credential | `JOYAI_BASE_URL` / `JOYAI_STREAM_WS_URL` / `JOYAI_API_KEY` 均空 |
| 4 | Voicebox | 🟡 Stage 1 PARTIAL | Stage 2 probe | `VOICEBOX_BASE_URL` 已设但 gen-engine 未启；缺真实 ACK |
| 5 | Duix | 🔴 Stage 1 BLOCKED | Stage 1 credential | `DUIX_SERVICE_URL` / `DUIX_LIVESTREAM_PATH` 均空 (仅 livestream 路径)；杜比离线口型合成为内部化路径 |
| 6 | MPT live | 🟡 Stage 1 PARTIAL | Stage 2 probe | `MPT_API_BASE` 已设但 `MPT_API_KEY` 空；未拿到 /ping ACK |
| 7 | HELIOS deploy | 🔴 Stage 1 BLOCKED | Stage 1 credential | `.env` 与 `.env.example` 都没有任何 HELIOS_* 变量名 |

> 阶段编号约定：1=credential/config 2=readiness probe 3=real submit 4=ACK/job_id
> 5=real artifact 6=local freeze 7=provenance 8=evaluation 9=billing/usage

## 总账状态（升级前冻结）

```
HEVI V1.0 CORE            = VERIFIED
HEVI FRONTEND             = READY
HEVI REAL USER UX         = READY
HEVI CODE BLOCKERS        = 0
EXTERNAL PROVIDER TRACK   = PENDING  (1/6 verified: Pexels；Wan/local 列为内化基线不计)
FULL ALL-PROVIDER SYSTEM  = NOT YET VERIFIED
```
