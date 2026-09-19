'use client';

/**
 * D3-D production-operations panel: persistent identity, continuity, repair.
 * Renders ONLY canonical authority state (identity version, gate verdict,
 * incident status come from the API). No local re-derivation.
 */
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth-store';
import { identityApi, continuityApi, incidentApi } from '@/lib/api-client';
import type { PersistentIdentity, ContinuityFact, RepairIncident } from '@/types/api';

export function OpsPanel() {
  const router = useRouter();
  const [identities, setIdentities] = useState<PersistentIdentity[]>([]);
  const [selectedIdentity, setSelectedIdentity] = useState<string | null>(null);
  const [facts, setFacts] = useState<ContinuityFact[]>([]);
  const [incidents, setIncidents] = useState<RepairIncident[]>([]);
  const [projectId, setProjectId] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      setIdentities(await identityApi.list());
      setIncidents((await incidentApi.list()).incidents);
    } catch (e) {
      if (e instanceof Error && e.message === 'NOT_AUTHENTICATED') router.push('/login');
      else setError('运维数据加载失败，请稍后重试');
    }
  };

  useEffect(() => { if (!isAuthenticated()) router.push('/login'); else void load(); }, [router]);

  const inspect = async (id: string) => {
    setSelectedIdentity(id); setMessage(null); setError(null);
    try { setFacts((await continuityApi.facts(id)).facts); }
    catch (e) { setError(e instanceof Error ? e.message : '连续性状态加载失败'); }
  };

  const bind = async (identityId: string) => {
    if (!projectId.trim()) { setError('请先填写项目 ID'); return; }
    setError(null); setMessage(null);
    try {
      const binding = await identityApi.bind(projectId.trim(), identityId);
      setMessage(`已绑定:版本 v${binding.pinned_identity_version}`);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : '绑定失败'); }
  };

  const confirm = async (id: string, ok: boolean) => {
    setError(null); setMessage(null);
    try {
      await incidentApi.confirm(id, ok);
      setMessage(ok ? '已确认修复' : '已记录拒绝');
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : '确认失败'); }
  };

  const refuse = async (id: string) => {
    setError(null); setMessage(null);
    try { await incidentApi.refuse(id); setMessage('已拒绝该修复'); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : '拒绝失败'); }
  };

  return (
    <div data-testid="ops-panel">
      <h2>生产运维</h2>
      {message && <p data-testid="ops-message">{message}</p>}
      {error && <p data-testid="ops-error">{error}</p>}

      <section>
        <h3>持久身份</h3>
        <label>
          项目 ID
          <input data-testid="ops-project-id" value={projectId}
            onChange={e => setProjectId(e.target.value)} placeholder="proj-b" />
        </label>
        <ul data-testid="ops-identities">
          {identities.map(item => (
            <li key={item.identity_id} data-testid={`ops-identity-${item.identity_id}`}>
              <span>{item.canonical_name} v{item.identity_version} · {item.voice_id} · 绑定×{item.binding_count}</span>
              <button type="button" onClick={() => void inspect(item.identity_id)}>查看连续性</button>
              <button type="button" onClick={() => void bind(item.identity_id)}>绑定到项目</button>
            </li>
          ))}
        </ul>
      </section>

      {selectedIdentity && (
        <section>
          <h3>连续性状态</h3>
          <ul data-testid="ops-facts">
            {facts.map(fact => (
              <li key={fact.fact_id}>
                [{fact.category}] {fact.statement}（{fact.provenance} · {fact.episode}/{fact.scene}/{fact.shot} · {fact.revision}）
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <h3>修复事件</h3>
        <ul data-testid="ops-incidents">
          {incidents.map(incident => (
            <li key={incident.incident_id} data-testid={`ops-incident-${incident.incident_id}`}>
              <span>{incident.root_cause} · {incident.status} · 尝试×{incident.attempts}</span>
              <button type="button" onClick={() => void confirm(incident.incident_id, true)}>确认修复</button>
              <button type="button" onClick={() => void refuse(incident.incident_id)}>拒绝</button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
