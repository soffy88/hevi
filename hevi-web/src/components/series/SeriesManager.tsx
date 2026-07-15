/**
 * SeriesManager — 系列 + 风格包管理(§3 L2)
 * 系列:建/列/选 → 看分集 → 一键建下一集(继承系列全部,只写新 topic)。
 * 风格包:建(base 预设 + 覆盖)→ resolve 预览 → 一键填入系列绑定。
 * 直连 /api/series 与 /api/style-packs。需登录。
 */
'use client';

import { useState, useEffect, type FormEvent } from 'react';
import { seriesApi, styleApi } from '@/lib/api-client';
import type { Series, Episode, StylePack } from '@/types/api';

const PRESETS = [
  '科普', '严肃', '搞笑', '电影感', '赛博朋克', '国风水墨', '治愈系', '商务专业', '美食', '旅行Vlog',
  '产品广告', '新闻播报', '悬疑', '史诗', '复古胶片', '动漫', '极简', '自然纪录片', '时尚', '运动',
];
const OVERRIDE_KEYS: { k: string; label: string }[] = [
  { k: 'style', label: '风格' }, { k: 'lighting', label: '光照' }, { k: 'camera', label: '镜头' },
  { k: 'color_grade', label: '调色' }, { k: 'negative', label: '负向' },
];

function errText(e: unknown): string {
  if (e instanceof Error && e.message === 'NOT_AUTHENTICATED') return '请先登录';
  return e instanceof Error ? e.message : '出错了';
}

