'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { canonicalProductionApi } from '@/lib/api-client';

export function OnePromptEntry() {
  const router = useRouter();
  const [request, setRequest] = useState('Make a tense 12-second vertical scene of an envoy crossing an old gate at dawn.');
  const [renderPreview, setRenderPreview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit() {
    if (!request.trim()) return;
    setBusy(true); setError(null);
    try {
      const renderPath = renderPreview ? `/tmp/hevi-one-prompt-${Date.now()}.mp4` : undefined;
      const result = await canonicalProductionApi.onePrompt(request.trim(), renderPath);
      router.push(`/studio/projects/${result.project_id}`);
    }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'One-Prompt 创建失败'); setBusy(false); }
  }
  return <main className="wb-one-prompt"><div className="wb-one-prompt-card"><span className="wb-eyebrow">ONE PROMPT / PRODUCT ENTRYPOINT</span><h1>Start a production</h1><p>输入创作意图，HEVI 会通过 CreativeBrief → DirectorSession → canonical Production Graph 创建项目。</p><label htmlFor="one-prompt-request">你的创作意图</label><textarea id="one-prompt-request" value={request} onChange={event => setRequest(event.target.value)} rows={5} /><label className="wb-one-prompt-render"><input type="checkbox" checked={renderPreview} onChange={event => setRenderPreview(event.target.checked)} /> 创建后运行 CPU preview render</label><div className="wb-one-prompt-foot"><span>真实 Studio API v2 · 不在前端构造 ProductionPlan</span><button type="button" className="wb-primary-btn" onClick={() => void submit()} disabled={busy || !request.trim()}>{busy ? '正在规划…' : '创建 Production'}</button></div>{error && <div className="wb-inline-error">{error}</div>}</div></main>;
}
