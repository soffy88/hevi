# QNLR-EP · s1 曲沃代翼 · EpisodePlan 实例（定稿 · 送裁 · 不进 N1）· 2026-07-24

> **性质**：P3 试点件（W agent 输入）。**送裁不进 N1、不产旁白稿、不动 schema**。**判定人=顾问 Claude·Wiki 授权 2026-07-24**。
> **状态**：按裁决**定稿**——counterpoint 判显式无（附检索记录）、shimo-changbian 移除（见自查③）。
> **形状依据**：stratum `EPISODEPLAN-MAPPING-DRAFT.md`（e009b8b，read-only）+ `CURATION-s1-s2.md`（a4d53d8）+ `arc-jin-decline.json`（94c2376）+ OP-D-051；字段对齐已落仓 `HEVI-N0-DUALAGENT-SPEC-001` §2 ScriptDraft 双轨。

---

## EpisodePlan 实例（超集形状）

```yaml
episode_id: ep:jin-decline-s1
title: 曲沃代翼
sub_arc_ref: arc:jin-decline/s1-quwo        # seq=1，七子簇之首
粒度裁议: 一子簇=一集（送裁点②）；**3 拍**——师服论断独立成拍（N0-D-002 薄集拆拍首例，OP-D-051②）
time_window: 前745（曲沃封桓叔·晋始乱）– 前678（武公灭翼代晋·王命为晋侯）  # 曲沃三世 67 年，成员事件 canonical_date 包络

# ── 论点双轨（thesis_refs 轨）──────────────────────────────────
throughline_thesis:
  ref: thesis:shifu-modabizhe                # 师服『末大必折』
  quote_locator: "4YW6S…:0205"               # 左传桓2/惠之二十四年
  quote: "本大而末小是以能固…今晋甸侯也而建国本既弱矣其能久乎"
  attribution: 源内（师服·左传）
counterpoint_theses: []                      # 裁定：显式无（附检索记录，满足 H6/OP-D-045）
counterpoint_search_record:                  # OP-D-045：默认无对立=未查，故附检索
  claim: s1 曲沃代翼因果论·源内无同题异框架对立论点（师服『末大必折』为唯一）
  searched: [左传·桓2, 左传·桓3, 左传·庄28, 史记·晋世家, 国语·晋语]
  result: 未见同题异框架源内论点；shimo-changbian（史墨『社稷无常奉』·左传昭32=前510）晚曲沃代翼 200+ 年、属六卿期君权旁落，非曲沃代翼异框架 → 移除，defer arc 级/s3+
  decided_by: 顾问 Claude · Wiki 授权 2026-07-24

# ── 分镜拍（beats·3 拍）· fact 拍与 thesis 拍分离（N0-D-002）──────────────
beats:
  - beat_id: s1-b1
    title: 曲沃封桓叔·晋始乱
    fact_refs: [ev:quwo-feng-huanshu]        # candidate→KU（送裁；cand:quwo-feng-huanshu）
    thesis_refs: []                          # fact 拍（论断移 b3）
    evidence_spans:                          # 映射不变式①：一 beat ≥1 逐字白文 span
      - para_ulid: "4YW6S…:0205"
        source: 左传·桓公二年
        genre: 编年正史（白文）
        text: "惠之二十四年晋始乱，封桓叔于曲沃，栾宾傅之"
    mapstate_cues: [曲沃（封地·末）, 翼（晋都·本）]   # place_refs；无 place 冲突
    conflict_callouts: []                    # 无 S12 冲突
  - beat_id: s1-b2
    title: 曲沃武公灭翼·代晋
    fact_refs: [ev:quwo-wugong-mie-yi]       # candidate→KU（送裁；cand:quwo-wugong-mie-yi）
    thesis_refs: []                          # fact 拍
    evidence_spans:
      - para_ulid: "4YW6S…:0217"
        source: 左传·桓公三年（武公伐翼逐翼侯于汾隰）
        genre: 编年正史（白文）
        text: "曲沃武公伐翼，逐翼侯于汾隰"
        note: "后武公灭晋、王命为晋侯（并大宗）——过程性注记"
    mapstate_cues: [翼, 汾隰]
    conflict_callouts: []
  - beat_id: s1-b3
    title: 末大必折·师服论断（throughline 独立拍）
    fact_refs: []                            # thesis 拍（N0-D-002 拆出）
    thesis_refs: [thesis:shifu-modabizhe]    # 师服『末大必折』——曲沃代翼第一次应验
    evidence_spans:                          # 师服语所在（左传桓2，逐字引文供 H2）
      - para_ulid: "4YW6S…:0205"
        source: 左传·桓公二年（师服语）
        genre: 编年正史（白文）
        text: "本大而末小是以能固…今晋甸侯也而建国本既弱矣其能久乎"
    attribution: 我方按（师服·左传，R8/R10 论/史区分）
    mapstate_cues: []
    conflict_callouts: []

provenance:
  成员KU指纹: [SHA-256(cand:quwo-feng-huanshu), SHA-256(cand:quwo-wugong-mie-yi)]  # 待裁定转 KU 后钉
  membership_decided_by: 顾问 Claude
  candidate_status: 全 candidate→KU 送裁（本簇无 gold fixture 覆盖）
```

