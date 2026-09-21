'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { checkBackendHealth } from '@/lib/backend-health';
import { isAuthenticated } from '@/lib/auth-store';
import { productionApi } from '@/lib/api-client';
import { capabilityQualification } from '@/lib/backend-contract';
import type { CapabilityDescriptor, ProductionTask } from '@/types/api';

export function ProductionCreatePanel({ onCreated }: { onCreated: (task: ProductionTask) => void }) {
  const router = useRouter();
  const [script, setScript] = useState('');
  const [voice, setVoice] = useState('zh_female_standard');
  const [visualMode, setVisualMode] = useState('local_media');
  const [subtitles, setSubtitles] = useState(true);
  const [outputSpec, setOutputSpec] = useState('9:16');
  const [ready, setReady] = useState(false);
  const [checking, setChecking] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<CapabilityDescriptor[] | null>(null);
  const [capabilityError, setCapabilityError] = useState<string | null>(null);

  const refreshReadiness = async () => {
    setChecking(true);
    const health = await checkBackendHealth();
    setReady(health.ready);
    if (!health.ready) setError('生产系统当前不可用：worker 或其他依赖未 ready。');
    else setError(null);
    setChecking(false);
  };

  useEffect(() => { void refreshReadiness(); }, []);
  useEffect(() => {
    void productionApi.capabilities()
      .then(({ capabilities: catalog }) => {
        setCapabilities(catalog);
        setCapabilityError(null);
      })
      .catch((reason: unknown) => {
        setCapabilities(null);
        setCapabilityError(reason instanceof Error ? reason.message : '能力目录不可用');
      });
  }, []);
  useEffect(() => {
    const timer = window.setInterval(() => { void refreshReadiness(); }, 5_000);
    return () => window.clearInterval(timer);
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isAuthenticated()) { router.push('/login'); return; }
    if (!ready || !script.trim() || !localMediaReady) return;
    setSubmitting(true);
    setError(null);
    try {
      const task = await productionApi.create({
        source: 'automatic',
        topic: script.trim(),
        duration_archetype: '1-5min',
        video_provider: 'auto',
        audio_provider: voice,
        aspect_ratio: outputSpec as '9:16' | '16:9' | '1:1',
        options: {
          visual_mode: visualMode,
          subtitles,
          output_spec: outputSpec,
          voice_identity: { voice_id: voice },
        },
      });
      onCreated(task);
      setScript('');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '生产创建失败');
    } finally {
      setSubmitting(false);
    }
  };

  const byId = new Map((capabilities ?? []).map((capability) => [capability.id, capability]));
  const localMedia = byId.get('local_media');
  const localMediaReady = localMedia?.production_ready === true;
  const rendererOptions = (['motion_graphics', 'blender_previz'] as const)
    .map((id) => byId.get(id))
    .filter((capability): capability is CapabilityDescriptor => capability != null);
  const v2v = byId.get('v2v') ?? byId.get('streaming_v2v');
  const capabilityLabel = (capability: CapabilityDescriptor) => {
    if (capability.id === 'motion_graphics') return 'Remotion';
    if (capability.id === 'blender_previz') return 'Blender';
    return capability.name;
  };

  return (
    <section className="hevi-task-section" data-testid="production-create">
      <div className="hevi-task-section__head">
        <div><h2>创建 production</h2><p>正式 Production Graph 入口；前端不直接调用 TTS、ASR、Remotion 或 Blender。</p></div>
        <span className={ready ? 'status-healthy' : 'status-degraded'} data-testid="production-readiness">
          {checking ? '检查 readiness…' : ready ? 'READY' : 'UNAVAILABLE'}
        </span>
      </div>
      {capabilityError && <div className="hevi-production__notice is-error" role="alert">能力目录不可用：{capabilityError}</div>}
      {capabilities && !localMediaReady && <div className="hevi-production__notice is-error" role="alert">当前没有可执行的 production-qualified local-media path。</div>}
      {error && <div className="hevi-production__notice is-error" role="alert">{error}</div>}
      <form className="hevi-production-create" onSubmit={submit}>
        <label>Script / text<textarea aria-label="script/text" value={script} onChange={e => setScript(e.target.value)} required /></label>
        <label>Voice<select aria-label="voice" value={voice} onChange={e => setVoice(e.target.value)}><option value="zh_female_standard">Standard female voice</option><option value="zh_male_standard">Standard male voice</option></select></label>
        <label>Visual mode<select aria-label="visual mode" value={visualMode} onChange={e => setVisualMode(e.target.value)}>
          {localMediaReady && <option value="local_media">Local media golden path</option>}
          {rendererOptions.filter((capability) => capability.production_ready === true).map((capability) => <option key={capability.id} value={capability.id}>{capabilityLabel(capability)}</option>)}
          {v2v && <option value="v2v" disabled>V2V — {capabilityQualification(v2v)}</option>}
        </select></label>
        {v2v && <p data-testid="v2v-capability-state">V2V：{capabilityQualification(v2v)}（不可用于 production）</p>}
        <label>Output spec<select aria-label="output spec" value={outputSpec} onChange={e => setOutputSpec(e.target.value)}><option value="9:16">9:16</option><option value="16:9">16:9</option><option value="1:1">1:1</option></select></label>
        <label className="hevi-production-create__check"><input type="checkbox" checked={subtitles} onChange={e => setSubtitles(e.target.checked)} /> Subtitle/Timeline</label>
        <button type="submit" disabled={checking || submitting || !ready || !localMediaReady || !script.trim()}>{submitting ? '提交中…' : '创建 production'}</button>
      </form>
    </section>
  );
}
