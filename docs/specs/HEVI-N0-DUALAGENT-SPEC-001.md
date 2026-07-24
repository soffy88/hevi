# HEVI-N0-DUALAGENT-SPEC-001

## N0 双 agent 稿件生产规范（撰稿 W / 审核 R）v0.1

| 项 | 值 |
|---|---|
| 状态 | draft v0.1 · 2026-07-24 · 所有者 顾问 Claude（Wiki 全权授权，D-023）· 执行 CC-A |
| 所属 | hevi 仓。为 HEVI-EXPLAINER-PIPELINE-SPEC-001 §2 N0 阶段的实现规范 |
| 依赖 | 生产 spec（R4/R8/R9 体例、VO 主时钟）· AII-HISTORY-ARC-SPEC-001 §2 R10（双溯源）· OP-D-051（双轨/counterpoint 非装饰）· OP-D-054（原料池不可引）· history-contract v0.2.2 |
| 核心命题 | 稿子由 LLM 写、由**确定性代码**审、由顾问闸裁——LLM 产出、代码审判，不可欺裁判原则的 N0 落地形态 |

---

## 1. 流程

```
EpisodePlan（策展投影，如 QNLR-EP-*）
  → N0b  W 撰稿（LLM）→ ScriptDraft（结构化，非纯文本）
  → N0c  R 审核 = R-hard（纯代码硬门）+ R-soft（LLM 软评，仅意见）
  → W↔R 循环 ≤3 轮；硬门仍不过 → 升顾问（带失败分类）
  → 净稿 + 审计报告 → 閘⓪（顾问裁，Wiki 保留否决）→ 进 N1
```

## 2. ScriptDraft：句级双轨结构（机器可审的前提）

稿件不是纯文本，是句列表；每句强制分型：

```
ScriptDraft {episode_ref, beats[{beat_id, sentences[
  {sid, type ∈ {fact | thesis | transition},
   text,
   fact_refs[]      # type=fact 必填 ≥1，解析到 KU 事件/account（ULID 可达）
   thesis_refs[]    # type=thesis 必填 =1，解析到 thesis 对象
   display{署源体例串, attribution}   # R4/R8 的呈现层
  }]}], meta{model, prompt_ver, cost}}   # 四支柱照常
```

- transition 句（过渡/衔接）不带 ref，**全稿占比 ≤20%**（超限即硬门 FAIL）。
- 引用原文的 quote span 必须逐字命中语料 ULID 段（简繁归一后字节比对）。

## 3. R-hard 硬门（全部确定性代码，无 LLM 参与）

| 门 | 判 |
|---|---|
| H1 双溯源 | fact 句 fact_refs 全解析、thesis 句 thesis_refs 解析且 attribution 呈现（我方以"按"显式，R8/R10） |
| H2 引文保真 | quote span 逐字命中语料 ULID（机核，同 fixture 机核标准）；**扩门（N0-D-006）**：句中引号 `『』「」""` span 必须挂 quote 对象并过机核，未标疑似引文 FAIL（堵未标引文绕行） |
| H3 日期/数字 | 只出 chronology 注册表与 number_claims（带"《X》载"体例）；稿内任何数字无 ref 即 FAIL（"围两年"事故的制度化根除） |
| H4 名从注册表 | 人名/地名解析注册表，按代取名（R3）；原料池（OP-D-054）id 不可引 |
| H5 冲突不抹平 | EpisodePlan 涉及事件带 S12/角标 hint 的 cf，稿内必须呈现或显式记录不呈现理由 |
| H6 counterpoint 非装饰 | 按 OP-D-051：呈现 ≥1 次，或 EpisodePlan 已附检索记录的显式无 |
| H7 E-banner | 涉 E3/E4 事件的拍必须带等级标注指令（R9） |
| H8 结构 | transition ≤20%；beat 对齐 EpisodePlan；VO **分段估时** 5–15s/拍——非引文口播 5 字/s + H2 锁定的逐字引文按字幕 2 字/s，拍级求和（**N0-D-001** 修订，见 DECISIONS-N0.md；原口径一律 5 字/s 使含长引文拍误超时） |
| H9 拍-role 一致（**N0-D-005**） | EpisodePlan 声明的拍 role（`beat_roles`: fact/thesis）与实际句 type 分布一致；同一 `thesis_ref` 全稿呈现 >1 次须 EpisodePlan `allow_thesis_repeat` 显式允许，否则 FAIL |

R-soft（LLM）：叙事节奏、通俗度、开场钩子、深度是否名实相符——**只出意见附审计报告，不设门**。

## 4. W 撰稿约束

- 输入 = EpisodePlan + 其引用的 KU/thesis 对象全文 + 生产 spec 体例；**输入之外无事实来源**——W 不得引入任何未在 KU 内的日期、数字、人名、情节。
- 深度来自论点层：throughline 驱动叙事骨架，counterpoint 制造张力，事实层供证。照搬白文翻译即 R-soft 差评、且通常伴随 H1 结构性 FAIL（无 thesis 句）。
- W 可提"素材缺口"清单（想引而 KU 没有的），随审计报告上报——这是策展回流信号，不是自行补料的许可。

## 5. 升级与闸

- ≤3 轮不过：升顾问，附失败分类（H 门号 + 句 sid）；顾问裁 = 修稿指令 / 回策展补料 / 特批记录。
- 閘⓪ 交付 = 净稿 + 审计报告（每门结果 + 轮数 + soft 意见 + 素材缺口）+ cost。签字工件同格（钉稿件 sha256）。

## 6. 试点与度量

- 试点 = s1 曲沃代翼（QNLR-EP 草案，2 拍薄集照做——薄集验流程，厚薄合并是后续编辑决策，OP-D-051②）。
- 一等指标：硬门首过率 · W↔R 轮数 · 閘⓪ 人工分钟 · cost/稿。
- W 模型选型 CC-A 实测自决（hevi 不受 stratum 无云端约束，但 cost 入四支柱账）；R-hard 禁用任何模型。