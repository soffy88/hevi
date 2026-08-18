/**
 * StorefrontGallery — 3D 成片店面(主组件)
 *
 * 数据源 = galleryApi(thumbnail→封面, media_url→成片, category→分区)+
 *          seriesApi(剧集成片并入长视频区,未登录/失败静默跳过)。
 * 三种模式:浏览(orbit)/行走(walk)/2.5D;主题:自动投票或手动循环。
 * 点选盒子 → 拿起展示 + 详情浮层;3D 里点展示盒翻面看背封;播放走浮层。
 */
'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { galleryApi, seriesApi, USE_MOCK } from '@/lib/api-client';
import { MOCK_GALLERY } from '@/lib/mock-data';
import type { Episode, GalleryItem, Series } from '@/types/api';
import { buildShelfPlan } from './shelfPlan';
import {
  StorefrontScene,
  type StoreMode,
} from './StorefrontScene';
import { TapeDetailOverlay } from './TapeDetailOverlay';
import { PlaybackOverlay } from './PlaybackOverlay';
import { STORE_THEMES, inferTheme, nextTheme, type StoreTheme, type StoreThemeId } from './storeThemes';
import { episodesToItems, mergeStoreItems } from './seriesAdapter';

type ThemeChoice = StoreThemeId | 'auto';

export function StorefrontGallery() {
  const [items, setItems] = useState<GalleryItem[]>([]);
  const [seriesCount, setSeriesCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<GalleryItem | null>(null);
  const [playing, setPlaying] = useState<GalleryItem | null>(null);
  const [mode, setMode] = useState<StoreMode>('orbit');
  const [themeChoice, setThemeChoice] = useState<ThemeChoice>('auto');
  const [facingBack, setFacingBack] = useState(false);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        if (USE_MOCK) {
          if (live) setItems(MOCK_GALLERY);
          return;
        }
        const gallery = await galleryApi.list(); // 主数据源:失败即报错
        const seriesList = await seriesApi.list().catch(() => [] as Series[]); // 辅助:静默跳过
        const seriesItems = (
          await Promise.all(
            seriesList.map(async (s) => {
              const eps = await seriesApi.episodes(s.id).catch(() => [] as Episode[]);
              return episodesToItems(s, eps);
            }),
          )
        ).flat();
        if (!live) return;
        setItems(mergeStoreItems(gallery, seriesItems));
        setSeriesCount(seriesItems.length);
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
  const theme: StoreTheme = useMemo(
    () => (themeChoice === 'auto' ? STORE_THEMES[inferTheme(items)] : STORE_THEMES[themeChoice]),
    [themeChoice, items],
  );

  const handleSelect = useCallback((item: GalleryItem) => {
    setSelected(item);
    setFacingBack(false);
  }, []);
  const handleCloseDetail = useCallback(() => setSelected(null), []);
  const handlePlay = useCallback((item: GalleryItem) => {
    setPlaying(item);
    setSelected(null);
  }, []);
  const handleClosePlay = useCallback(() => setPlaying(null), []);
  const handleFlip = useCallback(() => setFacingBack((f) => !f), []);

  const themeLabel =
    themeChoice === 'auto'
      ? `自动主题(${STORE_THEMES[inferTheme(items)].label})`
      : STORE_THEMES[themeChoice].label;

  const itemTotal = items.length;

  return (
    <div className="hevi-store">
      <div className="hevi-store__bar">
        <div className="hevi-store__title">📼 3D 成片店面</div>
        <div className="hevi-store__hint">
          {mode === 'orbit' && '拖拽旋转视角 · 滚轮缩放 · 点选录像带查看作品'}
          {mode === 'walk' && '点击画面锁定鼠标 · WASD/方向键行走 · 走到货架前点选录像带'}
          {mode === '25d' && '2.5D 固定机位 · 左右平移浏览货架 · 点选录像带查看作品'}
        </div>
      </div>
      <div className="hevi-store__controls">
        <div className="hevi-store__modes" role="group" aria-label="浏览模式">
          <button data-on={mode === 'orbit'} onClick={() => setMode('orbit')}>🔍 浏览</button>
          <button data-on={mode === 'walk'} onClick={() => setMode('walk')}>🚶 行走</button>
          <button data-on={mode === '25d'} onClick={() => setMode('25d')}>📺 2.5D</button>
        </div>
        <button
          className="hevi-store__theme"
          onClick={() => setThemeChoice((t) => nextTheme(t))}
          title="切换店面主题"
        >
          🎨 {themeLabel}
        </button>
        <span className="hevi-store__stat" data-testid="store-stat">
          货架 {itemTotal} 部作品{seriesCount > 0 ? ` · 含 ${seriesCount} 部剧集` : ''}
        </span>
      </div>
      {loading ? (
        <div className="hevi-store__empty">店面布置中…</div>
      ) : error ? (
        <div className="hevi-store__empty">⚠ {error}</div>
      ) : sections.length === 0 ? (
        <div className="hevi-store__empty">货架空空如也 —— 先上架几部作品吧</div>
      ) : (
        <div className="hevi-store__stage" data-testid="store-stage">
          <StorefrontScene
            key={mode}
            sections={sections}
            selectedId={selected?.item_id ?? null}
            selectedItem={selected}
            facingBack={facingBack}
            theme={theme}
            mode={mode}
            onSelect={handleSelect}
            onFlip={handleFlip}
          />
          {mode === 'walk' && (
            <div className="hevi-store__walktip">🚶 点击画面进入行走 · Esc 退出</div>
          )}
        </div>
      )}
      <TapeDetailOverlay item={selected} onClose={handleCloseDetail} onPlay={handlePlay} />
      {playing && <PlaybackOverlay item={playing} onClose={handleClosePlay} />}
    </div>
  );
}
