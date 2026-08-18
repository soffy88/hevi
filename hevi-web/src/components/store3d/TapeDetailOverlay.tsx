/**
 * TapeDetailOverlay — 选中录像带的详情浮层(纯 DOM)
 * 展示封面/分区/标题/描述/prompt,提供播放与关闭。测试友好(无 three 依赖)。
 */
'use client';

import type { GalleryItem } from '@/types/api';
import { CATEGORY_META } from './shelfPlan';

export interface TapeDetailOverlayProps {
  item: GalleryItem | null;
  onClose: () => void;
  onPlay: (item: GalleryItem) => void;
}

export function TapeDetailOverlay({ item, onClose, onPlay }: TapeDetailOverlayProps) {
  if (!item) return null;
  const meta = CATEGORY_META[item.category in CATEGORY_META ? item.category : 'image'];
  return (
    <div className="hevi-store-detail" role="dialog" aria-label={`作品详情:${item.title}`}>
      <div className="hevi-store-detail__card">
        <div className="hevi-store-detail__thumb">
          {item.thumbnail_url ? (
            <img src={item.thumbnail_url} alt={item.title} />
          ) : (
            <span className="hevi-store-detail__icon" style={{ background: meta.color }}>
              {meta.icon}
            </span>
          )}
        </div>
        <div className="hevi-store-detail__body">
          <span className="hevi-store-detail__badge" style={{ background: meta.color }}>
            {meta.label}
          </span>
          <h3 className="hevi-store-detail__title">{item.title}</h3>
          {item.description && <p className="hevi-store-detail__desc">{item.description}</p>}
          {item.prompt && <p className="hevi-store-detail__prompt">{item.prompt}</p>}
          <div className="hevi-store-detail__actions">
            {item.media_url && (
              <button className="hevi-store-detail__play" onClick={() => onPlay(item)}>
                ▶ 播放
              </button>
            )}
            <button className="hevi-store-detail__close" onClick={onClose}>
              关闭
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
