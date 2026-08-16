/** Lite 完整闭环发射台。
 *
 * 流程(html-video × hevi):
 *   1. 输入选题 → POST /api/lite/runs → LLM 出文案 + veya-loop 审稿
 *   2. awaiting_confirm: 展示裁决/分镜,可改稿、再审、确认
 *   3. confirm → 本地 HTML/Playwright/ffmpeg 零云端视频费出片
 *   4. 兼容直出:手写旁白可跳过审稿直接 assemble
 */

'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { liteApi } from '@/lib/api-client';
import { syncAuthToken } from '@/lib/auth-store';
import type { LiteCueInput, LiteRunRecord, LiteScriptVerdict } from '@/types/api';

const DEFAULT_SCRIPT = [
  '今天我们用三分钟，彻底讲清一个概念。',
  '首先，我们需要理解问题的核心假设。',
  '其次，用简单的例子建立直观感受。',
  '最后，把直觉收敛成严谨的结论。',
].join('\n');

function splitCues(text: string): LiteCueInput[] {
  return text
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map((narration, index) => ({ index, narration }));
}

function cuesToScript(cues: LiteCueInput[] | undefined | null): string {
  if (!cues?.length) return '';
  return cues.map(c => c.narration).join('\n');
}

function latestVerdict(run: LiteRunRecord | null): LiteScriptVerdict | null {
  const list = run?.loop?.verdicts;
  if (!list?.length) return null;
  return list[list.length - 1] ?? null;
}

type Mode = 'topic' | 'manual';

