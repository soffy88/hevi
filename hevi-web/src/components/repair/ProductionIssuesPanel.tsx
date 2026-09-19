'use client';

/**
 * D6-D 制作问题 — productized self-healing.
 * Shows what happened, whether HEVI can handle it, whether it costs money,
 * and the verified outcome. Never shows internal-only jargon.
 */
import { useEffect, useState } from 'react';
import { incidentApi } from '@/lib/api-client';
import { PRODUCT_COPY as C, TIMELINE_LABELS } from '@/lib/product-copy';
import type { IncidentProductView, IncidentTimelineEvent } from '@/types/api';
import { ActionButton, Card, SectionHeader } from '@/components/shared/ui';

function money(usd: number): string {
  return usd > 0 ? `$${usd.toFixed(2)}` : '';
}

export function ProductionIssuesPanel({ productionRunId = '' }: { productionRunId?: string }) {
  const [incidents, setIncidents] = useState<IncidentProductView[]>([]);
  const [timelines, setTimelines] = useState<Record<string, IncidentTimelineEvent[]>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    try {
      const data = await incidentApi.listProduct(productionRunId);
      setIncidents(data.incidents);
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : '制作问题加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [productionRunId]);

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    setMessage('');
    setError('');
    try {
      await fn();
      setMessage(ok);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : '操作失败');
    } finally {
      setBusy(false);
    }
  };

  const showTimeline = async (incidentId: string) => {
    if (timelines[incidentId]) {
      setTimelines(prev => {
        const next = { ...prev };
        delete next[incidentId];
        return next;
      });
      return;
    }
    try {
      const data = await incidentApi.timeline(incidentId);
      setTimelines(prev => ({ ...prev, [incidentId]: data.events }));
    } catch (e) {
      setError(e instanceof Error ? e.message : '处理过程加载失败');
    }
  };

  return (
    <section data-testid="production-issues" aria-busy={loading}>
      <SectionHeader icon="🛠" title={C.repair.title} />

      {message && <p role="status" data-testid="issues-message">{message}</p>}
      {error && <p role="alert" data-testid="issues-error">{error}</p>}
      {loading && <p data-testid="issues-loading">加载中…</p>}
      {!loading && incidents.length === 0 && (
        <p data-testid="issues-empty">{C.repair.empty}</p>
      )}

      <ul data-testid="issues-list">
        {incidents.map(incident => {
          const autoRecovered = incident.status === 'resolved' && incident.policy === 'auto_safe';
          const manual = incident.status === 'escalated_manual' || incident.policy === 'manual_only';
          const failed = incident.status === 'repair_failed';
          return (
            <li key={incident.incident_id} data-testid={`issue-${incident.incident_id}`}>
              <Card title={incident.diagnosis || incident.root_cause} subtitle={incident.status}>
                {autoRecovered && (
                  <p data-testid={`recovered-${incident.incident_id}`}>{C.repair.autoRecovered}</p>
                )}
                {failed && <p data-testid={`failed-${incident.incident_id}`}>{C.repair.failed}</p>}

                {incident.requires_confirmation && incident.status !== 'resolved' && (
                  <div data-testid={`confirm-box-${incident.incident_id}`}>
                    <p>{C.repair.needsDecision}</p>
                    <p>
                      {incident.estimated_cost_usd > 0
                        ? C.repair.estimatedCost(money(incident.estimated_cost_usd))
                        : C.repair.noExtraCost}
                    </p>
                    <div className="actions">
                      <ActionButton
                        onClick={() =>
                          act(
                            () => incidentApi.confirm(incident.incident_id, true),
                            '已确认修复',
                          )
                        }
                        loading={busy}
                      >
                        {C.repair.confirmRepair}
                      </ActionButton>
                      <ActionButton
                        variant="secondary"
                        onClick={() =>
                          act(
                            () => incidentApi.refuse(incident.incident_id),
                            '已选择暂不处理',
                          )
                        }
                      >
                        {C.repair.notNow}
                      </ActionButton>
                    </div>
                  </div>
                )}

                {manual && (
                  <p data-testid={`manual-${incident.incident_id}`}>
                    {C.repair.manual}：{incident.diagnosis}
                  </p>
                )}

                {!incident.requires_confirmation && !manual && !autoRecovered && !failed && (
                  <p>{C.repair.autoRecovered}</p>
                )}

                <ActionButton variant="ghost" size="sm" onClick={() => showTimeline(incident.incident_id)}>
                  {C.repair.timeline}
                </ActionButton>
                {timelines[incident.incident_id] && (
                  <ol data-testid={`timeline-${incident.incident_id}`}>
                    {timelines[incident.incident_id].map(event => (
                      <li key={event.seq}>
                        {TIMELINE_LABELS[event.event] ?? event.event}
                        {event.detail ? `：${event.detail}` : ''}
                      </li>
                    ))}
                  </ol>
                )}
              </Card>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
