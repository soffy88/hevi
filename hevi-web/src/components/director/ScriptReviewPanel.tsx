/**
 * ScriptReviewPanel — 剧本人工审核台(通鉴 L2 卡点)
 * 状态=AWAITING_REVIEW 时展示:立意卡(可编辑) + 台词表(全量行内编辑) + 确认渲染/重新生成。
 * 确认后 PUT 编辑结果 → resume 续跑 L3-L8。
 */
'use client';

import { useState, useEffect, useCallback } from 'react';
import { tongjianApi } from '@/lib/api-client';
import type { TongjianScriptLine } from '@/types/api';

const TYPE_OPTS: { v: string; label: string }[] = [
  { v: 'narration', label: '旁白' },
  { v: 'dialogue', label: '对白' },
  { v: 'commentary', label: '史论' },
];

function blankLine(i: number): TongjianScriptLine {
  return {
    line_id: `LN${String(i).padStart(3, '0')}`, act: 1, type: 'narration',
    speaker: 'NARRATOR', text: '', event_id: null, quote_id: null,
    dramatized: false, emotion: '', visual_hint: '',
  };
}

export function ScriptReviewPanel({ runId, onResumed }: { runId: string; onResumed: () => void }) {
  const [lines, setLines] = useState<TongjianScriptLine[]>([]);
  const [logline, setLogline] = useState('');
  const [tone, setTone] = useState('');
  const [rawConstitution, setRawConstitution] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await tongjianApi.getScript(runId);
      setLines(r.script.lines);
      setRawConstitution(r.constitution);
      setLogline(String(r.constitution.logline ?? ''));
      setTone(Array.isArray(r.constitution.tone) ? (r.constitution.tone as string[]).join('、') : '');
    } catch (e) {
      setErr(e instanceof Error ? e.message : '加载剧本失败');
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => { load(); }, [load]);

  function patch(i: number, upd: Partial<TongjianScriptLine>) {
    setLines(ls => ls.map((l, idx) => (idx === i ? { ...l, ...upd } : l)));
  }
  function del(i: number) { setLines(ls => ls.filter((_, idx) => idx !== i)); }
  function move(i: number, dir: -1 | 1) {
    setLines(ls => {
      const j = i + dir;
      if (j < 0 || j >= ls.length) return ls;
      const copy = [...ls];
      [copy[i], copy[j]] = [copy[j], copy[i]];
      return copy;
    });
  }
  function addLine() { setLines(ls => [...ls, blankLine(ls.length + 1)]); }

  function buildConstitution() {
    return {
      ...rawConstitution,
      logline,
      tone: tone.split(/[、,，]/).map(s => s.trim()).filter(Boolean),
    };
  }

  async function saveOnly() {
    setBusy(true); setErr(null); setNote(null);
    try {
      await tongjianApi.updateScript(runId, { script: { lines }, constitution: buildConstitution() });
      setNote('已保存草稿');
    } catch (e) {
      setErr(e instanceof Error ? e.message : '保存失败');
    } finally { setBusy(false); }
  }

  async function confirmRender() {
    if (lines.length === 0) { setErr('至少保留一行台词'); return; }
    setBusy(true); setErr(null); setNote(null);
    try {
      await tongjianApi.updateScript(runId, { script: { lines }, constitution: buildConstitution() });
      await tongjianApi.resume(runId);
      onResumed();
    } catch (e) {
      setErr(e instanceof Error ? e.message : '开始渲染失败');
      setBusy(false);
    }
  }

  async function regenerate() {
    if (!confirm('重新生成会丢弃当前编辑，用同一立意重出一版剧本，确定？')) return;
    setBusy(true); setErr(null); setNote('重新生成中…');
    try {
      await tongjianApi.regenerate(runId);
      // 轮询直到重新回到审核态，再加载新剧本
      for (let k = 0; k < 40; k++) {
        await new Promise(res => setTimeout(res, 2500));
        const r = await tongjianApi.getScript(runId);
        if (r.status === 'AWAITING_REVIEW') {
          setLines(r.script.lines);
          setRawConstitution(r.constitution);
          setLogline(String(r.constitution.logline ?? ''));
          setNote('已重新生成');
          break;
        }
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : '重新生成失败');
    } finally { setBusy(false); }
  }

  if (loading) return <div className="tj-review"><div className="tj-review__head">📝 加载剧本审核台…</div></div>;

  const dialogueN = lines.filter(l => l.type === 'dialogue').length;
  const narrN = lines.filter(l => l.type === 'narration').length;
  const chars = lines.reduce((n, l) => n + l.text.length, 0);

  return (
    <div className="tj-review">
      <div className="tj-review__head">
        📝 剧本人工审核 —— 确认无误再渲染（渲染很耗时，改在这里最省）
      </div>
      <div className="tj-review__stat">
        共 {lines.length} 行 · 对白 {dialogueN} · 旁白 {narrN} · 约 {chars} 字
      </div>

      <label className="tj-field">
        <span className="tj-field__label">立意 logline（一句话说清这集在讲什么）</span>
        <textarea rows={2} value={logline} onChange={e => setLogline(e.target.value)} />
      </label>
      <label className="tj-field">
        <span className="tj-field__label">基调（顿号分隔）</span>
        <input value={tone} onChange={e => setTone(e.target.value)} placeholder="肃穆、隐伏张力、青铜冷感" />
      </label>

      <div className="tj-rev-table">
        {lines.map((l, i) => (
          <div key={l.line_id + i} className={`tj-rev-row tj-rev-row--${l.type}`}>
            <div className="tj-rev-row__meta">
              <span className="tj-rev-row__n">{i + 1}</span>
              <select value={l.type} onChange={e => patch(i, { type: e.target.value, dramatized: e.target.value === 'dialogue' ? l.dramatized : false })}>
                {TYPE_OPTS.map(o => <option key={o.v} value={o.v}>{o.label}</option>)}
              </select>
              {l.type === 'dialogue' && (
                <input className="tj-rev-row__spk" value={l.speaker} onChange={e => patch(i, { speaker: e.target.value })} placeholder="角色id 如 C005" />
              )}
              <input className="tj-rev-row__emo" value={l.emotion} onChange={e => patch(i, { emotion: e.target.value })} placeholder="情绪" />
              {l.type === 'dialogue' && l.dramatized && <span className="tj-chip">戏剧化</span>}
              {l.type === 'dialogue' && l.quote_id && <span className="tj-chip" title="逐字引语">引语</span>}
              <span className="tj-rev-row__sp" />
              <button type="button" title="上移" onClick={() => move(i, -1)}>↑</button>
              <button type="button" title="下移" onClick={() => move(i, 1)}>↓</button>
              <button type="button" title="删除" className="tj-rev-row__del" onClick={() => del(i)}>🗑</button>
            </div>
            <textarea rows={2} value={l.text} onChange={e => patch(i, { text: e.target.value })}
              placeholder={l.type === 'dialogue' ? '这句台词…' : '这段旁白/史论…'} />
          </div>
        ))}
      </div>

      <button type="button" className="tj-rev-add" onClick={addLine}>+ 加一行</button>

      {err && <div className="tj-err">{err}</div>}
      {note && <div className="tj-review__note">{note}</div>}

      <div className="tj-review__actions">
        <button type="button" className="oui-btn oui-btn--primary" disabled={busy} onClick={confirmRender}>
          ✓ 确认，开始渲染
        </button>
        <button type="button" className="oui-btn" disabled={busy} onClick={saveOnly}>保存草稿</button>
        <button type="button" className="oui-btn" disabled={busy} onClick={regenerate}>↻ 重新生成剧本</button>
      </div>
    </div>
  );
}
