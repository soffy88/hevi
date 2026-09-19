/**
 * D6 product copy — user-facing vocabulary.
 *
 * Internal authority names (GlobalCreativeIdentity, ContinuityLedger,
 * RepairIncident, …) MUST NOT appear in the UI. Wording stays within the
 * verified claim matrix (artifacts/research/hevi_differentiation_claim_matrix.json):
 * no "never fails", no "fixes everything", no "guarantees consistency",
 * no "local AI video", no "verified lip-sync".
 */

export const PRODUCT_COPY = {
  characterLibrary: {
    title: '角色库',
    subtitle: '跨项目复用角色，并固定角色版本',
    empty: '还没有长期角色。创建角色后可以保存到角色库，在其他项目继续使用。',
    createPlaceholder: '角色名称',
    saveToLibrary: '保存到角色库',
    useInProject: '用于当前项目',
    upgrade: '升级到当前版本',
    upgradeAvailable: '有新版本可用',
    pinned: (v: number) => `当前项目固定 v${v}`,
    archive: '归档',
    archived: '已归档',
    projectsUsing: '使用中的项目',
    appearances: '形象',
    voice: '声音',
  },
  continuity: {
    title: '连续性检查',
    pass: '未发现连续性问题',
    warn: (n: number) => `发现 ${n} 个连续性提醒`,
    block: '无法开始生成：存在硬性冲突',
    checkBeforeGenerate: '生成前检查角色、道具和剧情连续性',
    viewDetails: '查看详情',
    continueAnyway: '仍然继续生成',
    backToEdit: '返回修改',
    why: '为什么 HEVI 这么判断',
    provenance: '依据',
    affected: '影响范围',
  },
  repair: {
    title: '制作问题',
    empty: '当前没有制作问题',
    autoRecovered: 'HEVI 已恢复制作',
    needsDecision: '需要你的确认',
    manual: '需要你处理',
    confirmRepair: '确认修复',
    notNow: '暂不处理',
    regenerates: '将重新生成',
    willBePreserved: '会保留的内容',
    estimatedCost: (n: string) => `预计新增费用 ${n}`,
    noExtraCost: '不会产生新的付费生成',
    timeline: '处理过程',
    verified: '已验证结果',
    failed: '修复未成功',
  },
  project: {
    healthTitle: '制作状态',
    nextAction: '下一步',
    status: {
      READY: '可以开始制作',
      GENERATING: '制作中',
      NEEDS_ATTENTION: '需要处理',
      BLOCKED: '已阻塞',
      COMPLETE: '已完成',
      UNKNOWN: '未知',
    } as Record<string, string>,
  },
  onboarding: {
    quickStart: '快速开始',
    quickStartHint: '几步即可开始，高级能力有合理默认值。',
    sample: '示例项目',
    sampleHint: '这是一个演示，用于体验流程；示例结果不作为生产交付。',
    demoBadge: '演示',
  },
  claims: {
    crossProject: '跨项目复用角色，并固定角色版本',
    continuity: '生成前检查角色、道具和剧情连续性',
    selfHealing: '可自动恢复部分制作故障，涉及重新付费时先征求确认',
    isolation: '多用户项目和创作数据隔离',
  },
} as const;

/** Timeline event → human label (never raw enum). */
export const TIMELINE_LABELS: Record<string, string> = {
  detected: '发现问题',
  diagnosed: '已诊断',
  action_proposed: '已给出修复方案',
  needs_decision: '等待你的决定',
  authorized: '已确认修复',
  authorization_declined: '修复未获确认',
  executed: '已执行修复',
  verified_resolved: '已验证恢复',
  verification_failed: '验证未通过',
  declined: '已选择暂不处理',
};
