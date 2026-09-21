'use client';

import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { productionApi } from '@/lib/api-client';
import { capabilityQualification } from '@/lib/backend-contract';
import type { CapabilityDescriptor } from '@/types/api';

export default function ProviderStatusDetailPage() {
  const params = useParams();
  const providerId = String(params.id ?? '');
  const [provider, setProvider] = useState<CapabilityDescriptor | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    void productionApi.capabilities().then(({ capabilities }) => {
      const found = capabilities.find(item => item.id === providerId);
      if (!found) throw new Error(`Capability "${providerId}" not found in backend catalog`);
      if (alive) setProvider(found);
    }).catch(reason => {
      if (alive) setError(reason instanceof Error ? reason.message : 'Capability detail unavailable');
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => { alive = false; };
  }, [providerId]);

  if (loading) return <div className="provider-detail-page"><div className="provider-detail-page__loading">读取后端 capability catalog…</div></div>;
  if (error || !provider) return <div className="provider-detail-page"><div className="provider-detail-page__error"><h2>Capability unavailable</h2><p>{error ?? 'Capability missing from backend catalog'}</p></div></div>;

  const qualification = capabilityQualification(provider);
  return (
    <main className="provider-detail-page">
      <div className="provider-detail-page__header">
        <h1 className="provider-detail-page__name">{provider.name}</h1>
        <span className="provider-detail-page__status">{qualification}</span>
      </div>
      <section className="provider-detail-page__section">
        <h2 className="provider-detail-page__section-title">Backend capability evidence</h2>
        <div className="provider-detail-page__info-grid">
          <div className="provider-detail-page__info-item"><span className="provider-detail-page__info-label">id:</span><span className="provider-detail-page__info-value">{provider.id}</span></div>
          <div className="provider-detail-page__info-item"><span className="provider-detail-page__info-label">available:</span><span className="provider-detail-page__info-value">{String(provider.available)}</span></div>
          <div className="provider-detail-page__info-item"><span className="provider-detail-page__info-label">production_ready:</span><span className="provider-detail-page__info-value">{String(provider.production_ready ?? 'unknown')}</span></div>
          <div className="provider-detail-page__info-item"><span className="provider-detail-page__info-label">provider_ready:</span><span className="provider-detail-page__info-value">{String(provider.provider_ready ?? 'unknown')}</span></div>
          <div className="provider-detail-page__info-item"><span className="provider-detail-page__info-label">message:</span><span className="provider-detail-page__info-value">{provider.message}</span></div>
        </div>
      </section>
    </main>
  );
}