---

## 自查（三项，草案硬规）

### ① 双轨（fact_refs / thesis_refs）——达成
每拍 `fact_refs`（事件）与 `thesis_refs`（论点）分轨双挂：s1-b1 事件=封桓叔／论=师服预言；s1-b2 事件=武公灭翼／论=预言应验。史（画面事件）与论（旁白论点）R10 可区分，符 OP-D-051 双轨。

### ② 一拍一逐字白文 span——达成（s1 无 PENDING-pin）
s1-b1 :0205、s1-b2 :0217 均有 para_ulid 锚定逐字白文（左传桓2/桓3）。**s1 证据链无缺环**（对比 s2 的申生自缢/诅无畜群公子 PENDING-pin，s1 干净）。

### ③ counterpoint 非装饰——★裁定：显式无（附检索记录）· 顾问 Claude·Wiki 授权 2026-07-24
**背景（两权威输入曾矛盾）**：
- `EPISODEPLAN-MAPPING-DRAFT` §二：s1 counterpoint = `thesis:shimo-changbian`（史墨无常律）。
- `CURATION-s1-s2` s1 并陈项：「**无对立论点**（师服说为主流）」。

**裁决（2026-07-24）**：
1. **否决 shimo-changbian 作 s1 counterpoint、移除**。史墨『社稷无常奉、君臣无常位』（左传昭32=前510）晚于曲沃代翼（前745–678）二百余年、针对六卿期君权旁落，非对『曲沃代翼』因果的直接异框架——嫁接即违 OP-D-051『counterpoint 非装饰』。`thesis:shimo-changbian` **defer 至 arc 级或 s3+（六卿期）** 其在题位置。
2. **s1 判显式无 counterpoint，附 OP-D-045 检索记录**（见上 `counterpoint_search_record`）：已检左传桓2/桓3/庄28、史记·晋世家、国语·晋语——曲沃代翼因果论源内仅师服『末大必折』一说，未见同题异框架源内论点。满足 H6（『EpisodePlan 已附检索记录的显式无』）。

---

## 送裁点汇总（对接 MAPPING-DRAFT §四 + OP-D-051）
1. EpisodePlan 字段拟议准否（尤 `throughline_thesis`/`counterpoint_theses`/`beats[].fact_refs`+`thesis_refs` 双挂命名）。
2. 粒度：s1 一子簇=一集（本定稿取此），准否。
3. **counterpoint：已裁定**（顾问·Wiki 授权 2026-07-24）——否决 shimo-changbian、s1 显式无 counterpoint 附检索记录（自查③）。Wiki 保留否决。
4. 2 成员事件 candidate→KU 转正（过同一性管线 + 顾问裁）。
5. 依赖：`HEVI-N0-DUALAGENT-SPEC-001` **已落仓**（commit 1170108），字段对齐其 §2 ScriptDraft 双轨——本定稿即 W agent 输入。

> 定稿止此。不进 N1、不产旁白稿、不动 schema。
