# GATE-N0 · s1 曲沃代翼 · N0 双 agent 试点（送裁·升顾问）· 2026-07-24

**依据**：HEVI-N0-DUALAGENT-SPEC-001（commit 1170108）§4/§5/§6。
**输入**：EpisodePlan 定稿 `QNLR-EP-jin-decline-s1`（commit 656e887）。
**W 模型**：qwen_cloud（ALIBABA_MAAS workspace·qwen-plus，非欠费）。**R-hard**：纯代码 H1–H8（commit e4061df）。
**判定人**：顾问 Claude（Wiki 授权 2026-07-24）。**结论：W↔R 3 轮未收敛 → 升顾问（spec §5）。deliverable 已就绪、送裁不进 N1。**
**净稿 sha256**：`b592c2a5ed9370cd128eea1f3c2db8535cd5e958bf2a1cd446018bc6ce0c2aed`。

---

## 一等指标四数（spec §6）

| 指标 | 值 |
|---|---|
| 硬门首过率 | **7/8 门（首轮）**；首轮整稿未过（仅 H8 FAIL） |
| W↔R 轮数 | **3**（达上限未收敛，升顾问） |
| 閘⓪人工分钟 | 待送裁（自动 pilot 未过人工闸；deliverable 已就绪） |
| cost/稿 | **¥0.0541**（qwen_cloud 真机，W×3 + R-soft×1；cost 入四支柱账 meta.cost） |

## 逐轮 R-hard（不可欺裁判实证）

```
round 1: H1–H7 PASS, H8 FAIL(2)   ← b2 VO 超时
round 2: H8 PASS, H2 FAIL(1)      ← W 缩 b2 时改动引文，破引文逐字
round 3: H2 PASS, H8 FAIL(1)      ← W 复原引文逐字，b2 又超时
final  : H1–H7 PASS, H8 FAIL(1)   ← s1-b2 VO 估时 16.4s > 15s/拍
```

## 失败分类（升顾问·spec §5）

- **门**：H8（VO 5–15s/拍），`sid=s1-b2`，估时 **16.4s**（82 字 ÷ 5 字/s）。
- **根因**：b2 单拍装了**逐字长引文**（师服『本大而末小是以能固…今晋甸侯也而建国本既弱矣其能久乎』约 30+ 字）+ fact + 解读 = 16.4s。引文受 **H2 逐字锁死不可删**，非引文 trim 压不下 15s → W 在 **H8(缩)↔H2(引文逐字)** 间振荡不收敛。
- **性质**：**OP-D-051② 薄集典型**——2 拍集里单拍装不下"长逐字引文 + 解读"。**非 W 能力缺陷，是薄集结构张力 + R-hard 阈值语义未定**。

## 顾问裁选项（送 Wiki）

1. **R-hard 阈值语义**：H8 VO 估时应否**把逐字引文按其呈现方式计**（引文常作字幕/快读，不按 5 字/s 口播估）？若采纳，H8 改为"非引文口播字数"估时——本例 b2 去引文后约 10s，过闸。（R-hard 阈值裁决，改代码需 Wiki 点头。）
2. **回策展补料**：b2 师服长引文单独拆一拍（b2→b2+b3，3 拍）——改 EpisodePlan 拍数属**策展粒度决策**（OP-D-051② 厚薄合并），超 W 权限，回策展。
3. **特批记录**：本薄集 b2 特批 16.4s（薄集验流程为主、时长非本轮判据）。

**顾问倾向**：选项 1（引文不计口播估时）——它根治"长引文拍"的普遍张力，且与 VO 主时钟语义一致；改 H8 估时口径需 Wiki 拍。

## R-soft 软评（不设门·附审计）

1. 开场钩子薄弱：首句直抛年份事件，缺悬念/画面感/现代共鸣；建议设问切入。
2. 叙事节奏失衡：b1 仅 1 句、b2 信息密度过高；建议拆师服预言为独立 beat 并配简释。
3. 通俗度不足：翼侯/汾隰/支庶大宗等术语未即时解释。
4. 深度名实：标榜"首次应验"未对比先例、未点转型标志性意义，深度停于引文复述。
5. 史源呈现生硬：文言直录无口语转译/语境说明。

## 素材缺口
无（本轮 W 未申报；s1 KU 对象齐，证据链无 PENDING-pin）。

## 产物（durable-on-host，output/ gitignored）
- 净稿 `output/n0_s1/s1_clean_script.json`（sha 见上）
- 审计报告 `output/n0_s1/s1_audit_report.json`（每门+轮数+soft+gaps+metrics）
- 本签字工件为**可提交证据**（output/ 不入 git，evidence 嵌此）。

> N0 试点验证：**R-hard 审判有效（H8/H2 精确拦截）、W 双轨结构 7/8 首过、cost 入账通、升顾问路径打通**。s1 因薄集+引文阈值未收敛，deliverable 送裁，H8 口径待 Wiki 裁。
