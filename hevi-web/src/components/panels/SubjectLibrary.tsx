/**
 * SubjectLibrary — 主体库侧栏(4 类:character/portrait/product/scene)
 * 条目可拖入画布节点(subject_id 作为参考)。
 */
'use client';

import { useEffect, useState } from 'react';
import type { Subject, SubjectKind } from '@/types/api';
import { subjectApi, USE_MOCK } from '@/lib/api-client';
import { MOCK_SUBJECTS } from '@/lib/mock-data';

const KINDS: { id: SubjectKind | 'all'; label: string }[] = [
  { id: 'all',       label: '全部' },
  { id: 'character', label: '角色' },
  { id: 'portrait',  label: '人像' },
  { id: 'product',   label: '产品' },
  { id: 'scene',     label: '场景' },
];

const KIND_ICON: Record<SubjectKind, string> = {
  character: '☻', portrait: '◐', product: '◫', scene: '⛰',
};

export function SubjectLibrary({ onPick }: { onPick?: (s: Subject) => void }) {
  const [items, setItems] = useState<Subject[]>([]);
  const [kind, setKind]   = useState<SubjectKind | 'all'>('all');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState('');
  const [addBusy, setAddBusy] = useState(false);

  const reload = async () => {
    try {
      const data = USE_MOCK
        ? MOCK_SUBJECTS
        : await subjectApi.list(kind === 'all' ? undefined : kind, query || undefined);
      setItems(data);
    } catch { if (USE_MOCK) setItems(MOCK_SUBJECTS); }
  };

  useEffect(() => {
    let live = true;
    (async () => {
      setLoading(true);
      try {
        const data = USE_MOCK
          ? MOCK_SUBJECTS
          : await subjectApi.list(kind === 'all' ? undefined : kind, query || undefined);
        if (live) setItems(data);
      } catch { if (live) setItems(USE_MOCK ? MOCK_SUBJECTS : []); }
      finally { if (live) setLoading(false); }
    })();
    return () => { live = false; };
  }, [kind, query]);

  async function onQuickCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setAddBusy(true);
    try {
      await subjectApi.create({ kind: kind === 'all' ? 'character' : kind, name: newName.trim() });
      setNewName(''); setShowAdd(false); await reload();
    } catch { /* 静默失败,侧栏面积小,不放错误文案 */ }
    finally { setAddBusy(false); }
  }

  const filtered = items.filter(s =>
    (kind === 'all' || s.kind === kind) &&
    (!query || s.name.includes(query))
  );

  return (
    <div className="hevi-subjects">
      <div className="hevi-subjects__head">
        <span className="hevi-side-title">主体库</span>
      </div>

      <input
        className="hevi-subjects__search"
        placeholder="搜索主体…"
        value={query}
        onChange={e => setQuery(e.target.value)}
      />

      <div className="hevi-subjects__tabs">
        {KINDS.map(k => (
          <button key={k.id} type="button"
            className="hevi-subjects__tab"
            data-active={kind === k.id ? 'true' : undefined}
            onClick={() => setKind(k.id)}>
            {k.label}
          </button>
        ))}
      </div>

      <div className="hevi-subjects__list">
        {loading ? (
          <div className="hevi-side-empty">加载中…</div>
        ) : filtered.length === 0 ? (
          <div className="hevi-side-empty">暂无主体</div>
        ) : filtered.map(s => (
          <button key={s.subject_id} type="button"
            className="hevi-subject-item"
            draggable
            onDragStart={e => e.dataTransfer.setData('application/hevi-subject', s.subject_id)}
            onClick={() => onPick?.(s)}>
            <span className="hevi-subject-item__icon">{KIND_ICON[s.kind]}</span>
            <span className="hevi-subject-item__name">{s.name}</span>
            <span className="hevi-subject-item__kind">{s.kind}</span>
          </button>
        ))}
      </div>

      {showAdd ? (
        <form className="hevi-subjects__add-form" onSubmit={onQuickCreate}>
          <input
            className="hevi-subjects__add-input"
            placeholder="姓名"
            autoFocus
            value={newName}
            onChange={e => setNewName(e.target.value)}
          />
          <div className="hevi-subjects__add-actions">
            <button type="submit" className="hevi-subjects__add-confirm" disabled={addBusy}>
              {addBusy ? '创建中…' : '创建'}
            </button>
            <button type="button" onClick={() => setShowAdd(false)}>取消</button>
          </div>
        </form>
      ) : (
        <button type="button" className="hevi-subjects__add" onClick={() => setShowAdd(true)}>
          + 新建主体
        </button>
      )}
    </div>
  );
}
