# HEVI Productization Guide (D6)

This guide covers the product surfaces built on HEVI's verified differentiators.
It uses product vocabulary; internal authority names are implementation detail.

## Quick Start

1. Sign in, open **工作台 (/workspace)**.
2. On **制作状态**, fill **项目类型 / 素材 / 目标输出** and click **开始创建**.
   Advanced capabilities (persistent character, continuity, memory, provider,
   repair policy) are optional and defaulted — you do not configure them to start.
3. Click **示例项目** to create a clearly-labelled **演示** project. The demo uses
   only local fixture data and never spends on paid generation; demo results are
   not production deliverables.

## 角色库与跨项目复用

Open **工作台 → 角色库**.

- Create a character with **保存到角色库** (name + voice).
- **用于当前项目** binds the character to the current project **and pins the
  current version**. Projects never silently follow the latest version.
- When the character is updated, affected projects show **有新版本可用**; click
  **升级到当前版本** to opt in explicitly.
- **归档** hides the character from the library without deleting it. Historical
  projects, bindings and continuity facts are preserved — nothing dangles.

Cross-project reuse and version pinning are backed by the verified
*Persistent cross-project creative identity* differentiator.

## 连续性检查

Open **工作台 → 连续性** (or the pre-generation check).

- **未发现连续性问题** — proceed.
- **发现 N 个连续性提醒** — review, then either **返回修改** or **仍然继续生成**
  (continuing records an audited override).
- **无法开始生成：存在硬性冲突** — generation is refused and **no paid task is
  created**. Fix the contradiction (character appearance, lost prop, wrong
  location, state or hard canon) and retry.
- Expand **为什么 HEVI 这么判断** to see the fact provenance (source, episode /
  scene / shot, approved vs inferred).

Backed by the verified *Continuity-aware production* differentiator.

## 制作问题与自动修复

Open **工作台 → 制作问题**.

- Recoverable issues (download interrupted, provider temporarily unavailable,
  worker restart) show **HEVI 已恢复制作**.
- Paid or creative-changing repairs show **需要你的确认** with the action, the
  estimated extra cost (when known), and what is preserved. Buttons are
  **确认修复** / **暂不处理** — never an ambiguous "Retry".
- Issues needing your action (missing credential, rights) show **需要你处理** and
  are never auto-retried.
- Open **处理过程** for the timeline: detected → diagnosed → proposed → confirmed
  → executed → verified. A completed action is not the same as a verified result.

Backed by the verified *Self-healing production* differentiator.

## 费用与修复确认

- Auto-recoverable repairs never incur new paid generation.
- Any repair that may incur new paid generation requires explicit confirmation
  first; the estimated cost is shown when it can be computed.
- The dashboard's **创作数据** panel reports auto vs confirmed paid repairs and
  the number of duplicate billings avoided.

## 多用户安全边界

- Characters, continuity facts, production issues and creative memory are
  **private to your account** (server-derived owner). Other users cannot list,
  read, bind, upgrade, confirm, refuse or verify your data.
- This is application-level tenant isolation, not certified infrastructure
  compliance.

## 生产状态

**工作台 → 制作状态** shows one server-derived status per project:
**可以开始制作 / 制作中 / 需要处理 / 已阻塞 / 已完成**, with the **下一步** action
decided server-side (continue, confirm repair, handle manually, export). The
browser does not recompute this.

## 单主机部署边界

The durable differentiation stores are **single-host durable**: they survive
process restarts on the one authoritative host. They are **not** distributed,
multi-node or HA durable. A second authority host pointed at the same stores
fails closed. Do not run two authoritative hosts against one store volume.

## 备份与恢复

Back up the differentiation stores as a coordinated set (identity +
continuity + production issues) under one boundary token; restore the whole set
together. A partially restored set is detected and refused rather than served
inconsistently.

## Creative preferences (项目记忆)

Your **创作偏好** and **项目约定** are remembered per account/project and used
to compose planning inputs. They are advisory; they never override hard canon.

## Known limitations

- **Lip-sync presenter: BLOCKED** on this host (no GPU / ComfyUI / EchoMimic).
  Talking-head-without-lip-sync is not counted as verified lip-sync.
- **Local GPU runtime: BLOCKED** (no GPU). Local/hybrid generation is
  control-plane-ready only.
- Creative memory is backend/API + limited UI, not a full personalization suite.
- 3O lint drift is a local environment condition (see the D6-M drift report);
  the canonical 3O architecture audit is PASS.
