/** 任务行卡片:React.memo 化 —— 只有被 WS 更新命中的行才会重绘。
 *
 * 核心细节:进度条宽度带 CSS 过渡(transition width .5s ease-out),
 * 每次收到 WebSocket 推送时平滑向前滑动, 不生硬跳闪。
 */

'use client';

import { memo, useCallback, useState } from 'react';
import { taskApi } from '@/lib/api-client';
import { VideoPreviewModal } from '@/components/dashboard/VideoPreviewModal';
import type { DashboardTask } from '@/types/api';
import {
  boundedBackendProgress,
  normalizeTaskStatus,
  TASK_STATUS_LABELS,
} from '@/lib/backend-contract';

const PIPELINE_LABELS: Record<string, string> = {
  main_remotion: '主管道 · Remotion',
  lite_html: 'Lite 管道 · 录屏',
  realtime: '实时任务',
};

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  const hh = String(date.getHours()).padStart(2, '0');
  const min = String(date.getMinutes()).padStart(2, '0');
  return `${mm}-${dd} ${hh}:${min}`;
}

export interface TaskRowProps {
  task: DashboardTask;
}

function TaskRowInner({ task }: TaskRowProps) {
  const [detailOpen, setDetailOpen] = useState(false);
  const [detail, setDetail] = useState<DashboardTask | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);

  const status = normalizeTaskStatus(task.status);
  const label = TASK_STATUS_LABELS[status];
  const progress = boundedBackendProgress(task.progress_pct ?? task.progress);
  const stage = task.stage ?? (typeof task.state_json?.stage === 'string' ? task.state_json.stage : null);
  const productionId = task.production_id ?? (typeof task.state_json?.production_id === 'string' ? task.state_json.production_id : null);
  const revisionId = task.revision_id ?? (typeof task.state_json?.revision_id === 'string' ? task.state_json.revision_id : null);
  const rootTaskId = task.root_task_id ?? (typeof task.state_json?.root_task_id === 'string' ? task.state_json.root_task_id : null);
  const attemptId = task.current_attempt_id ?? (typeof task.state_json?.attempt_id === 'string' ? task.state_json.attempt_id : null);
  const doneSteps = Object.entries(task.state_json ?? {}).filter(
    ([, value]) => value === 'done',
  );
  const outputUrl = taskApi.videoUrl(task.task_id);

  const toggleDetail = useCallback(async () => {
    if (detailOpen) {
      setDetailOpen(false);
      return;
    }
    setDetailOpen(true);
    if (detail) return;
    setDetailLoading(true);
    setDetailError(null);
    try {
      const canonical = await taskApi.get(task.task_id);
      setDetail({
        ...canonical,
        pipeline_type: canonical.production_source ?? 'task',
        status: normalizeTaskStatus(canonical.status),
        progress: canonical.percent ?? canonical.progress_pct ?? null,
        error_log: canonical.error ?? null,
        state_json: canonical.config_json ?? null,
        created_at: canonical.created_at ?? '',
        updated_at: canonical.updated_at ?? '',
      });
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : '详情加载失败');
    } finally {
      setDetailLoading(false);
    }
  }, [detailOpen, detail, task.task_id]);

  const errorText = detail?.error_log ?? task.error_log;

  return (
    <article className={`tdash__row is-${status}`} data-testid={`task-row-${task.task_id}`}>
      <div className="tdash__row-head">
        <div className="tdash__row-id">
          <code title={task.task_id}>{task.task_id.slice(0, 10)}…</code>
          <span className={`tdash__badge is-${status}`}>{label}</span>
        </div>
        <time title={task.created_at}>{formatTime(task.created_at)}</time>
      </div>

      {progress !== null ? (
        <div className="tdash__row-bar" aria-label={`backend progress ${progress}%`}>
          <i className="tdash__row-fill" style={{ width: `${progress}%` }} />
        </div>
      ) : <p className="tdash__row-no-progress">后端尚未提供进度</p>}

      <div className="tdash__row-meta">
        <span className="tdash__pipeline">{PIPELINE_LABELS[task.pipeline_type] ?? task.pipeline_type}</span>
        <span className="tdash__pct">{progress === null ? '—' : `${progress}%`}</span>
        {stage && <span className="tdash__stage">阶段：{stage}</span>}
        {productionId && <span>Production：{productionId}</span>}
        {revisionId && <span>Revision：{revisionId}</span>}
        {rootTaskId && <span>Root：{rootTaskId}</span>}
        {attemptId && <span>Attempt：{attemptId}</span>}
        {doneSteps.length > 0 && (
          <span className="tdash__chips">
            {doneSteps.map(([step]) => <i key={step}>{step} ✓</i>)}
          </span>
        )}
      </div>

      <div className="tdash__row-actions">
        <button type="button" className="tdash__btn" onClick={() => void toggleDetail()}>
          {detailOpen ? '收起执行详情' : '查看执行详情'}
        </button>
        {status === 'completed' && (
          <>
            <button type="button" className="tdash__btn is-primary" onClick={() => setPreviewOpen(true)}>预览</button>
            <a className="tdash__btn" href={outputUrl} download>下载</a>
          </>
        )}
        {status === 'failed' && (
          <span className="tdash__failure-code">{task.error_code ?? 'failure code unavailable'}</span>
        )}
      </div>

      {detailOpen && (
        <div className="tdash__detail" role="region" aria-label="错误日志">
          {detailLoading && <p className="tdash__detail-loading">正在读取详情…</p>}
          {detailError && <p className="tdash__detail-error">{detailError}</p>}
          {!detailLoading && status === 'failed' && errorText && (
            <pre>{errorText}</pre>
          )}
          {!detailLoading && detail && (
            <div className="tdash__detail-execution">
              <p>production_id：{detail.production_id ?? '—'}</p>
              <p>revision_id：{detail.revision_id ?? '—'}</p>
              <p>root_task_id：{detail.root_task_id ?? '—'}</p>
              <p>current_attempt_id：{detail.current_attempt_id ?? '—'}</p>
              <p>step：{detail.stage ?? '—'}</p>
              <p>started_at：{detail.started_at ?? '—'}</p>
              <p>finished_at：{detail.finished_at ?? '—'}</p>
              {detail.error_code && <p>failure_code：{detail.error_code}</p>}
            </div>
          )}
          {!detailLoading && detail && Object.keys(detail.state_json ?? {}).length > 0 && (
            <div className="tdash__detail-state">
              {Object.entries(detail.state_json ?? {}).map(([step, value]) => (
                <code key={step}>{step}: {String(value)}</code>
              ))}
            </div>
          )}
        </div>
      )}


      {previewOpen && status === 'completed' && (
        <VideoPreviewModal
          taskId={task.task_id}
          title={`${task.task_id.slice(0, 12)}…`}
          src={outputUrl}
          onClose={() => setPreviewOpen(false)}
        />
      )}
    </article>
  );
}

/** 只有行对象引用变化(即被 WS 融合命中)时才重绘。 */
export const TaskRow = memo(TaskRowInner);
