/**
 * playerPhysics 测试:碰撞盒生成 / 边界 clamp / 圆-盒推回。
 */
import { describe, it, expect } from 'vitest';
import type { GalleryItem } from '@/types/api';
import {
  buildShelfColliders,
  resolvePlayerCollision,
  STORE_BOUNDS,
  PLAYER_RADIUS,
  SECTION_Z,
} from './playerPhysics';
import { buildShelfPlan, SHELF, sectionCenterX } from './shelfPlan';

function imageItem(id: string): GalleryItem {
  return { item_id: id, category: 'image', title: id, prompt: '', gen_params: { category: 'image' } };
}

const sections = buildShelfPlan([imageItem('a'), imageItem('b'), imageItem('c')]);

describe('buildShelfColliders', () => {
  it('每段货架一个碰撞盒,覆盖段几何', () => {
    const colliders = buildShelfColliders(sections);
    expect(colliders).toHaveLength(sections.length);
    colliders.forEach((c, i) => {
      const cx = sectionCenterX(i);
      expect(c.xMin).toBeCloseTo(cx - SHELF.SECTION_W / 2, 6);
      expect(c.xMax).toBeCloseTo(cx + SHELF.SECTION_W / 2, 6);
      expect(c.zMin).toBeCloseTo(SECTION_Z - SHELF.SECTION_D / 2, 6);
      expect(c.zMax).toBeCloseTo(SECTION_Z + SHELF.SECTION_D / 2, 6);
    });
  });
});

describe('resolvePlayerCollision', () => {
  it('边界 clamp:走出店面被拉回', () => {
    const r = resolvePlayerCollision({ x: 999, z: 999 });
    expect(r.x).toBeCloseTo(STORE_BOUNDS.xMax - PLAYER_RADIUS, 6);
    expect(r.z).toBeCloseTo(STORE_BOUNDS.zMax - PLAYER_RADIUS, 6);
  });

  it('正面撞货架:沿最近点法向推回,不穿透', () => {
    const colliders = buildShelfColliders(sections);
    const c = colliders[0];
    // 玩家从货架正前方(z > 盒)冲入
    const r = resolvePlayerCollision({ x: (c.xMin + c.xMax) / 2, z: c.zMax - 0.05 }, PLAYER_RADIUS, colliders);
    expect(r.z).toBeGreaterThanOrEqual(c.zMax + PLAYER_RADIUS - 1e-9);
    expect(r.x).toBeCloseTo((c.xMin + c.xMax) / 2, 6);
  });

  it('斜角撞盒角:沿角点方向推回', () => {
    const colliders = buildShelfColliders(sections);
    const c = colliders[0];
    const r = resolvePlayerCollision({ x: c.xMax - 0.02, z: c.zMax - 0.02 }, PLAYER_RADIUS, colliders);
    // 推回后与盒角距离 >= radius
    const dx = r.x - c.xMax;
    const dz = r.z - c.zMax;
    expect(Math.hypot(dx, dz)).toBeGreaterThanOrEqual(PLAYER_RADIUS - 1e-6);
  });

  it('圆心落入盒内(穿模):推回最近边', () => {
    const colliders = buildShelfColliders(sections);
    const c = colliders[0];
    const r = resolvePlayerCollision({ x: (c.xMin + c.xMax) / 2, z: (c.zMin + c.zMax) / 2 }, PLAYER_RADIUS, colliders);
    // 横向对称:应被推回最近边(z 边,因为 x 方向两端距离相等时走 z 分支)
    expect(r.z >= c.zMax + PLAYER_RADIUS - 1e-9 || r.z <= c.zMin - PLAYER_RADIUS + 1e-9).toBe(true);
  });

  it('无碰撞体时仅做边界 clamp', () => {
    const r = resolvePlayerCollision({ x: 3, z: -2 }, PLAYER_RADIUS, []);
    expect(r).toEqual({ x: 3, z: -2 });
  });

  it('远离货架不误推', () => {
    const colliders = buildShelfColliders(sections);
    const r = resolvePlayerCollision({ x: 0, z: 4 }, PLAYER_RADIUS, colliders);
    expect(r).toEqual({ x: 0, z: 4 });
  });
});
