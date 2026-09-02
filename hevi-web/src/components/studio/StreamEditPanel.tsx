'use client';

import { useEffect, useState } from 'react';
import { streamEditApi } from '@/lib/api-client';

type StreamCapabilities = {
  available?: boolean;
  status?: string;
  transport?: string;
  causal?: boolean;
  open_ended?: boolean;
  provider_url?: string | null;
  setup?: string;
};

export function StreamEditPanel() {
  const [capability, setCapability] = useState<StreamCapabilities | null>(null);
  const [prompt, setPrompt] = useState('把背景变成霓虹雨夜，保持主体动作');
  const [session, setSession] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    void streamEditApi.capabilities()
      .then((value) => setCapability(value as StreamCapabilities))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '实时编辑能力加载失败'));
  }, []);

  async function create() {
    if (!prompt.trim()) return;
    setCreating(true);
    setError('');
    try {
      setSession(await streamEditApi.create({ prompt }));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '实时编辑会话创建失败');
    } finally {
      setCreating(false);
    }
  }

  return (
    <section style={{ marginTop: 20, padding: 24, border: '1px solid var(--border, #e2e8f0)', borderRadius: 8, background: 'var(--card, #fff)' }}>
      <h2 style={{ margin: 0 }}>JoyAI 实时 V2V</h2>
      <p style={{ color: 'var(--muted-foreground)', fontSize: 13 }}>实时/上传帧 → 因果视频编辑；HEVI 只转发真实 Provider 帧，不生成占位画面。</p>
      {capability && (
        <p style={{ fontSize: 12 }}>
          <span style={{ color: capability.available ? '#15803d' : '#a16207' }}>{capability.available ? 'Provider 可用' : 'Provider 未配置'}</span>
          {' · '}{capability.transport} · causal={String(capability.causal)} · open-ended={String(capability.open_ended)}
        </p>
      )}
      <div style={{ display: 'flex', gap: 8 }}>
        <input value={prompt} onChange={(event) => setPrompt(event.target.value)} style={{ flex: 1, padding: 9, border: '1px solid var(--border, #e2e8f0)', borderRadius: 6 }} />
        <button type="button" onClick={() => void create()} disabled={creating}>{creating ? '创建中…' : '创建会话'}</button>
      </div>
      {capability && !capability.available && <p style={{ color: '#92400e', fontSize: 12 }}>{capability.setup}</p>}
      {error && <p style={{ color: 'var(--destructive, #b91c1c)', fontSize: 12 }}>{error}</p>}
      {session && <details style={{ marginTop: 10, fontSize: 12 }} open><summary>会话状态：{String(session.status)}</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(session, null, 2)}</pre></details>}
    </section>
  );
}
