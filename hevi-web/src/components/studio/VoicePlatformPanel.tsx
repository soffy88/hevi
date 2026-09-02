'use client';

import { useEffect, useState } from 'react';
import { voicePlatformApi, voiceStudioApi } from '@/lib/api-client';

type Engine = { id: string; name: string; kind: string; mode: string; available: boolean; description: string; setup?: string | null };

export function VoicePlatformPanel() {
  const [engines, setEngines] = useState<Engine[]>([]);
  const [voices, setVoices] = useState<Array<Record<string, unknown>>>([]);
  const [diagnostic, setDiagnostic] = useState<Record<string, unknown> | null>(null);
  const [models, setModels] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    void Promise.all([voiceStudioApi.catalog(), voicePlatformApi.diagnostics(), voicePlatformApi.models()])
      .then(([catalog, diag, modelCatalog]) => {
        setEngines((catalog.engines as Engine[] | undefined) ?? []);
        setVoices((catalog.voices as Array<Record<string, unknown>> | undefined) ?? []);
        setDiagnostic(diag);
        setModels(modelCatalog.models);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '语音平台加载失败'));
  }, []);

  return (
    <section style={{ marginTop: 20, padding: 24, border: '1px solid var(--border, #e2e8f0)', borderRadius: 8, background: 'var(--card, #fff)' }}>
      <h2 style={{ margin: 0 }}>本地语音平台</h2>
      <p style={{ color: 'var(--muted-foreground)', fontSize: 13 }}>统一查看 TTS、ASR、声线目录与本机诊断；不可用引擎不会伪装成可执行。</p>
      {error && <p style={{ color: 'var(--destructive, #b91c1c)' }}>{error}</p>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 10 }}>
        {engines.map((engine) => (
          <div key={engine.id} style={{ padding: 12, border: '1px solid var(--border, #e2e8f0)', borderRadius: 8 }}>
            <strong>{engine.name}</strong>
            <span style={{ float: 'right', color: engine.available ? '#15803d' : '#a16207', fontSize: 12 }}>{engine.available ? '可用' : '未就绪'}</span>
            <p style={{ margin: '6px 0', fontSize: 12, color: 'var(--muted-foreground)' }}>{engine.kind} · {engine.mode}</p>
            {!engine.available && engine.setup && <p style={{ margin: 0, fontSize: 11, color: '#92400e' }}>{engine.setup}</p>}
          </div>
        ))}
      </div>
      <p style={{ margin: '14px 0 0', fontSize: 12, color: 'var(--muted-foreground)' }}>已登记声线：{voices.length} 个</p>
      <p style={{ margin: '6px 0 0', fontSize: 12, color: 'var(--muted-foreground)' }}>
        模型目录：{models.length} 个 · 就绪：{models.filter((model) => model.ready === true).length} 个 ·
        生命周期状态由本地模型路径真实探测得出
      </p>
      {diagnostic && <details style={{ marginTop: 8, fontSize: 12 }}><summary>诊断信息</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(diagnostic, null, 2)}</pre></details>}
    </section>
  );
}
