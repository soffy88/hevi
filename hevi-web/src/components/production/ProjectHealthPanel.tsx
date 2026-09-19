'use client';

/**
 * D6-E 制作状态 — project health home.
 * Renders the canonical health projection verbatim; the next action is
 * server-derived, never recomputed in the browser.
 */
import { useEffect, useState } from 'react';
import { productApi } from '@/lib/api-client';
import { PRODUCT_COPY as C } from '@/lib/product-copy';
import type { ProjectHealth } from '@/types/api';
import { Card, SectionHeader } from '@/components/shared/ui';

export function ProjectHealthPanel({
  projectId,
  bindingId = '',
  onAction,
}: {
  projectId: string;
  bindingId?: string;
  onAction?: (action: ProjectHealth['next_action']) => void;
}) {
  const [health, setHealth] = useState<ProjectHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    productApi
      .projectHealth(projectId, bindingId)
      .then(data => {
        if (active) {
          setHealth(data);
          setError('');
        }
      })
      .catch(e => active && setError(e instanceof Error ? e.message : '制作状态加载失败'))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [projectId, bindingId]);

  if (loading) return <p data-testid="health-loading">加载制作状态…</p>;
  if (error) return <p role="alert" data-testid="health-error">{error}</p>;
  if (!health) return <p data-testid="health-empty">暂无制作状态</p>;

  const label = C.project.status[health.status] ?? health.status;
  return (
    <section data-testid="project-health" data-status={health.status}>
      <SectionHeader icon="📊" title={C.project.healthTitle} />
      <Card title={label} subtitle={`任务状态：${health.task_status || '—'}`}>
        <dl>
          <dt>待处理问题</dt>
          <dd data-testid="health-incident-count">{health.incidents.length}</dd>
          <dt>过期素材</dt>
          <dd data-testid="health-stale">{health.currency?.stale ?? 0}</dd>
        </dl>
        {health.continuity && (
          <p data-testid="health-continuity">
            连续性：{health.continuity.verdict}
          </p>
        )}
        <div className="actions">
          <button
            type="button"
            data-testid="health-next-action"
            onClick={() => onAction?.(health.next_action)}
          >
            {C.project.nextAction}：{health.next_action.label}
          </button>
        </div>
      </Card>
    </section>
  );
}
