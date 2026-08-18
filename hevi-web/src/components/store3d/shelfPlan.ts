/**
 * shelfPlan — 3D 店面货架分区计划(纯逻辑,可单测)
 *
 * 把画廊条目(GalleryItem)按分区归类、排序,产出 StoreSection 列表;
 * 每个分区对应店里一段货架(分区标牌 + 该区全部成片盒子)。
 * 与渲染解耦:本模块不依赖 three.js / React,布局几何在组件层消费。
 */
import type { GalleryItem, GalleryCategory } from '@/types/api';

/** 分区元信息:标牌文案、图标、主题色(封面/标牌/灯带共用)。 */
export interface CategoryMeta {
  label: string;
  icon: string;
  color: string;
}

export const CATEGORY_META: Record<GalleryCategory, CategoryMeta> = {
  long_video: { label: '长视频', icon: '▶', color: '#1e40af' },
  short_video: { label: '短视频', icon: '▷', color: '#c2410c' },
  avatar_narration: { label: '数字人', icon: '☺', color: '#7c3aed' },
  animation: { label: '动画', icon: '✦', color: '#0e7490' },
  image: { label: '图片', icon: '▢', color: '#15803d' },
};

/** 店面沿墙的分区顺序(决定货架段的左右排布)。 */
export const CATEGORY_ORDER: GalleryCategory[] = [
  'long_video',
  'short_video',
  'avatar_narration',
  'animation',
  'image',
];

export interface StoreSection {
  category: GalleryCategory;
  label: string;
  icon: string;
  color: string;
  items: GalleryItem[];
}

/**
 * 把条目按分区归类,组内按 sort_order 升序、再按标题排序。
 * 空分区不出现在计划里;未知分类条目归入 image 兜底(数据防御)。
 */
export function buildShelfPlan(items: GalleryItem[]): StoreSection[] {
  const byCat = new Map<GalleryCategory, GalleryItem[]>();
  for (const item of items) {
    const cat: GalleryCategory = item.category in CATEGORY_META ? item.category : 'image';
    const list = byCat.get(cat) ?? [];
    list.push(item);
    byCat.set(cat, list);
  }
  const sections: StoreSection[] = [];
  for (const cat of CATEGORY_ORDER) {
    const list = byCat.get(cat);
    if (!list || list.length === 0) continue;
    list.sort(
      (a, b) =>
        (a.sort_order ?? 0) - (b.sort_order ?? 0) ||
        a.title.localeCompare(b.title, 'zh-Hans-CN'),
    );
    const meta = CATEGORY_META[cat];
    sections.push({ category: cat, label: meta.label, icon: meta.icon, color: meta.color, items: list });
  }
  return sections;
}

/** 货架几何常量(组件层与测试共用,单位:米,three.js 世界坐标)。 */
export const SHELF = {
  /** 单个货架段宽度(沿墙 X 方向)。 */
  SECTION_W: 3.6,
  /** 货架段总高。 */
  SECTION_H: 2.4,
  /** 货架深度(Z 方向,盒脊到背板)。 */
  SECTION_D: 0.5,
  /** 搁板层数(不含地面)。 */
  SHELVES: 3,
  /** 搁板 Y 高度(从地面起)。 */
  SHELF_YS: [0.85, 1.5, 2.05] as const,
  /** 相邻货架段的中心间距(段宽 + 段间过道)。 */
  SECTION_PITCH: 4.2,
  /** 录像带盒正面宽。 */
  BOX_W: 0.56,
  /** 录像带盒正面高。 */
  BOX_H: 0.3,
  /** 录像带盒厚度。 */
  BOX_D: 0.12,
  /** 盒子间距。 */
  BOX_GAP: 0.1,
  /** 货架段起点 X(最左段中心)。 */
  FIRST_SECTION_X: -8.4,
} as const;

/**
 * 计算某分区第 i 段货架的中心 X 坐标。
 */
export function sectionCenterX(sectionIndex: number): number {
  return SHELF.FIRST_SECTION_X + sectionIndex * SHELF.SECTION_PITCH;
}

/**
 * 计算某层搁板能容纳的盒子数(向下取整,最小 1)。
 */
export function boxesPerShelf(): number {
  const usable = SHELF.SECTION_W - 0.3; // 两端留边
  return Math.max(1, Math.floor(usable / (SHELF.BOX_W + SHELF.BOX_GAP)));
}

/** 货架内一个盒子的落位。 */
export interface PlacedTape {
  item: GalleryItem;
  /** 局部坐标(货架段原点为段中心)。 */
  position: [number, number, number];
}

/**
 * 分区条目 → 货架落位:从第一层(最低)起从左到右铺,铺满一层上一层。
 * 超出货架容量(3 层 × 每层 boxesPerShelf())的条目丢弃(MVP 不翻页)。
 */
export function layoutTapes(section: StoreSection): PlacedTape[] {
  const per = boxesPerShelf();
  const capacity = per * SHELF.SHELVES;
  const result: PlacedTape[] = [];
  section.items.slice(0, capacity).forEach((item, idx) => {
    const shelf = Math.floor(idx / per);
    const col = idx % per;
    const y = SHELF.SHELF_YS[shelf] + 0.025 + SHELF.BOX_H / 2; // 搁板顶 + 盒子半高
    const x = -SHELF.SECTION_W / 2 + 0.15 + SHELF.BOX_W / 2 + col * (SHELF.BOX_W + SHELF.BOX_GAP);
    const z = SHELF.SECTION_D / 2 - SHELF.BOX_D / 2; // 盒子前表面与搁板前沿平齐
    result.push({ item, position: [x, y, z] });
  });
  return result;
}
