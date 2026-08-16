/** 任务行卡片:React.memo 化 —— 只有被 WS 更新命中的行才会重绘。
 *
 * 核心细节:进度条宽度带 CSS 过渡(transition width .5s ease-out),
 * 每次收到 WebSocket 推送时平滑向前滑动, 不生硬跳闪。
 */

'use client';

import { memo, useCallback, useState } from 'react';
import { dashboardApi } from '@/lib/api-client';
import { VideoPreviewModal } from '@/components/dashboard/VideoPreviewModal';
import type { DashboardTask } from '@/types/api';

const STATUS_LABELS: Record<string, string> = {
  pending: '排队中',
  queued: '排队中',
  running: '渲染中',
  completed: '已完成',
  failed: '失败',
  paused: '已暂停',
};

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

  const status = task.status || 'pending';
  const label = STATUS_LABELS[status] ?? status;
  const progress = Math.max(0, Math.min(100, task.progress ?? 0));
  const doneSteps = Object.entries(task.state_json ?? {}).filter(
    ([, value]) => value === 'done',
  );
  const outputUrl = dashboardApi.outputUrl(task.task_id);

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
      setDetail(await dashboardApi.getTask(task.task_id));
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : '详情加载失败');
    } finally {
      setDetailLoading(false);
    }
  }, [detailOpen, detail, task.task_id]);

  const errorText = detail?.error_log ?? task.error_log;

  return (
    <article className={`tdash__row is-${status}`}>
      <div className="tdash__row-head">
        <div className="tdash__row-id">
          <code title={task.task_id}>{task.task_id.slice(0, 10)}…</code>
          <span className={`tdash__badge is-${status}`}>{label}</span>
        </div>
        <time title={task.created_at}>{formatTime(task.created_at)}</time>
      </div>

      <div className="tdash__row-bar">
        <i
          className="tdash__row-fill"
          style={{ width: `${Math.max(progress, status === 'running' ? 3 : 0)}%` }}
        />
      </div>

      <div className="tdash__row-meta">
        <span className="tdash__pipeline">{PIPELINE_LABELS[task.pipeline_type] ?? task.pipeline_type}</span>
        <span className="tdash__pct">{progress}%</span>
        {doneSteps.length > 0 && (
          <span className="tdash__chips">
            {doneSteps.map(([step]) => <i key={step}>{step} ✓</i>)}
          </span>
        )}
      </div>

      <div className="tdash__row-actions">
        {status === 'completed' && (
          <>
            <button type="button" className="tdash__btn is-primary" onClick={() => setPreviewOpen(true)}>预览</button>
            <a className="tdash__btn" href={outputUrl} download>下载</a>
          </>
        )}
        {status === 'failed' && (
          <button type="button" className="tdash__btn" onClick={() => void toggleDetail()}>
            {detailOpen ? '收起日志' : '查看错误日志'}
          </button>
        )}
      </div>

      {detailOpen && status === 'failed' && (
        <div className="tdash__detail" role="region" aria-label="错误日志">
          {detailLoading && <p className="tdash__detail-loading">正在读取详情…</p>}
          {detailError && <p className="tdash__detail-error">{detailError}</p>}
          {!detailLoading && errorText && (
            <pre>{errorText}</pre>
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
