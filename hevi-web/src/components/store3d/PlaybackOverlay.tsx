/**
 * PlaybackOverlay — 成片播放浮层(纯 DOM)
 * media_url 按扩展名判定视频/图片;Esc 关闭,点击遮罩关闭。
 */
'use client';

import { useEffect } from 'react';
import type { GalleryItem } from '@/types/api';

export interface PlaybackOverlayProps {
  item: GalleryItem;
  onClose: () => void;
}

const VIDEO_EXT = /\.(mp4|webm|mov|m4v|ogv|m3u8)(\?.*)?$/i;

/** URL 是否指向可播放的视频(按扩展名,纯函数可测)。 */
export function isVideoUrl(url: string): boolean {
  return VIDEO_EXT.test(url.trim());
}

export function PlaybackOverlay({ item, onClose }: PlaybackOverlayProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const isVideo = item.media_url ? isVideoUrl(item.media_url) : false;
  return (
    <div className="hevi-store-play" role="dialog" aria-label={`播放:${item.title}`} onClick={onClose}>
      <div className="hevi-store-play__frame" onClick={(e) => e.stopPropagation()}>
        {isVideo ? (
          <video src={item.media_url} controls autoPlay className="hevi-store-play__media" />
        ) : (
          <img src={item.media_url} alt={item.title} className="hevi-store-play__media" />
        )}
        <div className="hevi-store-play__caption">{item.title}</div>
        <button className="hevi-store-play__close" onClick={onClose} aria-label="关闭播放">
          ✕
        </button>
      </div>
    </div>
  );
}
