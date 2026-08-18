/**
 * StorefrontGallery — 3D 成片店面(主组件)
 *
 * 数据源 = 现有 galleryApi(GalleryItem: thumbnail→封面, media_url→成片, category→分区)。
 * 布局:buildShelfPlan 分区 → StorefrontScene 渲染店面;点选盒子 → 详情浮层 → 播放。
 * 无数据 / 加载失败 / 空货架都有对应文案。
 */
'use client';

import { useCallback, useEffect, useState } from 'react';
import { galleryApi, USE_MOCK } from '@/lib/api-client';
import { MOCK_GALLERY } from '@/lib/mock-data';
import type { GalleryItem } from '@/types/api';
import { buildShelfPlan } from './shelfPlan';
import { StorefrontScene } from './StorefrontScene';
import { TapeDetailOverlay } from './TapeDetailOverlay';
import { PlaybackOverlay } from './PlaybackOverlay';

export function StorefrontGallery() {
  const [items, setItems] = useState<GalleryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<GalleryItem | null>(null);
  const [playing, setPlaying] = useState<GalleryItem | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const data = USE_MOCK ? MOCK_GALLERY : await galleryApi.list();
        if (live) setItems(data);
      } catch {
        if (live) setError('作品加载失败,请稍后重试');
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  const sections = buildShelfPlan(items);
  const handleSelect = useCallback((item: GalleryItem) => setSelected(item), []);
  const handleCloseDetail = useCallback(() => setSelected(null), []);
  const handlePlay = useCallback((item: GalleryItem) => {
    setPlaying(item);
    setSelected(null);
  }, []);
  const handleClosePlay = useCallback(() => setPlaying(null), []);

  return (
    <div className="hevi-store">
      <div className="hevi-store__bar">
        <div className="hevi-store__title">📼 3D 成片店面</div>
        <div className="hevi-store__hint">点选录像带查看作品 · 拖拽旋转视角 · 滚轮缩放</div>
      </div>
      {loading ? (
        <div className="hevi-store__empty">店面布置中…</div>
      ) : error ? (
        <div className="hevi-store__empty">⚠ {error}</div>
      ) : sections.length === 0 ? (
        <div className="hevi-store__empty">货架空空如也 —— 先上架几部作品吧</div>
      ) : (
        <div className="hevi-store__stage" data-testid="store-stage">
          <StorefrontScene sections={sections} selectedId={selected?.item_id ?? null} onSelect={handleSelect} />
        </div>
      )}
      <TapeDetailOverlay item={selected} onClose={handleCloseDetail} onPlay={handlePlay} />
      {playing && <PlaybackOverlay item={playing} onClose={handleClosePlay} />}
    </div>
  );
}
