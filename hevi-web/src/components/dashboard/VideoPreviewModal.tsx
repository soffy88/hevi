/** 沉浸式视频放映室: 深色遮罩 + 原生 video 播放成片。 */

'use client';

import { useCallback, useEffect } from 'react';

export interface VideoPreviewModalProps {
  taskId: string;
  title: string;
  src: string;
  onClose: () => void;
}

export function VideoPreviewModal({ taskId, title, src, onClose }: VideoPreviewModalProps) {
  // ESC 关闭 + 阻止背景滚动。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  const stopPropagation = useCallback((e: React.MouseEvent) => e.stopPropagation(), []);

  return (
    <div
      className="vmodal__backdrop"
      role="dialog"
      aria-modal="true"
      aria-label={`任务 ${taskId} 成片预览`}
      onClick={onClose}
    >
      <div className="vmodal__panel" onClick={stopPropagation}>
        <header className="vmodal__head">
          <div>
            <p className="vmodal__eyebrow">HEVI · LITE 成片</p>
            <h3 className="vmodal__title">{title}</h3>
          </div>
          <button type="button" className="vmodal__close" onClick={onClose} aria-label="关闭预览">✕</button>
        </header>
        <video
          controls
          autoPlay
          playsInline
          className="vmodal__video"
          src={src}
        >
          当前浏览器不支持视频播放, 请<a href={src} download>下载成片</a>。
        </video>
      </div>
    </div>
  );
}
