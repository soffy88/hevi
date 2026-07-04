/**
 * ShowcaseWall — 展示墙(§4 独立页)
 * 全分区官方精选作品墙:顶部分区标签过滤 + 作品网格。公开(无需登录),冷启动用官方示例。
 * 复用首页 Gallery 的卡片样式(hevi-gallery*),区别是整页、含分区标签、卡片直链示例媒体。
 */
'use client';

import { useState, useEffect, type FormEvent } from 'react';
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

const EMPTY_FORM = { category: 'long_video' as GalleryCategory, title: '', media_url: '', description: '', prompt: '' };

export function ShowcaseWall() {
  const [items, setItems] = useState<GalleryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<GalleryCategory | 'all'>('all');
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

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

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!form.title.trim()) { setMsg('请填标题'); return; }
    setSubmitting(true); setMsg(null);
    try {
      const created = await galleryApi.create({
        category: form.category,
        title: form.title.trim(),
        media_url: form.media_url.trim() || undefined,
        description: form.description.trim() || undefined,
        prompt: form.prompt.trim() || undefined,
      });
      setItems(prev => [created, ...prev]);
      setForm(EMPTY_FORM); setShowForm(false);
      setMsg('已上墙 ✓');
    } catch (err) {
      setMsg(err instanceof Error && err.message === 'NOT_AUTHENTICATED' ? '请先登录再投稿' : '投稿失败,请重试');
    } finally { setSubmitting(false); }
  }

  const filtered = tab === 'all' ? items : items.filter(i => i.category === tab);

  return (
    <div className="hevi-gallery hevi-showcase">
      <div className="hevi-showcase__bar">
        <div className="hevi-gallery__head">展示墙 · 官方精选作品</div>
        <button className="hevi-showcase__submit-btn" onClick={() => { setShowForm(v => !v); setMsg(null); }}>
          {showForm ? '收起' : '+ 投稿'}
        </button>
      </div>
      {showForm && (
        <form className="hevi-showcase__form" onSubmit={submit}>
          <div className="hevi-showcase__form-row">
            <select value={form.category} onChange={e => setForm({ ...form, category: e.target.value as GalleryCategory })}>
              {TABS.filter(t => t.key !== 'all').map(t => <option key={t.key} value={t.key}>{t.label}</option>)}
            </select>
            <input placeholder="标题 *" value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} />
          </div>
          <input placeholder="作品链接 media_url(视频/图片)" value={form.media_url} onChange={e => setForm({ ...form, media_url: e.target.value })} />
          <input placeholder="一句话简介(可选)" value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} />
          <input placeholder="生成 prompt(可选)" value={form.prompt} onChange={e => setForm({ ...form, prompt: e.target.value })} />
          <button type="submit" disabled={submitting}>{submitting ? '提交中…' : '上墙'}</button>
        </form>
      )}
      {msg && <div className="hevi-showcase__msg">{msg}</div>}
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
