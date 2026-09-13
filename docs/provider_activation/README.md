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
| 3 | JoyAI | 🔴 Stage 1 BLOCKED | Stage 1 credential | `JOYAI_BASE_URL` / `JOYAI_STREAM_WS_URL` / `JOYAI_API_KEY` 均空；未执行真实调用 |
| 4 | Voicebox | 🔴 Stage 2 BLOCKED | Stage 2 probe | `VOICEBOX_BASE_URL` 已设但当前不可达；未拿到真实 ACK；独立 CosyVoice3 本地运行时已另行实测通过 |
| 5 | Duix | 🔴 Stage 2 BLOCKED | Stage 2 readiness | `DUIX_SERVICE_URL` / `DUIX_LIVESTREAM_PATH` 均空；`duix-avatar-gen-video` 当前 Exited (137) |
| 6 | MPT live | 🟡 CURRENT REAL ARTIFACT / Stage 9 BLOCKED | Stage 9 billing/usage | 当前控制面健康；真实 task `55d3790c-e053-40ac-8ceb-58314636cdc2` 完成并已下载 MP4；billing/usage 证据尚未闭环 |
| 7 | Vidu | 🔴 Owner blocked | Stage 1 credential refresh | 已使用 `.env` credential 发起真实 `reference2video` 请求；服务端 HTTP 401 Unauthorized，无 job_id/产物 |
| 8 | LongLive | 🔴 Stage 1 BLOCKED | Stage 1 provider | `LONGLIVE_BASE_URL` 为空；运行时返回 `planned`，不计真实执行 |
| 9 | HELIOS deploy | 🔴 Stage 1 BLOCKED | Stage 1 credential | `.env` 与 `.env.example` 都没有任何 HELIOS_* 变量名 |

### RC5 current local/runtime evidence

以下状态只代表本轮在当前工作区实际跑通的本地闭环，不替代外部 Provider 的 9 段验收：

| Capability | Current evidence | Status |
|---|---|---|
| Frontend production | `hevi-web/.env.production` 使用 `https://api-prod.sxueji.com`、mock=false；typecheck、156/156 tests、Next build 均通过 | ✅ CURRENT |
| MPT real generation | `outputs/rc5/mpt/55d3790c-e053-40ac-8ceb-58314636cdc2/` 含 request/status/MP4/provenance；MP4 已 ffprobe | ✅ CURRENT |
| ComfyUI H3 | `outputs/rc5/h3/` 含 raw、FlashVSR upscaled、RIFE final MP4 与 provenance；当前 8188 可用 | ✅ CURRENT |
| Canonical TTS | `outputs/rc5/voice/cosyvoice3_real.wav` 为 CosyVoice3 native inference 产物，含 ffprobe/SHA/provenance | ✅ CURRENT |
| Digital human | `outputs/rc5/digital_human/echo_mimic_real.mp4` 为 EchoMimicV2 native ComfyUI 推理产物，含视频/音频流与 provenance | ✅ CURRENT |
| Promo render | `outputs/rc5/promo/promo_final.mp4` 由 PaperPromo/Remotion 使用真实 MPT 截帧渲染并通过质量门；默认静音画面轨 | ✅ CURRENT |
| Vidu lip-sync | 代码证据仍为未实现独立 lip-sync 后处理；本轮 Vidu 请求未获授权 | 🔴 BLOCKED |

本轮证据索引：`outputs/rc5/vidu/request_result.json` 记录 Vidu 的 401；JoyAI、LongLive、Duix Live 均因 provider/path 配置为空未执行真实生产调用。`DUIX` 的离线 fallback/历史 smoke 不等同于当前 Duix native inference。

> 阶段编号约定：1=credential/config 2=readiness probe 3=real submit 4=ACK/job_id
> 5=real artifact 6=local freeze 7=provenance 8=evaluation 9=billing/usage

## 总账状态（升级前冻结）

```
HEVI V1.0 CORE            = VERIFIED
HEVI FRONTEND             = VERIFIED CURRENT (production config/build/typecheck/tests)
HEVI REAL USER UX         = PARTIAL CURRENT
HEVI CODE BLOCKERS        = PRESENT (真实代码回归与测试基础设施阻断待清理)
EXTERNAL PROVIDER TRACK   = BLOCKED/PARTIAL (Pexels verified；MPT 有真实当前产物但 billing/usage 未闭环)
LOCAL VIDEO RUNTIME       = PARTIAL CURRENT (MPT/H3/CosyVoice3/EchoMimic/Promo 已有当前证据)
FULL ALL-PROVIDER SYSTEM  = NOT YET VERIFIED
```
