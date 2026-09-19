'use client';

/**
 * D6-C 连续性检查 — inline pre-generation gate.
 * Reads the canonical project continuity summary; BLOCK never proceeds to
 * paid generation, WARN requires an explicit (audited) override.
 */
import { useEffect, useState } from 'react';
import { continuityApi } from '@/lib/api-client';
import { PRODUCT_COPY as C } from '@/lib/product-copy';
import type { ContinuityProjectSummary } from '@/types/api';
import { ActionButton, Card, SectionHeader } from '@/components/shared/ui';

export function ContinuityCheckPanel({
  projectId,
  bindingId = '',
  onProceed,
  onBack,
}: {
  projectId: string;
  bindingId?: string;
  onProceed?: () => void;
  onBack?: () => void;
}) {
  const [summary, setSummary] = useState<ContinuityProjectSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showFacts, setShowFacts] = useState(false);
  const [overriding, setOverriding] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      setSummary(await continuityApi.projectSummary(projectId));
      setError('');
    } catch (e) {
      setError(e instanceof Error ? e.message : '连续性检查失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [projectId]);

  const proceedWithOverride = async () => {
    setOverriding(true);
    setError('');
    try {
      if (bindingId) {
        await continuityApi.gate(bindingId, 'video_generation', {}, 'studio-user');
      }
      onProceed?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : '无法继续生成');
    } finally {
      setOverriding(false);
    }
  };

  if (loading) return <p data-testid="continuity-loading">连续性检查中…</p>;
  if (error) return <p role="alert" data-testid="continuity-error">{error}</p>;
  if (!summary) return <p data-testid="continuity-empty">暂无连续性数据</p>;

  const verdict = summary.verdict;
  return (
    <section data-testid="continuity-panel" data-verdict={verdict}>
      <SectionHeader icon="🧭" title={C.continuity.title} subtitle={C.continuity.checkBeforeGenerate} />

      {verdict === 'pass' && (
        <p role="status" data-testid="continuity-pass">
          {C.continuity.pass}
        </p>
      )}

      {verdict === 'warn' && (
        <Card title={C.continuity.warn(summary.issues.length)}>
          <ul data-testid="continuity-issues">
            {summary.issues.map((issue, idx) => (
              <li key={idx}>
                <strong>{issue.code}</strong>：{issue.detail}
              </li>
            ))}
          </ul>
          <div className="actions">
            <ActionButton variant="secondary" onClick={() => setShowFacts(v => !v)}>
              {C.continuity.viewDetails}
            </ActionButton>
            <ActionButton variant="secondary" onClick={onBack}>
              {C.continuity.backToEdit}
            </ActionButton>
            <ActionButton onClick={proceedWithOverride} loading={overriding}>
              {C.continuity.continueAnyway}
            </ActionButton>
          </div>
        </Card>
      )}

      {verdict === 'block' && (
        <Card title={C.continuity.block}>
          <ul data-testid="continuity-block-issues">
            {summary.issues.map((issue, idx) => (
              <li key={idx}>
                <strong>{issue.code}</strong>：{issue.detail}
                {issue.identity_name ? `（${issue.identity_name}）` : ''}
              </li>
            ))}
          </ul>
          <div className="actions">
            <ActionButton variant="secondary" onClick={onBack}>
              {C.continuity.backToEdit}
            </ActionButton>
          </div>
          <p data-testid="continuity-blocked-note">
            已阻止生成，不会创建付费任务。
          </p>
        </Card>
      )}

      {showFacts && (
        <div data-testid="continuity-provenance">
          <h4>{C.continuity.why}</h4>
          <ul>
            {summary.facts.map((fact, idx) => (
              <li key={idx}>
                [{fact.category}] {fact.statement} — {C.continuity.provenance}: {fact.provenance}
                {fact.episode ? ` · ${fact.episode}/${fact.scene}/${fact.shot}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
