# G0 · A-QIN 付费通路烟测签字工件

**日期**：2026-07-23
**立项**：QNLR-AQIN-PROJ-001 §0 前置链末环（T1→T3→A0→**G0**）
**性质**：首笔非零支出。经 `qnlr_gen_adapter.GenAdapter.generate_video`（A0，commit `9962c78` + 签名修复）真机调用 happyhorse。

---

## 判据与实测

| 项 | 结果 | 判定 |
|---|---|---|
| 付费通路连通 | happyhorse_1_1_maas（ALIBABA_MAAS workspace 专属域）调用成功返回 | ✅ |
| 产物验真（防占位 mp4） | ffprobe：h264 / 1280×720（720P）/ 5.125s / 123 帧 @24fps / 2.07MB；抽第 0/30/60 帧 md5 三者各异、帧字节各异 → 有真实运动，非静止占位 | ✅ 真片 |
| §3.5 单价闸 | ¥0.945/s < ¥1/s（视频阈值） | ✅ 过闸 |
| ¥80 金额帽 | 本次 ¥4.725，累计 spent 4.725 / 80，余 ¥75.275 | ✅ 帽内 |
| 熔断行为（附带实证） | 首次点火因 adapter 对底层签名传参错误 → `ok=False`、预留回滚、`spent_cny=0.0`、零支出（非静默失败）；修签名后复点成功 | ✅ 反静默断链有效 |

## 实测单价（首份，喂 tranche 2 预算 + §3.5 校准）

- happyhorse_1_1_maas：**$0.14/s = ¥0.945/s**（5s = $0.70 = ¥4.725）。
- ⚠ 此值取自 `hevi/cost/pricing_table.py:106`，注释标为"WaveSpeed 转售价当保守上限，非阿里官方逐秒价"。**真实账单需阿里云控制台核对**（直连大概率更低）；`alibaba_maas_generate` 仅返回 Path、不回传实际计费，故 adapter 计价走 pricing_table 上限估值。控制台账单回来后校准本表。

## 产物

- 烟测 clip：`<scratchpad>/g0_smoke.mp4`（一次性烟测，未入 vault；`register_fn=None`）。
- decision_trail digest：`3cb1328a1c0dd81e`。

## 结论

**前置链 T1→T3→A0→G0 全闭。** 付费通路已验、单价在闸内、帽与熔断实战有效。tranche 1 可进 L1（身份锚）/L2（D1 底版）——二者真实实现为本地免费（CLIP+TripoSR+本地 SDXL），零真机成本，但产出规模大且 L1 出口判据含人工"同一人 6/6"目检，建议开工前 Wiki 点头。
