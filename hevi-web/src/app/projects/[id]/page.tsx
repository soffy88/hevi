/**
 * Project Detail page - P2: Project Detail view
 * 
 * Shows video preview, status, progress, and actions
 * Production details collapsed by default
 */
'use client';

import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import { taskApi } from '@/lib/api-client';
import { useSSEProgress } from '@helios/oui';
import type { TaskInfo } from '@/types/api';

export default function ProjectDetailPage() {
  const params = useParams();
  const projectId = params.id as string;
  const [project, setProject] = useState<TaskInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const progress = useSSEProgress(projectId ? taskApi.progressUrl(projectId) : null);

  useEffect(() => {
    if (!projectId) return;
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const task = await taskApi.get(projectId);
        if (alive && task) {
          setProject(task);
        }
      } catch (err: unknown) {
        if (alive) {
          setError((err as { message?: string })?.message || '无法加载项目详情');
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [projectId]);

  if (loading) {
    return (
      <div className="project-detail">
        <div className="project-detail__loading">加载中...</div>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="project-detail">
        <div className="project-detail__error">
          <h2>无法加载项目</h2>
          <p>{error || '项目不存在'}</p>
        </div>
      </div>
    );
  }

  const isComplete = project.status === 'completed';
  const isFailed = project.status === 'failed';

  const videoSrc = project.result_video_path ? taskApi.videoUrl(project.task_id) : undefined;

  return (
    <div className="project-detail">
      <header className="project-detail__header">
        <h1 className="project-detail__title">任务 #{project.task_id.slice(0, 8)}</h1>
        <div className="project-detail__meta">
          <span className={`project-detail__status project-detail__status--${project.status}`}>
            {project.status}
          </span>
          <span className="project-detail__type">任务</span>
        </div>
      </header>

      {/* Video Preview */}
      <div className="project-detail__video">
        {!isComplete && (
          <div className="project-detail__progress">
            <div className="project-detail__progress-bar">
              <div className="project-detail__progress-fill"
                style={{ width: `${project.percent}%` }} />
            </div>
            <span className="project-detail__progress-text">
              {project.percent}% {progress?.stage && `· ${progress.stage}`}
            </span>
          </div>
        )}
      </div>

      {/* Actions */}
      <div className="project-detail__actions">
        {isComplete && videoSrc && (
          <a href={videoSrc} download className="project-detail__btn project-detail__btn--primary">
            下载
          </a>
        )}
        <button className="project-detail__btn" disabled={isComplete}>
          继续编辑
        </button>
        <button className="project-detail__btn" onClick={() => window.location.reload()}>
          重新生成
        </button>
        <button className="project-detail__btn">发布</button>
      </div>

      {/* Production Details - Collapsed by default */}
      <details className="project-detail__production-info">
        <summary className="project-detail__production-summary">生产详情 &gt;</summary>
        <div className="project-detail__production-content">
          <dl className="project-detail__production-grid">
            <dt>任务 ID</dt>
            <dd>{project.task_id}</dd>
            <dt>类型</dt>
            <dd>任务</dd>
            <dt>状态</dt>
            <dd>{project.status}</dd>
            <dt>进度</dt>
            <dd>{project.percent}%</dd>
            <dt>创建时间</dt>
            <dd>{new Date(project.created_at!).toLocaleString()}</dd>
            {project.error && (
              <>
                <dt>错误</dt>
                <dd>{project.error}</dd>
              </>
            )}
          </dl>
        </div>
      </details>
    </div>
  );
}