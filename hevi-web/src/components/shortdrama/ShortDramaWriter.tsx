'use client';

import { useState } from 'react';
import { shortdramaWriterApi } from '@/lib/api-client';

export function ShortDramaWriter() {
  const [premise, setPremise] = useState('一个外卖员发现订单地址是自己失踪多年的家');
  const [rawText, setRawText] = useState('');
  const [title, setTitle] = useState('地址');
  const [tone, setTone] = useState('悬疑、克制');
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);

  const draft = async () => {
    setBusy(true);
    try { setResult(await shortdramaWriterApi.draft({ title, premise, raw_text: rawText, tone, style: '电影感' })); }
    catch (e) { setResult({ error: e instanceof Error ? e.message : '剧本生成失败' }); }
    finally { setBusy(false); }
  };

  const screenplay = result?.screenplay as Record<string, unknown> | undefined;
  const review = result?.review as { passed?: boolean; score?: number; findings?: Array<{ message?: string }> } | undefined;
  return (
    <main style={{ maxWidth: 1100, margin: '0 auto', padding: '30px 16px' }}>
      <header style={{ marginBottom: 20 }}><p style={{ color: 'var(--primary)', fontWeight: 800, fontSize: 12 }}>AI SHORT DRAMA SCREENWRITER</p><h1 style={{ margin: 0 }}>短剧编剧</h1><p style={{ color: 'var(--muted-foreground)' }}>只写剧本，不把剧本伪装成分镜或成片；审核通过后再交给下游制作。</p></header>
      <section style={{ display: 'grid', gap: 12, padding: 22, border: '1px solid var(--border)', borderRadius: 14, background: 'var(--card)' }}>
        <label>集名<input value={title} onChange={(e) => setTitle(e.target.value)} style={{ display: 'block', width: '100%', marginTop: 6, padding: 10 }} /></label>
        <label>一句话梗概<textarea value={premise} onChange={(e) => setPremise(e.target.value)} rows={3} style={{ display: 'block', width: '100%', marginTop: 6, padding: 10 }} /></label>
        <label>作者原文（可选）<textarea value={rawText} onChange={(e) => setRawText(e.target.value)} rows={5} placeholder="有原文时优先保留原文事实" style={{ display: 'block', width: '100%', marginTop: 6, padding: 10 }} /></label>
        <label>基调<input value={tone} onChange={(e) => setTone(e.target.value)} style={{ display: 'block', width: '100%', marginTop: 6, padding: 10 }} /></label>
        <button type="button" onClick={() => void draft()} disabled={busy || !premise.trim()} style={{ width: 'fit-content', padding: '10px 16px' }}>{busy ? '写作中…' : '生成剧本草稿'}</button>
      </section>
      {typeof result?.error === 'string' && <p style={{ color: 'var(--destructive, #b91c1c)' }}>{result.error}</p>}
      {screenplay && <section style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) minmax(240px, .5fr)', gap: 16, marginTop: 20 }}><article style={{ padding: 22, border: '1px solid var(--border)', borderRadius: 14, background: 'var(--card)' }}><h2>剧本 Markdown</h2><pre style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>{String(result?.markdown ?? '')}</pre></article><aside style={{ padding: 18, border: '1px solid var(--border)', borderRadius: 14, background: 'var(--card)', alignSelf: 'start' }}><h2>审核</h2><p>{review?.passed ? '✅ 可交接下游' : '⚠️ 需要修订'} · {review?.score ?? 0}/100</p><ul>{(review?.findings ?? []).map((item, i) => <li key={i}>{item.message}</li>)}</ul><small>scope: script-only</small></aside></section>}
    </main>
  );
}
