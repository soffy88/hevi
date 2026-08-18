/**
 * shelfPlan 纯逻辑测试:分区分组 / 排序 / 空输入 / 未知分类兜底 / 落位计算。
 */
import { describe, it, expect } from 'vitest';
import type { GalleryItem } from '@/types/api';
import {
  buildShelfPlan,
  boxesPerShelf,
  layoutTapes,
  sectionCenterX,
  SHELF,
  CATEGORY_ORDER,
} from './shelfPlan';

function item(partial: Partial<GalleryItem> & Pick<GalleryItem, 'item_id' | 'category' | 'title'>): GalleryItem {
  return {
    prompt: '',
    gen_params: { category: partial.category },
    sort_order: 0,
    ...partial,
  };
}

describe('buildShelfPlan 分区计划', () => {
  it('按 CATEGORY_ORDER 顺序产出分区,空分区不出现', () => {
    const plan = buildShelfPlan([
      item({ item_id: 'a', category: 'image', title: '图' }),
      item({ item_id: 'b', category: 'long_video', title: '长' }),
      item({ item_id: 'c', category: 'animation', title: '动' }),
    ]);
    expect(plan.map((s) => s.category)).toEqual(['long_video', 'animation', 'image']);
  });

  it('组内按 sort_order 升序、再按标题排序', () => {
    const plan = buildShelfPlan([
      item({ item_id: 'b', category: 'short_video', title: '乙', sort_order: 2 }),
      item({ item_id: 'c', category: 'short_video', title: '丙', sort_order: 1 }),
      item({ item_id: 'a', category: 'short_video', title: '甲', sort_order: 0 }),
    ]);
    expect(plan[0].items.map((i) => i.item_id)).toEqual(['a', 'c', 'b']);
  });

  it('空输入返回空计划', () => {
    expect(buildShelfPlan([])).toEqual([]);
  });

  it('未知分类条目兜底到 image 分区(数据防御)', () => {
    const plan = buildShelfPlan([
      item({ item_id: 'x', category: 'image', title: '图' }),
      // @ts-expect-error 故意传入非法分类模拟脏数据
      item({ item_id: 'y', category: 'alien', title: '未知' }),
    ]);
    const image = plan.find((s) => s.category === 'image');
    expect(image?.items.map((i) => i.item_id)).toEqual(['x', 'y']);
  });

  it('CATEGORY_ORDER 覆盖全部合法分类', () => {
    expect(CATEGORY_ORDER).toHaveLength(5);
    expect(new Set(CATEGORY_ORDER).size).toBe(5);
  });
});

describe('layoutTapes 落位', () => {
  const section = buildShelfPlan([
    item({ item_id: '1', category: 'image', title: '一' }),
    item({ item_id: '2', category: 'image', title: '二' }),
    item({ item_id: '3', category: 'image', title: '三' }),
  ])[0];

  it('逐层自下而上、层内自左而右铺满', () => {
    const placed = layoutTapes(section);
    expect(placed).toHaveLength(3);
    // 同一层内 x 递增
    expect(placed[1].position[0]).toBeGreaterThan(placed[0].position[0]);
    // 第 1 个与第 boxesPerShelf 个分属不同层
    const per = boxesPerShelf();
    const many = buildShelfPlan(
      Array.from({ length: per + 1 }, (_, i) =>
        item({ item_id: `n${i}`, category: 'image', title: `t${i}` })),
    )[0];
    const manyPlaced = layoutTapes(many);
    expect(manyPlaced[0].position[1]).toBeLessThan(manyPlaced[per].position[1]);
  });

  it('容量外条目被丢弃', () => {
    const capacity = boxesPerShelf() * SHELF.SHELVES;
    const big = buildShelfPlan(
      Array.from({ length: capacity + 5 }, (_, i) =>
        item({ item_id: `b${i}`, category: 'image', title: `t${i}` })),
    )[0];
    expect(layoutTapes(big)).toHaveLength(capacity);
  });

  it('盒子前表面与搁板前沿平齐(z 固定)', () => {
    const placed = layoutTapes(section);
    const expectedZ = SHELF.SECTION_D / 2 - SHELF.BOX_D / 2;
    for (const p of placed) expect(p.position[2]).toBeCloseTo(expectedZ, 6);
  });
});

describe('几何常量', () => {
  it('货架段中心沿 X 等距排布', () => {
    expect(sectionCenterX(1) - sectionCenterX(0)).toBeCloseTo(SHELF.SECTION_PITCH, 6);
  });

  it('每层至少能放 1 个盒子', () => {
    expect(boxesPerShelf()).toBeGreaterThanOrEqual(1);
  });

  it('搁板高度升序且不超过货架高', () => {
    const ys = [...SHELF.SHELF_YS];
    for (let i = 1; i < ys.length; i++) expect(ys[i]).toBeGreaterThan(ys[i - 1]);
    expect(ys[ys.length - 1] + SHELF.BOX_H).toBeLessThan(SHELF.SECTION_H);
  });
});
