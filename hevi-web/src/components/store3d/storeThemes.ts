/**
 * storeThemes — 店面主题(纯逻辑,可测)
 *
 * 四个主题模拟录像带租赁店的不同年代/风格装修:
 * retro90s(默认暖木)/ neon2000(冷灰霓虹)/ warmVHS(琥珀暖调)/ cinematic(黑白电影感)。
 * 自动主题 = 从货架条目 gen_params.style_preset 投票推断;也可手动循环。
 */
import type { GalleryItem } from '@/types/api';

export type StoreThemeId = 'retro90s' | 'neon2000' | 'warmVHS' | 'cinematic';

export interface StoreTheme {
  id: StoreThemeId;
  label: string;
  icon: string;
  /** 货架主木色 */
  wood: string;
  /** 货架深木色(背板) */
  woodDark: string;
  /** 墙面 */
  wall: string;
  /** 地面 */
  floor: string;
  /** 环境光 */
  ambient: string;
  /** 主灯光色 */
  light: string;
  /** 灯带/标牌点缀色(霓虹主题的冷色强调) */
  accent: string;
}

export const STORE_THEMES: Record<StoreThemeId, StoreTheme> = {
  retro90s: {
    id: 'retro90s',
    label: '九十年代',
    icon: '🌆',
    wood: '#5b4632',
    woodDark: '#40321f',
    wall: '#3b2f23',
    floor: '#46382b',
    ambient: '#ffdcb8',
    light: '#ffd9a0',
    accent: '#ffcf8e',
  },
  neon2000: {
    id: 'neon2000',
    label: '千禧霓虹',
    icon: '🌃',
    wood: '#33404f',
    woodDark: '#232d38',
    wall: '#1a2330',
    floor: '#262f3d',
    ambient: '#b8c8ff',
    light: '#9fb8ff',
    accent: '#ff5fd0',
  },
  warmVHS: {
    id: 'warmVHS',
    label: '琥珀暖调',
    icon: '🎞️',
    wood: '#6b4a2b',
    woodDark: '#4a3018',
    wall: '#4a3520',
    floor: '#573d22',
    ambient: '#ffd2a1',
    light: '#ffc07a',
    accent: '#ff9e3d',
  },
  cinematic: {
    id: 'cinematic',
    label: '黑白电影',
    icon: '🎬',
    wood: '#3c3c3c',
    woodDark: '#262626',
    wall: '#202020',
    floor: '#2b2b2b',
    ambient: '#e8e8e8',
    light: '#ffffff',
    accent: '#c8c8c8',
  },
};

export const THEME_ORDER: StoreThemeId[] = ['retro90s', 'neon2000', 'warmVHS', 'cinematic'];

/** style_preset → 主题关键词映射(自动主题投票用)。 */
const PRESET_THEME_KEYS: Record<StoreThemeId, RegExp> = {
  retro90s: /复古|怀旧|九十|retro|vintage|90s/i,
  neon2000: /霓虹|赛博|未来|科幻|neon|cyber|futur/i,
  warmVHS: /暖|治愈|温馨|胶片|vhs|warm|film/i,
  cinematic: /黑白|电影|暗黑|黑色|cinema|noir|dark|mono/i,
};

/**
 * 单个 style_preset → 匹配的主题(无匹配返回 null)。
 */
export function themeForPreset(preset?: string | null): StoreThemeId | null {
  if (!preset) return null;
  for (const id of THEME_ORDER) {
    if (PRESET_THEME_KEYS[id].test(preset)) return id;
  }
  return null;
}

/**
 * 从货架条目投票推断主题:统计每个条目 style_preset 匹配的主题,
 * 取票数最高者;平票取 THEME_ORDER 靠前者;全部无匹配 → retro90s。
 */
export function inferTheme(items: GalleryItem[]): StoreThemeId {
  const votes: Record<StoreThemeId, number> = {
    retro90s: 0,
    neon2000: 0,
    warmVHS: 0,
    cinematic: 0,
  };
  for (const it of items) {
    const t = themeForPreset(it.gen_params?.style_preset);
    if (t) votes[t] += 1;
  }
  let best: StoreThemeId = 'retro90s';
  let bestVotes = 0;
  for (const id of THEME_ORDER) {
    if (votes[id] > bestVotes) {
      best = id;
      bestVotes = votes[id];
    }
  }
  return best;
}

/** 下一个主题(手动循环:auto → 依次主题 → 回到 auto)。 */
export function nextTheme(current: StoreThemeId | 'auto'): StoreThemeId | 'auto' {
  if (current === 'auto') return THEME_ORDER[0];
  const idx = THEME_ORDER.indexOf(current);
  if (idx === -1 || idx === THEME_ORDER.length - 1) return 'auto';
  return THEME_ORDER[idx + 1];
}
