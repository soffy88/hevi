'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { styleLibraryApi, type StyleBrief } from '@/lib/api-client';

const CATEGORIES = ['', 'FA', 'FB', 'FC', 'FD', 'FE', 'FF', 'FG', 'FH', 'FI'];
const USE_CASES = ['', '社论', '儿童', '国风', '动画', '摄影', '品牌', '实验', '情感', '知识讲解', '小红书'];

export function StyleLibraryBrowser({
  initialStyleId = '',
  onPick,
}: {
  initialStyleId?: string;
  onPick?: (style: StyleBrief) => void;
}) {
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');
  const [useCase, setUseCase] = useState('');
  const [styles, setStyles] = useState<StyleBrief[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(initialStyleId);
  const timer = useRef<number | null>(null);
  const limit = 60;

  async function load(nextOffset = 0, append = false) {
    setLoading(true);
    setError('');
    try {
      const res = await styleLibraryApi.search(query, category, useCase, limit, nextOffset);
      const rows = res.styles ?? [];
      setStyles((prev) => (append ? [...prev, ...rows] : rows));
      setTotal(res.total);
      setOffset(nextOffset + rows.length);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { void load(0, false); }, 120);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, category, useCase]);

  const heading = useMemo(
    () => `${total} 个风格${category ? ` · ${category}` : ''}${useCase ? ` · ${useCase}` : ''}`,
    [total, category, useCase],
  );

  return (
    <div className="style-lib">
      <div className="style-lib__bar">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="搜索 001 / FA-001 / 水墨 / 儿童…"
          aria-label="搜索风格"
          className="style-lib__search"
        />
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="类别">
          {CATEGORIES.map((c) => <option key={c || 'all'} value={c}>{c || '全部类别'}</option>)}
        </select>
        <select value={useCase} onChange={(e) => setUseCase(e.target.value)} aria-label="用途">
          {USE_CASES.map((u) => <option key={u || 'all'} value={u}>{u || '全部用途'}</option>)}
        </select>
      </div>
      <p className="style-lib__hint">{heading} · 预览为 HEVI 自绘，不使用上游样图</p>
      {error && <p className="style-lib__error">{error}</p>}
      <div className="style-lib__grid">
        {styles.map((s) => (
          <button
            type="button"
            key={s.id}
            className={`style-lib__card${selected === s.id ? ' is-selected' : ''}`}
            onClick={() => { setSelected(s.id); onPick?.(s); }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={styleLibraryApi.previewUrl(s.id)} alt={`${s.id} ${s.name}`} loading="lazy" />
            <span className="style-lib__id">{s.id} <small>#{s.legacy_number}</small></span>
            <span className="style-lib__name" title={s.name}>{s.name}</span>
            <span className="style-lib__uses">{s.use_cases.join(' · ')}</span>
            {s.credit_removed && <span className="style-lib__credit">参考作者按政策隐去</span>}
          </button>
        ))}
      </div>
      {loading && <p className="style-lib__hint">加载中…</p>}
      {!loading && offset < total && (
        <button type="button" className="style-lib__more" onClick={() => void load(offset, true)}>
          加载更多（{offset}/{total}）
        </button>
      )}
      {!loading && !styles.length && !error && <p className="style-lib__hint">没有匹配的风格，试试编号或类别。</p>}
    </div>
  );
}
