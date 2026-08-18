/**
 * storeThemes 测试:关键词匹配 / 自动投票 / 手动循环 / 主题表完整性。
 */
import { describe, it, expect } from 'vitest';
import type { GalleryItem } from '@/types/api';
import {
  STORE_THEMES,
  THEME_ORDER,
  themeForPreset,
  inferTheme,
  nextTheme,
  type StoreThemeId,
} from './storeThemes';

function item(style?: string): GalleryItem {
  return {
    item_id: 'x',
    category: 'image',
    title: 't',
    prompt: '',
    gen_params: { category: 'image', ...(style ? { style_preset: style } : {}) },
  };
}

describe('themeForPreset 关键词匹配', () => {
  it('中英文关键词命中对应主题', () => {
    expect(themeForPreset('赛博朋克')).toBe('neon2000');
    expect(themeForPreset('复古胶片')).toBe('retro90s');
    expect(themeForPreset('温馨治愈')).toBe('warmVHS');
    expect(themeForPreset('黑白电影感')).toBe('cinematic');
    expect(themeForPreset('neon')).toBe('neon2000');
    expect(themeForPreset('vintage')).toBe('retro90s');
  });

  it('无匹配 / 空值返回 null', () => {
    expect(themeForPreset('科普')).toBeNull();
    expect(themeForPreset(undefined)).toBeNull();
    expect(themeForPreset(null)).toBeNull();
    expect(themeForPreset('')).toBeNull();
  });
});

describe('inferTheme 自动投票', () => {
  it('空货架回退默认 retro90s', () => {
    expect(inferTheme([])).toBe('retro90s');
  });

  it('多数票决定主题', () => {
    const items = [item('科普'), item('赛博朋克'), item('霓虹夜城'), item('复古')];
    expect(inferTheme(items)).toBe('neon2000');
  });

  it('平票时取 THEME_ORDER 靠前主题', () => {
    expect(inferTheme([item('黑白'), item('赛博')])).toBe('neon2000');
  });

  it('无 style_preset 的条目不投票', () => {
    expect(inferTheme([item(undefined), item('科普')])).toBe('retro90s');
  });
});

describe('nextTheme 手动循环', () => {
  it('auto → 首个主题 → … → 末尾 → 回到 auto', () => {
    expect(nextTheme('auto')).toBe(THEME_ORDER[0]);
    for (let i = 0; i < THEME_ORDER.length - 1; i++) {
      expect(nextTheme(THEME_ORDER[i])).toBe(THEME_ORDER[i + 1]);
    }
    expect(nextTheme(THEME_ORDER[THEME_ORDER.length - 1])).toBe('auto');
  });
});

describe('主题表完整性', () => {
  it('每个主题都有完整配色字段', () => {
    const keys: (keyof (typeof STORE_THEMES)[StoreThemeId])[] = [
      'wood', 'woodDark', 'wall', 'floor', 'ambient', 'light', 'accent',
    ];
    for (const id of THEME_ORDER) {
      for (const k of keys) {
        expect(STORE_THEMES[id][k], `${id}.${k}`).toBeTruthy();
      }
    }
  });

  it('THEME_ORDER 无重复', () => {
    expect(new Set(THEME_ORDER).size).toBe(THEME_ORDER.length);
  });
});
