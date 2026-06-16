/**
 * LongVideoForm — 长视频生成独立表单
 * 含质量档选择(1.9)+ 成本预估确认(OCostConfirmDialog)+ SSE 进度(OTaskProgress)。
 */
'use client';

import { useState } from 'react';
import { OCostConfirmDialog, OTaskProgress, useSSEProgress } from '@helios/oui';
import type {
  DurationArchetype, VideoProvider, QualityProfile, LongVideoTaskReq,
} from '@/types/api';
import { QUALITY_SPECS } from '@/types/api';
import { taskApi, USE_MOCK } from '@/lib/api-client';
import { mockEstimate } from '@/lib/mock-data';

const DURATIONS: { id: DurationArchetype; label: string }[] = [
  { id: '1-5min',   label: '1–5 分钟' },
  { id: '5-15min',  label: '5–15 分钟' },
  { id: '15-45min', label: '15–45 分钟' },
  { id: '45min+',   label: '45 分钟+' },
];

export function LongVideoForm() {
  const [topic, setTopic]       = useState('');
  const [duration, setDuration] = useState<DurationArchetype>('1-5min');
  const [provider, setProvider] = useState<VideoProvider>('ltx2_cloud');
  const [quality, setQuality]   = useState<QualityProfile>('standard');

  const [confirming, setConfirming] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);

  const estimate = mockEstimate(duration, quality);
  const progress = useSSEProgress(taskId && !USE_MOCK ? taskApi.progressUrl(taskId) : null);

  const buildReq = (): LongVideoTaskReq => ({
    topic, duration_archetype: duration, video_provider: provider, quality_profile: quality,
  });

  const start = async () => {
    setConfirming(false);
    if (USE_MOCK) { setTaskId('mock-task'); return; }
    const t = await taskApi.create(buildReq());
    setTaskId(t.task_id);
  };

  // 任务进行中 → 显示进度
  if (taskId) {
    const mockProgress = { percent: 62, stage: '渲染第 3 镜头', status: 'running' as const,
      stages: [
        { id: 's1', label: '分镜脚本', status: 'completed' as const },
        { id: 's2', label: '角色一致性', status: 'completed' as const },
        { id: 's3', label: '视频渲染', status: 'running' as const },
        { id: 's4', label: '配音合成', status: 'pending' as const },
      ] };
    const p = USE_MOCK ? mockProgress : progress;
    return (
      <div className="hevi-form-page">
        <h1 className="hevi-form-title">生成进度</h1>
        <OTaskProgress
          percent={p.percent}
          stage={p.stage}
          status={p.status}
          stages={p.stages}
          etaSeconds={USE_MOCK ? 480 : undefined}
          onResume={() => taskId && taskApi.resume(taskId)}
          onCancel={() => setTaskId(null)}
        />
      </div>
    );
  }

  return (
    <div className="hevi-form-page">
      <h1 className="hevi-form-title">长视频生成</h1>

      <label className="hevi-field">
        <span className="hevi-field-label">主题</span>
        <input className="hevi-field-input" value={topic}
          onChange={e => setTopic(e.target.value)}
          placeholder="描述你想生成的视频内容…" />
      </label>

      <div className="hevi-field">
        <span className="hevi-field-label">时长</span>
        <div className="hevi-chip-row">
          {DURATIONS.map(d => (
            <button key={d.id} type="button" className="hevi-chip"
              data-active={duration === d.id ? 'true' : undefined}
              onClick={() => setDuration(d.id)}>{d.label}</button>
          ))}
        </div>
      </div>

      <div className="hevi-field">
        <span className="hevi-field-label">视频引擎</span>
        <div className="hevi-chip-row">
          {(['ltx2_cloud', 'wan_cloud'] as VideoProvider[]).map(p => (
            <button key={p} type="button" className="hevi-chip"
              data-active={provider === p ? 'true' : undefined}
              onClick={() => setProvider(p)}>{p === 'ltx2_cloud' ? 'LTX-2' : 'WAN'}</button>
          ))}
        </div>
      </div>

      {/* 1.9 质量档选择 */}
      <div className="hevi-field">
        <span className="hevi-field-label">质量档</span>
        <div className="hevi-quality-grid">
          {QUALITY_SPECS.map(q => (
            <button key={q.profile} type="button" className="hevi-quality-card"
              data-active={quality === q.profile ? 'true' : undefined}
              onClick={() => setQuality(q.profile)}>
              <span className="hevi-quality-name">{q.profile}</span>
              <span className="hevi-quality-res">{q.resolution}</span>
              <span className="hevi-quality-meta">{q.fps}fps · {q.bitrate}</span>
              <span className="hevi-quality-mult">{q.cost_multiplier}× 成本</span>
            </button>
          ))}
        </div>
      </div>

      {/* 成本预览 + 生成 */}
      <div className="hevi-form-footer">
        <div className="hevi-cost-preview">
          预估 <strong>{estimate.credits.toLocaleString()}</strong> 积分
          {estimate.usd != null && <span> ≈ ${estimate.usd}</span>}
        </div>
        <button type="button" className="oui-btn-primary"
          disabled={!topic.trim()}
          onClick={() => setConfirming(true)}>
          生成视频
        </button>
      </div>

      <OCostConfirmDialog
        open={confirming}
        estimate={estimate}
        balance={3500}
        onConfirm={start}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}
