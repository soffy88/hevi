/**
 * seriesAdapter 测试:剧集→货架条目映射 / 文件代理 URL / 合并去重。
 */
import { describe, it, expect } from 'vitest';
import type { Episode, GalleryItem, Series } from '@/types/api';
import { episodeMediaUrl, episodesToItems, mergeStoreItems } from './seriesAdapter';

const SERIES: Series = {
  id: 's1',
  name: '边境缉凶',
  style_preset: '赛博犯罪',
};

const EP_DONE: Episode = {
  id: 'task-1',
  status: 'completed',
  episode_index: 1,
  topic: '雨夜追车',
  result_video_path: '/data/media/task-1/out.mp4',
};

const EP_RUNNING: Episode = { id: 'task-2', status: 'running', episode_index: 2, topic: '对峙' };
const EP_NO_OUTPUT: Episode = { id: 'task-3', status: 'completed', episode_index: 3 };

describe('episodeMediaUrl 播放地址', () => {
  it('本地路径走 /api/files 代理', () => {
    expect(episodeMediaUrl('/data/media/x/out.mp4')).toBe(
      '/api/files?path=%2Fdata%2Fmedia%2Fx%2Fout.mp4',
    );
  });

  it('http(s) URL 直通', () => {
    expect(episodeMediaUrl('https://cdn.example.com/ep1.mp4')).toBe(
      'https://cdn.example.com/ep1.mp4',
    );
  });

  it('空值返回 undefined', () => {
    expect(episodeMediaUrl(undefined)).toBeUndefined();
    expect(episodeMediaUrl(null)).toBeUndefined();
    expect(episodeMediaUrl('')).toBeUndefined();
  });
});

describe('episodesToItems 剧集映射', () => {
  it('只收有成片/已完成的集,归入长视频区', () => {
    const items = episodesToItems(SERIES, [EP_DONE, EP_RUNNING, EP_NO_OUTPUT]);
    expect(items).toHaveLength(1);
    expect(items[0].category).toBe('long_video');
    expect(items[0].title).toBe('边境缉凶 · 第1集');
    expect(items[0].description).toContain('雨夜追车');
  });

  it('item_id 带 series 前缀防冲突,sort_order 排在 gallery 之后', () => {
    const items = episodesToItems(SERIES, [EP_DONE]);
    expect(items[0].item_id).toBe('series:s1:task-1');
    expect(items[0].sort_order).toBe(10001);
  });

  it('继承 Series 的 style_preset(供自动主题投票)', () => {
    const items = episodesToItems(SERIES, [EP_DONE]);
    expect(items[0].gen_params.style_preset).toBe('赛博犯罪');
    const noStyle = episodesToItems({ id: 's2', name: '无风格' }, [EP_DONE]);
    expect(noStyle[0].gen_params.style_preset).toBeUndefined();
  });
});

describe('mergeStoreItems 合并去重', () => {
  const g1: GalleryItem = {
    item_id: 'g1',
    category: 'long_video',
    title: '画廊片',
    prompt: '',
    gen_params: { category: 'long_video' },
  };
  const dup: GalleryItem = { ...g1, title: '剧集同名冲突' };
  const s1: GalleryItem = {
    item_id: 'series:s1:task-1',
    category: 'long_video',
    title: '剧集',
    prompt: '',
    gen_params: { category: 'long_video' },
  };

  it('合并且 gallery 优先(同 item_id 时取 gallery)', () => {
    const out = mergeStoreItems([g1], [dup]);
    expect(out).toHaveLength(1);
    expect(out[0].title).toBe('画廊片');
  });

  it('不同 item_id 全保留,顺序 gallery 在前 series 在后', () => {
    const out = mergeStoreItems([g1], [s1]);
    expect(out.map((i) => i.item_id)).toEqual(['g1', 'series:s1:task-1']);
  });

  it('空输入返回空数组', () => {
    expect(mergeStoreItems([], [])).toEqual([]);
  });
});
