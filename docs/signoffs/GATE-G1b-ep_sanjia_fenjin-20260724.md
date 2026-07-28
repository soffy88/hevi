# GATE-G1b · 三家分晋 G1b 对拍收口签字工件 · 2026-07-24

**闸口**：G1b（KU 查询响应 → 投影 VisualFact' → 对拍 G1a 手工装配）。
**钉点**：stratum annotated tag `history-contract-v0.2.2`（D-023：撤 cf:jinyang-independence，conflicts 空数组）。
**判定人**：顾问 Claude（Wiki 授权，2026-07-24）。
**RESULT**：**PASS**（diff 全解释）。

---

## 钉点 sha256（字节即真理，harness 硬编码校验）

| 输入 | sha256 | 说明 |
|---|---|---|
| `sample.sanjiafenjin.json`（ev:jinyang-zhizhan §8 冻结样例） | `4126c842aa0fc8f3b22268a0830c4b18e728233ca36f12297e636b0c572c62d9` | v0.2.2 新字节（撤 cf:jinyang-independence）；旧 `a1e7d70…` 作废 |
| `history-query-response.schema.json` | `638fc28e7db8bde88dd90309d478a280287a87d0d7b7c7e77d8ff02373ff7b6f` | 字节不变（contract_version 仍 v0.2，撤的是 conflict 实例非 shape） |

## 对拍结果

```
输入钉住 OK: contract_version=v0.2 (tag history-contract-v0.2.2)
L1 自造字段=0 | L2 断链=无 | L3 手工数据全过
L4 投影: 事件级 VisualFact' 1 条(过契约) | S12 冲突投影 0 条
对拍: 覆盖拍 11/11 | diff {一致:32, 可解释:90, PENDING:0} | gap 拍 0
RESULT: PASS(diff 全解释)
```

- **coverage gap 复测**：首测 4/11（仅 B05–B08）→ 现 **11/11**（B01–B11 全覆盖，PAIRING 指向 v0.2.2 交付单指向表），**覆盖提升 +7**，gap 拍归零。
- **閘① durable 计时**：`2026-07-24T00:05:22Z` → `2026-07-24T00:09:02Z` = **220s**（`.gate1_v022_start_ts`/`.gate1_v022_end_ts`）。

## 裁决（6 条 PENDING → 可解释）

首跑 6 条 PENDING（B01/B02 date、B03 regions+persons、B10/B11 date）经复核**全部为跨事件比对产物**：v0.2.2 PAIRING 将这些拍指向非-jinyang 事件（jin-gongshi-bei/zhixuanzi-liyao/zhibo-suodi/minghou-403），而 harness 钉点 sample 只是 ev:jinyang-zhizhan 单事件，`project_event()` 仅投影该事件，故这些拍被拿去与晋阳之战投影逐字段比，date/regions/persons 差异系"beat 指向事件 ≠ 载入事件"所致，非数据错。

**裁决（Wiki 授权顾问裁，2026-07-24）**：6 条改判**可解释**，explain 统一为——
> 「跨事件比对产物：beat 指向事件 ≠ 单-sample 载入事件，PAIRING 指向经复核正确（Wiki 授权顾问裁，2026-07-24）」

harness `classify()` 已加此裁决规则（落 PENDING 兜底前），future 运行稳定 PASS。

## 关联

- 单-sample 无法逐字段校验非-jinyang 拍的多事件对拍，作 **HARNESS-DEBT-1** 入册（`docs/DEBT-REGISTER.md`，needed-by=G2 批量前）；单-sample 口径在 G1b 语境下已完成历史使命。
- 判据（裁决修订 2026-07-22）：閘① durable 计时 + diff 全解释——两项均达成。**G1b 收口。**
