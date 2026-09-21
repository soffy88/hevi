'use client';

import { useEffect, useState } from 'react';
import { productionApi } from '@/lib/api-client';
import { capabilityQualification, type CapabilityQualification } from '@/lib/backend-contract';
import type { CapabilityDescriptor } from '@/types/api';

const RELEASE_CAPABILITIES: Array<{ id: string; label: string }> = [
  { id: 'blender_previz', label: 'Blender' },
  { id: 'audio_master_clock', label: 'Audio Master Clock' },
  { id: 'subtitle_timeline', label: 'Subtitle/Timeline' },
  { id: 'motion_graphics', label: 'Remotion Motion Graphics' },
  { id: 'visual_quality', label: 'Visual Quality' },
  { id: 'longvideo', label: 'Local Media Golden Path' },
  { id: 'v2v', label: 'V2V' },
];

function statusClass(status: CapabilityQualification): string {
  return status === 'PRODUCTION_QUALIFIED'
    ? 'status-ready'
    : status === 'WIRING_QUALIFIED_PROVIDER_BLOCKED'
      ? 'status-blocked'
      : 'status-unverified';
}

export default function ProviderStatusPage() {
  const [catalog, setCatalog] = useState<CapabilityDescriptor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void productionApi.capabilities().then(({ capabilities }) => {
      if (alive) setCatalog(capabilities);
    }).catch(reason => {
      if (alive) setError(reason instanceof Error ? reason.message : '能力目录加载失败');
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => { alive = false; };
  }, []);

  const byId = new Map(catalog.map(item => [item.id, item]));

  return (
    <main className="provider-status-page">
      <header className="provider-status-page__header">
        <h1 className="provider-status-page__title">Capability catalog</h1>
        <p className="provider-status-page__subtitle">状态来自后端 capability catalog；未知项 fail closed。</p>
      </header>
      {loading && <p data-testid="capability-loading">加载中…</p>}
      {error && <p role="alert">{error}</p>}
      {!loading && !error && (
        <div className="provider-status-page__grid">
          {RELEASE_CAPABILITIES.map(({ id, label }) => {
            const capability = byId.get(id);
            const status = capability ? capabilityQualification(capability) : 'UNKNOWN';
            return (
              <article key={id} className="provider-card" data-testid={`capability-${id}`}>
                <div className="provider-card__header">
                  <h2 className="provider-card__name">{label}</h2>
                  <span className={`provider-card__status ${statusClass(status)}`}>{status}</span>
                </div>
                <div className="provider-card__body">
                  <div className="provider-card__row"><span className="provider-card__label">Backend id:</span><span className="provider-card__value">{id}</span></div>
                  <div className="provider-card__row"><span className="provider-card__label">Available:</span><span className="provider-card__value">{capability?.available == null ? 'unknown' : String(capability.available)}</span></div>
                  <div className="provider-card__row"><span className="provider-card__label">Reason:</span><span className="provider-card__value">{capability?.message ?? 'Capability missing from backend catalog'}</span></div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </main>
  );
}
