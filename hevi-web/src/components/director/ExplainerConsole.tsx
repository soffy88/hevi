/**
 * ExplainerConsole — 自媒体解说短视频控制台(hevi.explainer)
 * 输入一个选题 → 一键生成文案分镜 → 配音 → Remotion 渲染竖屏/横屏成片
 */
'use client';

import { useState, useEffect, useRef } from 'react';
import { explainerApi } from '@/lib/api-client';
import type { ExplainerRunStatus } from '@/types/api';

const LAYER_LABELS: Record<string, string> = {
  E0: '选题 → 文案分镜',
  E1: '结构校验',
  E2: '配音 + 渲染出片',
};

const STATUS_ICON: Record<string, string> = {
  PENDING: '○',
  RUNNING: '⟳',
  PASSED: '✓',
  FAILED: '✗',
};

const STATUS_CLASS: Record<string, string> = {
  PENDING: 'ex-layer--pending',
  RUNNING: 'ex-layer--running',
  PASSED: 'ex-layer--passed',
  FAILED: 'ex-layer--failed',
};

const DEMO_TOPICS = ['沉没成本', '拖延症', '为什么我们容易冲动消费'];

export function ExplainerConsole() {
  const [topic, setTopic] = useState('');
  const [busy, setBusy] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<ExplainerRunStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!runId) return;
    const poll = async () => {
      try {
        const s = await explainerApi.getStatus(runId);
        setStatus(s);
        if (s.status === 'COMPLETED' || s.status === 'FAILED') {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        // 静默:网络偶发失败不清状态
      }
    };
    poll();
    pollRef.current = setInterval(poll, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [runId]);

  async function startPipeline() {
    if (!topic.trim()) { setErr('请输入选题'); return; }
    setErr(null);
    setBusy(true);
    setStatus(null);
    try {
      const r = await explainerApi.startRun({ topic });
      setRunId(r.run_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : '出错了');
    } finally {
      setBusy(false);
    }
  }

  const allDone = status?.status === 'COMPLETED' || status?.status === 'FAILED';
  const completedCount = status?.layers?.filter(l => l.status === 'PASSED').length ?? 0;
  const totalLayers = status?.layers?.length ?? 3;

  return (
    <div className="ex">
      <div className="ex__hero">
        <h1 className="ex__title">解说短视频自动成片</h1>
        <p className="ex__sub">
          输入一个选题,零人工干预输出抖音风格解说短视频(文案、配音、动态图文、字幕)
        </p>
        <div className="ex__badges">
          <span className="ex__badge">E0 文案分镜</span>
          <span className="ex__badge-arrow">→</span>
          <span className="ex__badge">E1 校验</span>
          <span className="ex__badge-arrow">→</span>
          <span className="ex__badge">E2 配音</span>
          <span className="ex__badge-arrow">→</span>
          <span className="ex__badge ex__badge--end">竖屏+横屏成片</span>
        </div>
      </div>

      <section className="ex-sec">
        <div className="ex-sec__head">
          <span className="ex-sec__num">①</span>
          <h2>选题</h2>
        </div>
        <div className="ex-demos">
          {DEMO_TOPICS.map(t => (
            <button key={t} type="button" className="ex-demo-btn" onClick={() => setTopic(t)}>
              填入示例:{t}
            </button>
          ))}
        </div>
        <label className="ex-field">
          <span className="ex-field__label">选题(一句话,如"沉没成本")</span>
          <input value={topic} onChange={e => setTopic(e.target.value)}
            placeholder="沉没成本" />
        </label>
      </section>

      <div className="ex-actions">
        <button type="button" className="ex-btn ex-btn--primary"
          onClick={startPipeline} disabled={busy || (!allDone && !!runId)}>
          {busy ? '提交中…' : (!allDone && runId) ? '流水线运行中…' : '▶ 一键出片'}
        </button>
        {runId && allDone && (
          <button type="button" className="ex-btn"
            onClick={() => { setRunId(null); setStatus(null); }}>
            重新开始
          </button>
        )}
      </div>

      {err && <div className="ex-err">{err}</div>}

      {status && (
        <div className="ex-progress">
          <div className="ex-progress__head">
            <span className={`ex-run-badge ex-run-badge--${status.status.toLowerCase()}`}>
              {status.status === 'RUNNING' ? '⟳ 运行中' :
               status.status === 'COMPLETED' ? '✓ 已完成' :
               status.status === 'FAILED' ? '✗ 失败' : '待机'}
            </span>
            <span className="ex-progress__count">{completedCount}/{totalLayers} 层完成</span>
            {status.current_layer && status.status === 'RUNNING' && (
              <span className="ex-progress__cur">
                当前:{LAYER_LABELS[status.current_layer] ?? status.current_layer}
              </span>
            )}
          </div>

          <div className="ex-bar">
            <div className="ex-bar__fill"
              style={{ width: `${Math.round(completedCount / totalLayers * 100)}%` }} />
          </div>

          <div className="ex-layers">
            {status.layers.map(l => (
              <div key={l.layer} className={`ex-layer ${STATUS_CLASS[l.status] ?? ''}`}>
                <span className="ex-layer__icon">{STATUS_ICON[l.status] ?? '○'}</span>
                <span className="ex-layer__code">{l.layer}</span>
                <span className="ex-layer__name">{LAYER_LABELS[l.layer] ?? l.layer}</span>
                {l.status === 'RUNNING' && <span className="ex-layer__spin" />}
                {l.error && <span className="ex-layer__err" title={l.error}>!</span>}
              </div>
            ))}
          </div>

          {status.status === 'COMPLETED' && (
            <div className="ex-result">
              <div className="ex-result__head">🎬 成片已完成</div>
              <p className="ex-result__path">竖屏:{status.result_portrait_path}</p>
              <p className="ex-result__path">横屏:{status.result_landscape_path}</p>
              <p className="ex-hint">成片已落盘,可在服务器上直接取用。</p>
            </div>
          )}

          {status.status === 'FAILED' && (
            <div className="ex-result ex-result--fail">
              <div className="ex-result__head">流水线失败</div>
              <p className="ex-hint">{status.error ?? '未知错误'}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
