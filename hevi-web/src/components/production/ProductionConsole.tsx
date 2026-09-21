'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth-store';
import { taskApi } from '@/lib/api-client';
import type { ProductionTask, TaskInfo } from '@/types/api';
import { ProductionCreatePanel } from '@/components/production/ProductionCreatePanel';
import { ProductionEvidencePanel } from '@/components/production/ProductionEvidencePanel';
import { boundedBackendProgress, isTaskActive, normalizeTaskStatus, TASK_STATUS_LABELS } from '@/lib/backend-contract';

const SOURCE_LABELS: Record<string, string> = {
  automatic: '极简单片',
  explainer: '头像解说',
  tongjian: '资治通鉴',
  shortdrama: '故事短剧',
  director_graph: '导演控制台',
};

function labelFor(task: TaskInfo): string {
  const source = (task as TaskInfo & { production_source?: string }).production_source;
  return SOURCE_LABELS[source ?? 'automatic'] ?? source ?? '统一任务';
}

export function ProductionConsole() {
  const router = useRouter();
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => {
    if (!isAuthenticated()) { router.push('/login'); return; }
    taskApi.list().then(setTasks).catch(e => setError(e instanceof Error ? e.message : '任务加载失败'));
  };

  const addCreatedTask = (task: ProductionTask) => {
    setTasks(previous => [task, ...previous.filter(item => item.task_id !== task.task_id)]);
  };

  useEffect(() => { refresh(); }, [router]);
  useEffect(() => {
    const hasActive = tasks.some(task => isTaskActive(task.status));
    if (!hasActive) return;
    const timer = window.setInterval(refresh, 3000);
    return () => window.clearInterval(timer);
  }, [tasks]);

  const metrics = useMemo(() => ({
    running: tasks.filter(task => isTaskActive(task.status) && !['pending', 'queued'].includes(normalizeTaskStatus(task.status))).length,
    queued: tasks.filter(task => ['pending', 'queued'].includes(normalizeTaskStatus(task.status))).length,
    completed: tasks.filter(task => normalizeTaskStatus(task.status) === 'completed').length,
    passed: tasks.filter(task => normalizeTaskStatus(task.status) === 'completed' && (task as TaskInfo & { config_json?: Record<string, unknown> }).config_json?.quality_evaluation).length,
  }), [tasks]);

  return (
    <div className="hevi-production hevi-task-manager">
      <ProductionCreatePanel onCreated={addCreatedTask} />
      <header className="hevi-production__hero">
        <div>
          <p className="hevi-production__eyebrow">Task &amp; Asset Manager</p>
          <h1>生产看板 &amp; 任务中心</h1>
          <p>统一查看自动出片、导演控制台和内容适配器产生的任务、进度、质检与交付资产。</p>
        </div>
        <button className="hevi-production__refresh" onClick={refresh}>↻ 刷新</button>
      </header>

      <section className="hevi-task-metrics" aria-label="任务指标">
        <div><strong>{metrics.running}</strong><span>运行中任务</span></div>
        <div><strong>{metrics.queued}</strong><span>队列等待</span></div>
        <div><strong>{metrics.completed}</strong><span>已交付成片</span></div>
        <div><strong>{metrics.completed ? `${metrics.passed}/${metrics.completed}` : '—'}</strong><span>质检通过率（后端证据）</span></div>
      </section>

      {error && <div className="hevi-production__notice is-error">{error}</div>}

      <section className="hevi-task-section">
        <div className="hevi-task-section__head"><div><h2>任务列表与实时状态</h2><p>进度由统一 Task 生命周期投影，成片完成后才开放下载。</p></div><span>{tasks.length} 项</span></div>
        {tasks.length === 0 ? <div className="hevi-task-empty">暂无任务。请从首页生成中心或导演控制台创建任务。</div> : (
          <div className="hevi-task-table-wrap"><table className="hevi-task-table"><thead><tr><th>Task ID</th><th>模式 / 适配器</th><th>进度</th><th>阶段</th><th>状态</th><th>操作</th></tr></thead><tbody>
            {tasks.map(task => {
              const status = normalizeTaskStatus(task.status);
              const percent = boundedBackendProgress(task.percent ?? task.progress_pct);
              const done = status === 'completed';
              return <tr key={task.task_id}><td className="hevi-task-id">#{task.task_id.slice(0, 8)}</td><td>{labelFor(task)}<br /><small>production {task.production_id ?? '—'} · revision {task.revision_id ?? '—'}</small></td><td>{percent === null ? '—' : <><div className="hevi-task-progress"><i style={{ width: `${percent}%` }} /></div><small>{percent}%</small></>}</td><td>{task.stage ?? '后端未提供阶段'}</td><td><span className={`hevi-task-status hevi-task-status--${status}`}>{TASK_STATUS_LABELS[status]}</span></td><td><button className="hevi-task-action" onClick={() => setSelectedTaskId(task.task_id)}>查看 evidence</button>{done && <a className="hevi-task-action" href={taskApi.videoUrl(task.task_id)} download>下载</a>}</td></tr>;
            })}
          </tbody></table></div>
        )}
      </section>

      {selectedTaskId && <ProductionEvidencePanel taskId={selectedTaskId} onClose={() => setSelectedTaskId(null)} />}

      <section className="hevi-task-section hevi-task-assets">
        <div className="hevi-task-section__head"><div><h2>媒体交付库</h2><p>成片、封面、字幕与导出记录统一从任务产物索引读取。</p></div><button className="hevi-task-action" onClick={() => router.push('/account')}>打开完整资产库 →</button></div>
        <div className="hevi-asset-grid">{tasks.filter(task => normalizeTaskStatus(task.status) === 'completed').slice(0, 6).map(task => <article className="hevi-asset-card" key={task.task_id}><div className="hevi-asset-card__thumb">▶</div><div><strong>{labelFor(task)}</strong><span>{task.created_at ? new Date(task.created_at).toLocaleString() : '后端未提供时间'}</span></div><a href={taskApi.videoUrl(task.task_id)} download>下载 MP4</a></article>)}{tasks.every(task => normalizeTaskStatus(task.status) !== 'completed') && <div className="hevi-task-empty">后端没有返回 completed artifact。</div>}</div>
      </section>
    </div>
  );
}
