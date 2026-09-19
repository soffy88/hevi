/**
 * D6-G product-claims conformance: copy stays within the verified claim matrix.
 */
import { describe, it, expect } from 'vitest';
import { PRODUCT_COPY, TIMELINE_LABELS } from './product-copy';

const FORBIDDEN = [
  '永不出错',
  '自动修复所有失败',
  '完全保证角色一致',
  '本地 AI 视频生成',
  '已验证口型同步',
  'GlobalCreativeIdentity',
  'ProjectCharacterBinding',
  'ContinuityLedger',
  'RepairIncident',
  'Artifact Currency',
  'Production Graph',
];

function allStrings(value: unknown): string[] {
  if (typeof value === 'string') return [value];
  if (typeof value === 'function') {
    return [(value as (n: number) => string)(3)];
  }
  if (value && typeof value === 'object') {
    return Object.values(value).flatMap(allStrings);
  }
  return [];
}

describe('产品文案与声明一致性', () => {
  it('不包含禁止的过度声明或内部术语', () => {
    const strings = [...allStrings(PRODUCT_COPY), ...Object.values(TIMELINE_LABELS)];
    for (const s of strings) {
      for (const bad of FORBIDDEN) {
        expect(s).not.toContain(bad);
      }
    }
  });

  it('包含经核验的核心表述', () => {
    expect(PRODUCT_COPY.claims.crossProject).toContain('跨项目复用角色');
    expect(PRODUCT_COPY.claims.continuity).toContain('生成前检查');
    expect(PRODUCT_COPY.claims.selfHealing).toContain('先征求确认');
    expect(PRODUCT_COPY.claims.isolation).toContain('隔离');
  });

  it('费用相关表述明确', () => {
    expect(PRODUCT_COPY.repair.noExtraCost).toMatch(/不会产生新的付费生成/);
    expect(PRODUCT_COPY.repair.estimatedCost('$2.00')).toMatch(/预计新增费用/);
  });
});
