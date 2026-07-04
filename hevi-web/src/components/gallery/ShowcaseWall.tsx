/**
 * ShowcaseWall — 展示墙(§4 独立页)
 * 全分区官方精选作品墙:顶部分区标签过滤 + 作品网格。公开(无需登录),冷启动用官方示例。
 * 复用首页 Gallery 的卡片样式(hevi-gallery*),区别是整页、含分区标签、卡片直链示例媒体。
 */
'use client';

import { useState, useEffect } from 'react';
import { galleryApi, USE_MOCK } from '@/lib/api-client';
import { MOCK_GALLERY } from '@/lib/mock-data';
import type { GalleryItem, GalleryCategory } from '@/types/api';

const CATEGORY_ICON: Record<GalleryCategory, string> = {
  long_video: '▶', short_video: '▷', avatar_narration: '☺', animation: '✦', image: '▢',
};

const TABS: { key: GalleryCategory | 'all'; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'long_video', label: '长视频' },
  { key: 'short_video', label: '短视频' },
  { key: 'avatar_narration', label: '数字人' },
  { key: 'animation', label: '动画' },
  { key: 'image', label: '图片' },
];

export function ShowcaseWall() {
  const [items, setItems] = useState<GalleryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<GalleryCategory | 'all'>('all');

  useEffect(() => {
    let live = true;
    (async () => {
      setLoading(true);
      try {
        const data = USE_MOCK ? MOCK_GALLERY : await galleryApi.list();
        if (live) setItems(data);
      } catch { if (live) setItems(USE_MOCK ? MOCK_GALLERY : []); }
      finally { if (live) setLoading(false); }
    })();
    return () => { live = false; };
  }, []);

  const filtered = tab === 'all' ? items : items.filter(i => i.category === tab);

  return (
    <div className="hevi-gallery hevi-showcase">
      <div className="hevi-gallery__head">展示墙 · 官方精选作品</div>
      <div className="hevi-showcase__tabs">
        {TABS.map(t => (
          <button
            key={t.key}
            className="hevi-showcase__tab"
            data-active={tab === t.key ? 'true' : undefined}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      {loading ? (
        <div className="hevi-gallery__empty">加载中…</div>
      ) : filtered.length === 0 ? (
        <div className="hevi-gallery__empty">该分区暂无示例作品</div>
      ) : (
        <div className="hevi-gallery__grid">
          {filtered.map(item => {
            const card = (
              <>
                <div className="hevi-gallery-card__thumb">
                  {item.thumbnail_url
                    ? <img src={item.thumbnail_url} alt={item.title} />
                    : <span className="hevi-gallery-card__placeholder">{CATEGORY_ICON[item.category]}</span>}
                </div>
                <div className="hevi-gallery-card__body">
                  <div className="hevi-gallery-card__title">{item.title}</div>
                  {item.description && <div className="hevi-gallery-card__desc">{item.description}</div>}
                </div>
              </>
            );
            return item.media_url ? (
              <a
                key={item.item_id}
                className="hevi-gallery-card"
                href={item.media_url}
                target="_blank"
                rel="noreferrer"
              >
                {card}
              </a>
            ) : (
              <div key={item.item_id} className="hevi-gallery-card">{card}</div>
            );
          })}
        </div>
      )}
    </div>
  );
}
