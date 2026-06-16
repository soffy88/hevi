/**
 * AssetLibrary — 模板库 + 音效库(后端 PENDING,前端预留)
 * 文档 1.7:后端未单独建,前端先占位。
 */
'use client';

import { useState, useEffect } from 'react';
import { assetApi, USE_MOCK } from '@/lib/api-client';

type Tab = 'template' | 'bgm';

const MOCK_TEMPLATES = [
  { id: 'tpl-1', name: '产品宣传 · 竖屏', desc: '15s 快剪' },
  { id: 'tpl-2', name: '教学讲解 · 横屏', desc: '分镜+配音' },
  { id: 'tpl-3', name: '社媒短视频', desc: '9:16 节奏感' },
];

const MOCK_BGM = [
  { id: 'bgm-1', name: '轻快 · Upbeat', dur: '2:14' },
  { id: 'bgm-2', name: '舒缓 · Calm', dur: '3:02' },
  { id: 'bgm-3', name: '紧张 · Tension', dur: '1:48' },
];

export function AssetLibrary() {
  const [tab, setTab] = useState<Tab>('template');
  const [templates, setTemplates] = useState(USE_MOCK ? MOCK_TEMPLATES : [] as { id: string; name: string; desc?: string }[]);
  const [bgm, setBgm] = useState(USE_MOCK ? MOCK_BGM : [] as { id: string; name: string; dur?: string }[]);

  useEffect(() => {
    if (USE_MOCK) return;
    assetApi.templates().then(setTemplates).catch(() => setTemplates([]));
    assetApi.audio().then(setBgm).catch(() => setBgm([]));
  }, []);

  return (
    <div className="hevi-assets">
      <div className="hevi-assets__tabs">
        <button type="button" className="hevi-assets__tab"
          data-active={tab === 'template' ? 'true' : undefined}
          onClick={() => setTab('template')}>模板库</button>
        <button type="button" className="hevi-assets__tab"
          data-active={tab === 'bgm' ? 'true' : undefined}
          onClick={() => setTab('bgm')}>音效库</button>
      </div>

      <div className="hevi-assets__hint">后端就绪后接真实数据</div>

      {tab === 'template' ? (
        <div className="hevi-assets__list">
          {templates.map(t => (
            <div key={t.id} className="hevi-asset-item">
              <span className="hevi-asset-item__name">{t.name}</span>
              <span className="hevi-asset-item__meta">{t.desc}</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="hevi-assets__list">
          {bgm.map(b => (
            <div key={b.id} className="hevi-asset-item">
              <span className="hevi-asset-item__name">♫ {b.name}</span>
              <span className="hevi-asset-item__meta">{b.dur}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
