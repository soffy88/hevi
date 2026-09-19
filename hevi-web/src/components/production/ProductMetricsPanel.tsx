'use client';

/**
 * D6-H 创作数据 — product analytics from the canonical metrics endpoint.
 * No second analytics ledger; counts come from IdentityStore/IncidentStore.
 */
import { useEffect, useState } from 'react';
import { productApi } from '@/lib/api-client';
import { Card, SectionHeader } from '@/components/shared/ui';

interface Metrics {
  IDENTITY_REUSE_RATE: number;
  CONTINUITY_BLOCKS_CAUGHT: number;
  CONTINUITY_WARNINGS_OVERRIDDEN: number;
  AUTO_SAFE_REPAIRS: number;
  PAID_REPAIRS_CONFIRMED: number;
  FAILED_REPAIRS: number;
  REPAIR_MEAN_ATTEMPTS: number;
  DUPLICATE_BILLING_PREVENTED: number;
  ARTIFACTS_PRESERVED_BY_REPAIR: number;
}

const LABELS: Record<keyof Metrics, string> = {
  IDENTITY_REUSE_RATE: '平均角色复用项目数',
  CONTINUITY_BLOCKS_CAUGHT: '生成前拦截的连续性问题',
  CONTINUITY_WARNINGS_OVERRIDDEN: '已确认的连续性提醒',
  AUTO_SAFE_REPAIRS: '自动恢复次数',
  PAID_REPAIRS_CONFIRMED: '已确认付费修复',
  FAILED_REPAIRS: '修复未成功',
  REPAIR_MEAN_ATTEMPTS: '平均修复尝试',
  DUPLICATE_BILLING_PREVENTED: '避免的重复计费',
  ARTIFACTS_PRESERVED_BY_REPAIR: '修复中保留的成品',
};

export function ProductMetricsPanel() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    productApi
      .metrics()
      .then(data => {
        setMetrics(data.metrics as unknown as Metrics);
        setError('');
      })
      .catch(e => setError(e instanceof Error ? e.message : '数据加载失败'))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p data-testid="metrics-loading">加载中…</p>;
  if (error) return <p role="alert" data-testid="metrics-error">{error}</p>;
  if (!metrics) return null;

  return (
    <section data-testid="product-metrics">
      <SectionHeader icon="📈" title="创作数据" subtitle="只统计你帐号下的制作情况" />
      <Card>
        <dl>
          {(Object.keys(LABELS) as Array<keyof Metrics>).map(key => (
            <div key={key}>
              <dt>{LABELS[key]}</dt>
              <dd data-testid={`metric-${key}`}>{metrics[key]}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </section>
  );
}
