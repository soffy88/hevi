/** v9.1 Lite 管道发射台: 输入主题 + 多行旁白 → 一键生成轻量解说视频。
 *
 * 文案按换行符拆分: 每个非空行 = 一条 cue({index, narration}),
 * 提交 POST /api/lite/assemble → 202 受理 → router 丝滑跳转 /dashboard
 * 由大盘的 WebSocket 实时通道追踪进度。
 */

'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { liteApi } from '@/lib/api-client';
import { syncAuthToken } from '@/lib/auth-store';
import type { LiteCueInput } from '@/types/api';

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

export function LiteWorkbench() {
  const router = useRouter();
  const [topic, setTopic] = useState('');
  const [script, setScript] = useState(DEFAULT_SCRIPT);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const cues = useMemo(() => splitCues(script), [script]);

  useEffect(() => {
    syncAuthToken();
  }, []);

  const submit = useCallback(async () => {
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
      // 202 受理 → 跳转大盘, 由 WebSocket 实时追踪该任务进度。
      router.push(`/dashboard?task=${encodeURIComponent(accepted.task_id)}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '提交失败,请稍后重试');
      setSubmitting(false);
    }
  }, [cues, router, submitting, topic]);

  return (
    <div className="ex-v6">
      <header className="ex-v6__hero">
        <p className="ex-v6__eyebrow">HEVI · LITE PIPELINE v9.1</p>
        <h1>轻量级解说发射台</h1>
        <p>零 GPU · 零云端 API —— 输入主题与旁白, 生成带动态 B-roll 背景、卡拉OK 词级高亮与音频的解说视频。</p>
      </header>

      <div className="lite__grid">
        <section className="lite__card" aria-label="发射参数">
          <label className="lite__label" htmlFor="lite-topic">主题 Topic</label>
          <input
            id="lite-topic"
            className="lite__input"
            type="text"
            value={topic}
            onChange={e => setTopic(e.target.value)}
            placeholder="如：波尔兹曼方程极简推导"
            maxLength={120}
          />

          <label className="lite__label" htmlFor="lite-script">旁白文案（每行 = 一个镜头）</label>
          <textarea
            id="lite-script"
            className="lite__textarea"
            value={script}
            onChange={e => setScript(e.target.value)}
            placeholder={'每行一段旁白…'}
            rows={8}
          />
          <p className="lite__hint">
            已拆分 <strong>{cues.length}</strong> 个镜头，文案按换行自动分段。
          </p>

          {error && <p className="ex-v6__error" role="alert">{error}</p>}

          <button
            type="button"
            className="lite__submit"
            disabled={submitting}
            onClick={() => void submit()}
          >
            {submitting ? '正在提交…' : '⚡ 生成视频'}
          </button>
        </section>

        <section className="lite__card" aria-label="镜头预览">
          <h2 className="lite__section-title">镜头拆解</h2>
          {cues.length === 0 && <p className="lite__hint">输入文案后将在这里预览每个镜头的旁白。</p>}
          <ol className="lite__cues">
            {cues.map(cue => (
              <li key={cue.index} className="lite__cue">
                <span className="lite__cue-index">{String(cue.index + 1).padStart(2, '0')}</span>
                <span className="lite__cue-text">{cue.narration}</span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}
