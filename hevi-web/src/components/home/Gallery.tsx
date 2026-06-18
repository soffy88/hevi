/**
 * Gallery — 首页作品画廊(§4)
 * 5 分区作品网格,每卡缩略图+标题+"用同款"。
 * 公开(无需登录),冷启动用官方示例。空状态友好提示。
 */
'use client';

import { useState, useEffect } from 'react';
import { galleryApi, USE_MOCK } from '@/lib/api-client';
import { MOCK_GALLERY } from '@/lib/mock-data';
import type { GalleryItem, GalleryCategory } from '@/types/api';

const CATEGORY_ICON: Record<GalleryCategory, string> = {
  long_video: '▶', short_video: '▷', avatar_narration: '☺', animation: '✦', image: '▢',
};

export function Gallery({
  category,
  onUseTemplate,
}: {
  category: GalleryCategory;
  onUseTemplate: (item: GalleryItem) => void;
}) {
  const [items, setItems] = useState<GalleryItem[]>([]);
  const [loading, setLoading] = useState(true);

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

  const filtered = items.filter(i => i.category === category);

  return (
    <div className="hevi-gallery">
      <div className="hevi-gallery__head">官方精选 · 看看能做什么</div>
      {loading ? (
        <div className="hevi-gallery__empty">加载中…</div>
      ) : filtered.length === 0 ? (
        <div className="hevi-gallery__empty">该分区暂无示例作品,试试上方输入框直接生成</div>
      ) : (
        <div className="hevi-gallery__grid">
          {filtered.map(item => (
            <div key={item.item_id} className="hevi-gallery-card">
              <div className="hevi-gallery-card__thumb">
                {item.thumbnail_url
                  ? <img src={item.thumbnail_url} alt={item.title} />
                  : <span className="hevi-gallery-card__placeholder">{CATEGORY_ICON[item.category]}</span>}
              </div>
              <div className="hevi-gallery-card__body">
                <div className="hevi-gallery-card__title">{item.title}</div>
                {item.description && <div className="hevi-gallery-card__desc">{item.description}</div>}
                <button className="hevi-gallery-card__use" onClick={() => onUseTemplate(item)}>用同款</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
