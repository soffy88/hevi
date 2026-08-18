/**
 * playerPhysics — 第一人称行走碰撞(纯逻辑,可测)
 *
 * 玩家 = 半径 radius 的圆柱,货架段 = AABB(轴对齐盒)。
 * 移动分两步:先 clamp 到店面边界,再对每个货架 AABB 做圆-盒推回。
 * 坐标系:世界 X 右 / Z 朝向玩家(货架在 z=-5.5 一带)。
 */
import { sectionCenterX, SHELF, type StoreSection } from './shelfPlan';

/** 一个货架段的碰撞盒(含盒子厚度,玩家不可穿入)。 */
export interface ShelfCollider {
  xMin: number;
  xMax: number;
  zMin: number;
  zMax: number;
}

/** 店面可走范围。 */
export interface PlayerBounds {
  xMin: number;
  xMax: number;
  zMin: number;
  zMax: number;
}

/** 货架段局部原点 z(与 StorefrontScene 中 ShelfUnit position 一致)。 */
export const SECTION_Z = -5.5;

export const STORE_BOUNDS: PlayerBounds = {
  xMin: -12.5,
  xMax: 12.5,
  zMin: -7.5,
  zMax: 5.5,
};

/** 玩家默认半径(行走碰撞体,米)。 */
export const PLAYER_RADIUS = 0.45;

/**
 * 由分区计划生成货架碰撞盒列表(每段货架一个 AABB)。
 */
export function buildShelfColliders(sections: StoreSection[]): ShelfCollider[] {
  const halfW = SHELF.SECTION_W / 2;
  const halfD = SHELF.SECTION_D / 2;
  return sections.map((_, i) => {
    const cx = sectionCenterX(i);
    return {
      xMin: cx - halfW,
      xMax: cx + halfW,
      zMin: SECTION_Z - halfD,
      zMax: SECTION_Z + halfD,
    };
  });
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/**
 * 圆-盒碰撞解析:输入期望位置,输出被边界与货架推回后的合法位置。
 * 圆心在盒外:沿最近点法向推回;圆心落入盒内(高速穿模):推回最近边。
 */
export function resolvePlayerCollision(
  pos: { x: number; z: number },
  radius: number = PLAYER_RADIUS,
  colliders: ShelfCollider[] = [],
  bounds: PlayerBounds = STORE_BOUNDS,
): { x: number; z: number } {
  let { x, z } = pos;
  // 1. 店面边界
  x = clamp(x, bounds.xMin + radius, bounds.xMax - radius);
  z = clamp(z, bounds.zMin + radius, bounds.zMax - radius);
  // 2. 货架推回
  for (const c of colliders) {
    const nx = clamp(x, c.xMin - radius, c.xMax + radius);
    const nz = clamp(z, c.zMin - radius, c.zMax + radius);
    const dx = x - nx;
    const dz = z - nz;
    const d2 = dx * dx + dz * dz;
    if (d2 >= radius * radius) continue;
    if (d2 > 1e-9) {
      const d = Math.sqrt(d2);
      x = nx + (dx / d) * radius;
      z = nz + (dz / d) * radius;
    } else {
      // 圆心在盒内:沿穿透最小的轴推回
      const overlapX = Math.min(x - (c.xMin - radius), c.xMax + radius - x);
      const overlapZ = Math.min(z - (c.zMin - radius), c.zMax + radius - z);
      if (overlapX < overlapZ) {
        x = x - (c.xMin - radius) < c.xMax + radius - x ? c.xMin - radius : c.xMax + radius;
      } else {
        z = z - (c.zMin - radius) < c.zMax + radius - z ? c.zMin - radius : c.zMax + radius;
      }
    }
  }
  return { x, z };
}
