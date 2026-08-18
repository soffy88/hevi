/**
 * seriesAdapter — Series/短剧成片 → 货架条目(纯逻辑,可测)
 *
 * episodes 接口返回 video_tasks 行,result_video_path 为本地路径;
 * 播放走既有文件代理 /api/files?path=... (与 ExplainerConsole 一致),
 * 已是 http(s) URL 则直通。gallery 优先、按 item_id 去重合并。
 */
import type { Episode, GalleryItem, Series } from '@/types/api';

/** episode 的成片路径 → 可播放 URL(本地路径走 /api/files 代理)。 */
export function episodeMediaUrl(path?: string | null): string | undefined {
  if (!path) return undefined;
  if (/^https?:\/\//i.test(path.trim())) return path.trim();
  return `/api/files?path=${encodeURIComponent(path)}`;
}

/**
 * 一个 Series 的全部剧集 → 货架条目(只收有成片/已完成的集,归入长视频区)。
 * item_id 带 series 前缀防与 gallery 冲突;sort_order 10000+ 让其排在 gallery 之后。
 */
export function episodesToItems(series: Series, episodes: Episode[]): GalleryItem[] {
  return episodes
    .filter((ep) => Boolean(ep.result_video_path))
    .map((ep) => {
      const idx = ep.episode_index ?? 0;
      return {
        item_id: `series:${series.id}:${ep.id}`,
        category: 'long_video',
        title: `${series.name} · 第${idx}集`,
        description: ep.topic ? `剧集主题:${ep.topic}` : `${series.name} 系列剧集`,
        media_url: episodeMediaUrl(ep.result_video_path),
        thumbnail_url: undefined,
        prompt: ep.topic ?? series.name,
        gen_params: {
          category: 'long_video',
          ...(series.style_preset ? { style_preset: series.style_preset } : {}),
        },
        sort_order: 10000 + idx,
      };
    });
}

/**
 * gallery 与 series 条目合并:item_id 去重,gallery 优先(series 条目其后)。
 */
export function mergeStoreItems(gallery: GalleryItem[], series: GalleryItem[]): GalleryItem[] {
  const seen = new Set<string>();
  const out: GalleryItem[] = [];
  for (const it of [...gallery, ...series]) {
    if (seen.has(it.item_id)) continue;
    seen.add(it.item_id);
    out.push(it);
  }
  return out;
}
