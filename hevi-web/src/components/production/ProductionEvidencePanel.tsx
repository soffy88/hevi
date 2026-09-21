'use client';

import { useEffect, useState } from 'react';
import { artifactAuthorityApi, incidentApi, taskApi } from '@/lib/api-client';
import { isTaskTerminal, normalizeTaskStatus, TASK_STATUS_LABELS } from '@/lib/backend-contract';
import type { ArtifactCurrencyResponse, ArtifactManifest, IncidentProductView, TaskCheckpoint, TaskInfo } from '@/types/api';

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function asManifest(task: TaskInfo): ArtifactManifest | null {
  if (task.artifact_manifest) return task.artifact_manifest;
  const raw = asRecord(task.config_json)?.artifact_manifest;
  const record = asRecord(raw);
  return record && Array.isArray(record.artifacts) ? record as unknown as ArtifactManifest : null;
}

function json(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

export function ProductionEvidencePanel({ taskId, onClose }: { taskId: string; onClose: () => void }) {
  const [task, setTask] = useState<TaskInfo | null>(null);
  const [checkpoint, setCheckpoint] = useState<TaskCheckpoint | null>(null);
  const [currency, setCurrency] = useState<ArtifactCurrencyResponse | null>(null);
  const [incidents, setIncidents] = useState<IncidentProductView[]>([]);
  const [presentation, setPresentation] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setTask(null);
    setCheckpoint(null);
    setCurrency(null);
    setPresentation(null);
    setIncidents([]);
    setError(null);
    void Promise.all([
      taskApi.get(taskId),
      taskApi.checkpoint(taskId).catch(() => null),
      artifactAuthorityApi.currency(taskId).catch(() => null),
      artifactAuthorityApi.presentation(taskId).catch(() => null),
      incidentApi.listProduct(taskId).catch(() => ({ incidents: [] })),
    ]).then(([nextTask, nextCheckpoint, nextCurrency, nextPresentation, nextIncidents]) => {
      if (!alive) return;
      setTask(nextTask);
      setCheckpoint(nextCheckpoint);
      setCurrency(nextCurrency);
      setPresentation(nextPresentation);
      setIncidents(nextIncidents.incidents);
    }).catch(reason => {
      if (alive) setError(reason instanceof Error ? reason.message : '后端证据加载失败');
    });
    return () => { alive = false; };
  }, [taskId]);

  if (error) return <section className="hevi-task-section" role="alert">{error}<button onClick={onClose}>关闭</button></section>;
  if (!task) return <section className="hevi-task-section" aria-busy="true">正在读取后端 production/task/artifact/quality evidence…</section>;

  const status = normalizeTaskStatus(task.status);
  const manifest = asManifest(task);
  const quality = asRecord(task.config_json)?.quality_evaluation;

  return (
    <section className="hevi-task-section" data-testid="production-evidence">
      <div className="hevi-task-section__head"><div><h2>Production evidence</h2><p>所有字段来自 backend authority；前端不重算 current、quality 或 repair verdict。</p></div><button className="hevi-task-action" onClick={onClose}>关闭</button></div>
      <div className="hevi-evidence-grid">
        <div><strong>task</strong><code>{task.task_id}</code></div>
        <div><strong>status</strong><span>{TASK_STATUS_LABELS[status]}</span></div>
        <div><strong>production_id</strong><code>{task.production_id ?? manifest?.production_id ?? '—'}</code></div>
        <div><strong>revision_id</strong><code>{task.revision_id ?? manifest?.revision_id ?? '—'}</code></div>
        <div><strong>root_task_id</strong><code>{task.root_task_id ?? '—'}</code></div>
        <div><strong>current_attempt_id</strong><code>{task.current_attempt_id ?? checkpoint?.attempt_id ?? '—'}</code></div>
        <div><strong>step</strong><span>{task.stage ?? checkpoint?.stage ?? '—'}</span></div>
        <div><strong>started / finished</strong><span>{task.started_at ?? '—'} / {task.finished_at ?? '—'}</span></div>
      </div>

      {status === 'failed' && <div className="hevi-production__notice is-error"><strong>failure_code：</strong>{task.error_code ?? '—'}<br />{task.error ?? '后端未提供 failure message'}</div>}

      <h3>Artifact Currency authority</h3>
      {currency ? <p>{currency.usable}/{currency.total} usable；current state 由 authority evaluations 返回。</p> : <p>当前 revision 尚无可读 currency projection。</p>}
      {manifest ? <div className="hevi-artifact-list">{manifest.artifacts.map(artifact => {
        const evaluation = currency?.evaluations.find(item => item.artifact_id === artifact.artifact_id || item.target_id === artifact.artifact_id);
        return <article key={artifact.artifact_id ?? artifact.path}><strong>{artifact.logical_role ?? artifact.kind}</strong><span>artifact_id：{artifact.artifact_id ?? '—'}</span><span>type：{artifact.kind}</span><span>revision：{manifest.revision_id ?? '—'}</span><span>sha256：{artifact.sha256 ?? '—'}</span><span>currency：{String(evaluation?.currency ?? evaluation?.status ?? 'authority evidence unavailable')}</span><span>delivery：{isTaskTerminal(task.status) && presentation ? 'authority presentation available' : 'not available'}</span><small>lineage parents：{artifact.parent_artifact_ids?.join(', ') || '—'}</small></article>;
      })}</div> : <p>后端未返回 artifact manifest。</p>}

      <h3>Lineage</h3>
      <p>实际 lineage 由 manifest parent_artifact_ids 返回；未返回的关系不由 UI 补造。</p>
      {manifest && <ol className="hevi-lineage">{manifest.artifacts.map(artifact => <li key={artifact.artifact_id ?? artifact.path}>{artifact.logical_role ?? artifact.kind} ← {artifact.parent_artifact_ids?.join(', ') || 'root'}</li>)}</ol>}

      <h3>Quality evidence</h3>
      {quality ? <pre className="hevi-evidence-json">{json(quality)}</pre> : <p>后端未返回 quality_evaluation。</p>}

      <h3>RepairIncident</h3>
      {incidents.length === 0 ? <p>当前 production 没有 RepairIncident。</p> : <ul>{incidents.map(incident => <li key={incident.incident_id}><strong>{incident.failure_code}</strong> · {incident.status} · {incident.diagnosis}</li>)}</ul>}
    </section>
  );
}