export function LiteWorkbench() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>('topic');
  const [topic, setTopic] = useState('');
  const [script, setScript] = useState(DEFAULT_SCRIPT);
  const [targetCues, setTargetCues] = useState(5);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState<LiteRunRecord | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const cues = useMemo(() => splitCues(script), [script]);
  const verdict = latestVerdict(run);
  const awaiting = run?.status === 'awaiting_confirm';
  const busyDraft =
    run?.status === 'drafting' || run?.status === 'reviewing' || submitting;
  const rendering = run?.status === 'rendering';
  // 有 draft 即可预览;用 progress+cues 长度作 cache-bust 键
  const previewBust = `${run?.progress ?? 0}-${run?.draft?.cues?.length ?? 0}-${script.length}`;
  const showPreview =
    !!run?.run_id &&
    !!run.draft?.cues?.length &&
    (awaiting || run.status === 'completed' || run.status === 'failed' || !!run.preview_html_path);

  useEffect(() => {
    syncAuthToken();
  }, []);

  const stopPoll = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => () => stopPoll(), [stopPoll]);

  const startPoll = useCallback(
    (runId: string) => {
      stopPoll();
      pollRef.current = setInterval(() => {
        void liteApi
          .getRun(runId)
          .then(next => {
            setRun(next);
            if (next.draft?.cues?.length && next.status === 'awaiting_confirm') {
              setScript(cuesToScript(next.draft.cues));
            }
            if (
              next.status === 'awaiting_confirm' ||
              next.status === 'failed' ||
              next.status === 'completed'
            ) {
              // 审稿结束停轮询;出片完成后也停
              stopPoll();
            }
            if (next.status === 'completed' && next.task_id) {
              stopPoll();
              router.push(`/dashboard?task=${encodeURIComponent(next.task_id)}`);
            }
          })
          .catch(err => {
            setError(err instanceof Error ? err.message : '轮询失败');
          });
      }, 1200);
    },
    [router, stopPoll],
  );

  const startFromTopic = useCallback(async () => {
    if (busyDraft) return;
    const topicTrimmed = topic.trim();
    if (!topicTrimmed) {
      setError('请先填写选题');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const created = await liteApi.createRun({
        topic: topicTrimmed,
        target_cues: targetCues,
        max_rounds: 3,
        width: 720,
        height: 1280,
        fps: 24,
      });
      setRun(created);
      startPoll(created.run_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '出稿失败');
    } finally {
      setSubmitting(false);
    }
  }, [busyDraft, startPoll, targetCues, topic]);

  const saveEdits = useCallback(
    async (reloop: boolean) => {
      if (!run?.run_id) return;
      if (cues.length === 0) {
        setError('文案至少需要一行旁白');
        return;
      }
      setSubmitting(true);
      setError(null);
      try {
        const next = await liteApi.patchScript(run.run_id, {
          script,
          reloop,
          max_rounds: 2,
        });
        setRun(next);
        if (next.draft?.cues) setScript(cuesToScript(next.draft.cues));
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : '保存失败');
      } finally {
        setSubmitting(false);
      }
    },
    [cues.length, run?.run_id, script],
  );

  const confirmRender = useCallback(async () => {
    if (!run?.run_id) return;
    if (cues.length === 0) {
      setError('文案至少需要一行旁白');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const next = await liteApi.confirm(run.run_id, { script });
      setRun(next);
      startPoll(next.run_id);
      if (next.task_id) {
        // 渲染已入队,也可直接去大盘看进度
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '确认出片失败');
      setSubmitting(false);
    }
  }, [cues.length, run?.run_id, script, startPoll]);

  const directAssemble = useCallback(async () => {
    if (submitting) return;
    const topicTrimmed = topic.trim();
    if (!topicTrimmed) {
      setError('请先填写主题 (topic)');
      return;
    }
    if (cues.length === 0) {
      setError('文案至少需要一行旁白');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const accepted = await liteApi.assemble({
        topic: topicTrimmed,
        cues,
        width: 720,
        height: 1280,
        fps: 24,
      });
      router.push(`/dashboard?task=${encodeURIComponent(accepted.task_id)}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '提交失败,请稍后重试');
      setSubmitting(false);
    }
  }, [cues, router, submitting, topic]);

  return (
    <div className="ex-v6">
      <header className="ex-v6__hero">
        <p className="ex-v6__eyebrow">HEVI · LITE PIPELINE · VEYA LOOP</p>
        <h1>本地零费用解说发射台</h1>
        <p>
          选题 → LLM 文案 → veya-loop 审稿 → 你确认 → HTML/Playwright/ffmpeg
          本机出片。无云端视频生成费用。
        </p>
      </header>

      <div className="lite__mode-tabs" role="tablist" aria-label="模式">
        <button
          type="button"
          role="tab"
          className={`lite__tab${mode === 'topic' ? ' is-active' : ''}`}
          aria-selected={mode === 'topic'}
          onClick={() => setMode('topic')}
        >
          选题自动出稿
        </button>
        <button
          type="button"
          role="tab"
          className={`lite__tab${mode === 'manual' ? ' is-active' : ''}`}
          aria-selected={mode === 'manual'}
          onClick={() => setMode('manual')}
        >
          手写旁白直出
        </button>
      </div>

      <div className="lite__grid">
        <section className="lite__card" aria-label="发射参数">
          <label className="lite__label" htmlFor="lite-topic">
            选题 Topic
          </label>
          <input
            id="lite-topic"
            className="lite__input"
            type="text"
            value={topic}
            onChange={e => setTopic(e.target.value)}
            placeholder="如：波尔兹曼方程极简推导"
            maxLength={120}
            disabled={busyDraft || rendering}
          />

          {mode === 'topic' && (
            <>
              <label className="lite__label" htmlFor="lite-target-cues">
                目标镜头数 {targetCues}
              </label>
              <input
                id="lite-target-cues"
                className="lite__input"
                type="range"
                min={3}
                max={10}
                value={targetCues}
                onChange={e => setTargetCues(Number(e.target.value))}
                disabled={busyDraft || rendering || awaiting}
              />
            </>
          )}

          {(mode === 'manual' || awaiting || run?.draft) && (
            <>
              <label className="lite__label" htmlFor="lite-script">
                旁白文案（每行 = 一个镜头）
              </label>
              <textarea
                id="lite-script"
                className="lite__textarea"
                value={script}
                onChange={e => setScript(e.target.value)}
                placeholder={'每行一段旁白…'}
                rows={8}
                disabled={rendering || (mode === 'topic' && busyDraft && !awaiting)}
              />
              <p className="lite__hint">
                已拆分 <strong>{cues.length}</strong> 个镜头
                {run?.draft?.title ? ` · 标题：${run.draft.title}` : ''}
              </p>
            </>
          )}

          {error && (
            <p className="ex-v6__error" role="alert">
              {error}
            </p>
          )}

          {run && (
            <p className="lite__status" data-status={run.status}>
              状态：<strong>{run.status}</strong>
              {typeof run.progress === 'number' ? ` · ${run.progress}%` : ''}
              {run.loop
                ? ` · veya ${run.loop.rounds} 轮 · ${run.loop.passed ? '通过' : '待人审'}`
                : ''}
              {run.error ? ` · ${run.error}` : ''}
            </p>
          )}

          {mode === 'topic' && !awaiting && !rendering && (
            <button
              type="button"
              className="lite__submit"
              disabled={busyDraft}
              onClick={() => void startFromTopic()}
            >
              {busyDraft ? '正在出稿 + 审稿…' : '① 出文案并 veya 审核'}
            </button>
          )}

          {awaiting && (
            <div className="lite__actions">
              <button
                type="button"
                className="lite__submit lite__submit--ghost"
                disabled={submitting}
                onClick={() => void saveEdits(false)}
              >
                保存改稿
              </button>
              <button
                type="button"
                className="lite__submit lite__submit--ghost"
                disabled={submitting}
                onClick={() => void saveEdits(true)}
              >
                再跑 veya-loop
              </button>
              <button
                type="button"
                className="lite__submit"
                disabled={submitting}
                onClick={() => void confirmRender()}
              >
                {submitting || rendering ? '出片中…' : '② 确认，开始本地出片'}
              </button>
            </div>
          )}

          {mode === 'manual' && (
            <button
              type="button"
              className="lite__submit"
              disabled={submitting}
              onClick={() => void directAssemble()}
            >
              {submitting ? '正在提交…' : '⚡ 跳过审稿，直接生成'}
            </button>
          )}
        </section>

        <section className="lite__card" aria-label="审稿与镜头">
          <h2 className="lite__section-title">veya-loop 裁决</h2>
          {!verdict && (
            <p className="lite__hint">出稿后将在这里显示得分、硬伤与改写建议。</p>
          )}
          {verdict && (
            <div className="lite__verdict">
              <p>
                得分 <strong>{verdict.score.toFixed(2)}</strong>
                {' · '}
                {verdict.passed ? '✅ 通过' : '⚠ 需确认'}
                {' · '}
                {verdict.source}
              </p>
              {verdict.summary && <p className="lite__hint">{verdict.summary}</p>}
              {verdict.issues?.length > 0 && (
                <ul className="lite__issues">
                  {verdict.issues.map((iss, i) => (
                    <li key={`${iss.code}-${i}`}>
                      <span className={`lite__sev lite__sev--${iss.severity}`}>
                        {iss.severity}
                      </span>{' '}
                      {iss.message}
                      {iss.fix_hint ? ` → ${iss.fix_hint}` : ''}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <h2 className="lite__section-title">HTML 分镜预览（不落 MP4）</h2>
          {showPreview && run?.run_id ? (
            <div className="lite__preview-frame">
              <iframe
                title="Lite 审稿预览"
                className="lite__preview-iframe"
                src={liteApi.previewUrl(run.run_id, previewBust)}
                sandbox="allow-scripts allow-same-origin"
              />
              <p className="lite__hint">
                预览为计时器翻页模拟，确认后才本地录屏出片。
              </p>
            </div>
          ) : (
            <p className="lite__hint">出稿并审过后在此嵌入预览；改稿保存会刷新。</p>
          )}

          <h2 className="lite__section-title">镜头拆解</h2>
          {cues.length === 0 && (
            <p className="lite__hint">输入选题或文案后将在这里预览每个镜头。</p>
          )}
          <ol className="lite__cues">
            {cues.map(cue => (
              <li key={cue.index} className="lite__cue">
                <span className="lite__cue-index">
                  {String(cue.index + 1).padStart(2, '0')}
                </span>
                <span className="lite__cue-text">{cue.narration}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}