export function SeriesManager() {
  const [list, setList] = useState<Series[]>([]);
  const [selected, setSelected] = useState<Series | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // 新建系列表单
  const [sName, setSName] = useState('');
  const [sPreset, setSPreset] = useState('电影感');
  const [sPackId, setSPackId] = useState('');
  const [sSubjects, setSSubjects] = useState('');

  // 建集
  const [topic, setTopic] = useState('');

  // 风格包创建
  const [showPack, setShowPack] = useState(false);
  const [pName, setPName] = useState('');
  const [pPreset, setPPreset] = useState('电影感');
  const [pOverrides, setPOverrides] = useState<Record<string, string>>({});
  const [newPack, setNewPack] = useState<{ pack: StylePack; resolved: Record<string, string> } | null>(null);
  const [drafting, setDrafting] = useState(false);

  async function loadList() {
    try { setList(await seriesApi.list()); } catch (e) { setErr(errText(e)); }
  }
  useEffect(() => { loadList(); }, []);

  async function selectSeries(s: Series) {
    setSelected(s); setEpisodes([]); setErr(null);
    try { setEpisodes(await seriesApi.episodes(s.id)); } catch (e) { setErr(errText(e)); }
  }

  async function createSeries(e: FormEvent) {
    e.preventDefault();
    if (!sName.trim()) { setErr('系列名不能为空'); return; }
    setBusy(true); setErr(null);
    try {
      const created = await seriesApi.create({
        name: sName.trim(),
        style_preset: sPreset,
        style_pack_id: sPackId.trim() || null,
        subject_ids: sSubjects.split(',').map(x => x.trim()).filter(Boolean),
      });
      setSName(''); setSPackId(''); setSSubjects('');
      await loadList();
      await selectSeries(created);
    } catch (e2) { setErr(errText(e2)); } finally { setBusy(false); }
  }

  async function addEpisode(e: FormEvent) {
    e.preventDefault();
    if (!selected || !topic.trim()) { setErr('先选系列并写本集主题'); return; }
    setBusy(true); setErr(null);
    try {
      await seriesApi.createEpisode(selected.id, topic.trim());
      setTopic('');
      setEpisodes(await seriesApi.episodes(selected.id));
    } catch (e2) { setErr(errText(e2)); } finally { setBusy(false); }
  }

  async function draftFromReference(file: File) {
    setDrafting(true); setErr(null);
    try {
      const draft = await styleApi.draftFromReference(file);
      setPOverrides({ ...pOverrides, ...draft });
    } catch (e) { setErr(errText(e)); } finally { setDrafting(false); }
  }

  async function createPack(e: FormEvent) {
    e.preventDefault();
    if (!pName.trim()) { setErr('风格包名不能为空'); return; }
    setBusy(true); setErr(null);
    try {
      const pack = await styleApi.create({
        name: pName.trim(),
        base_preset: pPreset,
        overrides: Object.fromEntries(Object.entries(pOverrides).filter(([, v]) => v.trim())),
      });
      const { resolved } = await styleApi.resolve(pack.id);
      setNewPack({ pack, resolved });
      setPName(''); setPOverrides({});
    } catch (e2) { setErr(errText(e2)); } finally { setBusy(false); }
  }

  return (
    <div className="hevi-series">
      <h1 className="hevi-series__title">系列 · 风格包</h1>
      <p className="hevi-series__sub">建一个系列(绑主体/风格)→ 每集只写新主题,自动继承设定产出第 N 集。</p>
      {err && <div className="hevi-series__err">{err}</div>}

      <div className="hevi-series__cols">
        {/* 左:新建 + 列表 */}
        <div className="hevi-series__col">
          <form className="hevi-series__form" onSubmit={createSeries}>
            <div className="hevi-series__form-head">新建系列</div>
            <input placeholder="系列名 *" value={sName} onChange={e => setSName(e.target.value)} />
            <label>风格预设
              <select value={sPreset} onChange={e => setSPreset(e.target.value)}>
                {PRESETS.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            </label>
            <input placeholder="风格包 ID(可选,见右侧)" value={sPackId} onChange={e => setSPackId(e.target.value)} />
            <input placeholder="主体 ID,逗号分隔(可选)" value={sSubjects} onChange={e => setSSubjects(e.target.value)} />
            <button type="submit" disabled={busy}>创建系列</button>
          </form>

          <div className="hevi-series__list">
            <div className="hevi-series__form-head">我的系列({list.length})</div>
            {list.length === 0 ? <div className="hevi-series__empty">还没有系列</div> : list.map(s => (
              <button
                key={s.id}
                className="hevi-series__item"
                data-active={selected?.id === s.id ? 'true' : undefined}
                onClick={() => selectSeries(s)}
              >
                <span className="hevi-series__item-name">{s.name}</span>
                <span className="hevi-series__item-meta">{s.style_preset} · {s.episode_count ?? 0} 集</span>
              </button>
            ))}
          </div>
        </div>

        {/* 右:选中系列的分集 + 建集 */}
        <div className="hevi-series__col">
          {selected ? (
            <>
              <div className="hevi-series__detail-head">{selected.name}</div>
              <div className="hevi-series__detail-meta">
                风格 {selected.style_preset || '—'}
                {selected.style_pack_id ? ` · 绑风格包 v${selected.style_pack_version ?? 1}` : ''}
              </div>
              <form className="hevi-series__form hevi-series__form--row" onSubmit={addEpisode}>
                <input placeholder="下一集主题" value={topic} onChange={e => setTopic(e.target.value)} />
                <button type="submit" disabled={busy}>建下一集</button>
              </form>
              <div className="hevi-series__eps">
                {episodes.length === 0 ? <div className="hevi-series__empty">还没有分集</div> : episodes.map(ep => (
                  <div key={ep.id} className="hevi-series__ep">
                    <span className="hevi-series__ep-idx">第 {(ep.episode_index ?? 0) + 1} 集</span>
                    <span className="hevi-series__ep-topic">{ep.topic}</span>
                    <span className="hevi-series__ep-status">{ep.status}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="hevi-series__empty hevi-series__empty--big">选左侧一个系列查看分集,或先新建一个</div>
          )}
        </div>
      </div>

      {/* 风格包创建 */}
      <div className="hevi-series__pack">
        <button className="hevi-series__pack-toggle" onClick={() => setShowPack(v => !v)}>
          {showPack ? '收起风格包' : '+ 新建风格包'}
        </button>
        {showPack && (
          <form className="hevi-series__form" onSubmit={createPack}>
            <div className="hevi-series__form-head">风格包(base 预设 + 覆盖 → 版本化)</div>
            <input placeholder="风格包名 *" value={pName} onChange={e => setPName(e.target.value)} />
            <label>base 预设
              <select value={pPreset} onChange={e => setPPreset(e.target.value)}>
                {PRESETS.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            </label>
            <label className="hevi-series__pack-draft">
              上传参考图,自动填风格草稿(可选)
              <input
                type="file"
                accept="image/*,video/*"
                disabled={drafting}
                onChange={e => { const f = e.target.files?.[0]; if (f) draftFromReference(f); e.target.value = ''; }}
              />
              {drafting && <span className="hevi-series__pack-draft-busy">拆解中…</span>}
            </label>
            {OVERRIDE_KEYS.map(({ k, label }) => (
              <input
                key={k}
                placeholder={`覆盖 ${label}(可选)`}
                value={pOverrides[k] ?? ''}
                onChange={e => setPOverrides({ ...pOverrides, [k]: e.target.value })}
              />
            ))}
            <button type="submit" disabled={busy}>创建风格包</button>
          </form>
        )}
        {newPack && (
          <div className="hevi-series__pack-result">
            <div>新风格包 <b className="hevi-series__mono">{newPack.pack.id}</b> · v{newPack.pack.version}</div>
            <div className="hevi-series__resolved">
              {Object.entries(newPack.resolved).map(([k, v]) => <div key={k}><span>{k}</span> {v}</div>)}
            </div>
            <button onClick={() => { setSPackId(newPack.pack.id); setShowPack(false); }}>填入新建系列 ↑</button>
          </div>
        )}
      </div>
    </div>
  );
}
