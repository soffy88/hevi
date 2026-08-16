'use client';

/** 黄金公式动画演绎工作台: 输入故事 → 后台拆解分镜+动画出片 → 实时进度 → 预览下载。
 *
 * 链路: POST /api/cinematic/animate (202 受理) → 每 3s 轮询任务详情
 * (stage/shot_index/beats/video_path) → 完成后 video 预览 + 分镜表。
 * 进度同时可在大盘 (/dashboard) WebSocket 通道里看。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { cinematicApi } from '@/lib/api-client';
import { syncAuthToken } from '@/lib/auth-store';

const DEFAULT_STORY = '东汉鲁国, 孔融年仅四岁。一日, 父亲买回一筐鲜梨唤孩子们分食。' +
  '孔融走上前, 却拣起最小的那只梨。父亲问他为何不挑大的, 孔融说: 我年纪最小理当吃小的, ' +
  '兄长们年长理应吃大的。全家赞许, 此事传为美谈。孔融让梨, 尊老爱幼、谦逊礼让, 千古传颂。';

type BeatsItem = { index?: number; shot_size?: string; movement?: string; subject?: string; action?: string; emotion_expression?: string; atmosphere?: string; lighting?: string; duration_s?: number; narration?: string; shot_prompt?: string };

export function AnimateWorkbench() {
  const [story, setStory] = useState(DEFAULT_STORY);
  const [ratio, setRatio] = useState('16:9');
  const [submitting, setSubmitting] = useState(false);
  const [taskId, setTaskId] = useState('');
  const [status, setStatus] = useState('');
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState('');
  const [shotIndex, setShotIndex] = useState(-1);
  const [beats, setBeats] = useState<BeatsItem[]>([]);
  const [videoUrl, setVideoUrl] = useState('');
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const submit = useCallback(async () => {
    setSubmitting(true);
    setError(null);
    setBeats([]);
    setVideoUrl('');
    try {
      syncAuthToken();
      const res = await cinematicApi.animate({ story, ratio });
      setTaskId(res.task_id);
      setStatus('pending');
      setProgress(0);
    } catch (e) {
      setError(`提交失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSubmitting(false);
    }
  }, [story, ratio]);

  // 轮询任务状态
  useEffect(() => {
    if (!taskId) return;
    pollRef.current = setInterval(async () => {
      try {
        const t = await cinematicApi.get(taskId);
        setStatus(t.status);
        setProgress(t.progress);
        setStage(t.stage ?? '');
        setShotIndex(t.shot_index ?? -1);
        if (Array.isArray(t.beats)) setBeats(t.beats as BeatsItem[]);
        if (t.status === 'completed') {
          setVideoUrl(cinematicApi.videoUrl(taskId));
          if (pollRef.current) clearInterval(pollRef.current);
        } else if (t.status === 'failed') {
          setError(t.error ?? '出片失败');
          if (pollRef.current) clearInterval(pollRef.current);
        }
      } catch (e) {
        setError(`状态查询失败: ${e instanceof Error ? e.message : String(e)}`);
        if (pollRef.current) clearInterval(pollRef.current);
      }
    }, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [taskId]);

  const totalBeats = beats.length || Math.max(1, progress > 5 ? Math.ceil((progress - 10) / 10) : 1);
  const nDone = shotIndex >= 0 ? shotIndex + 1 : Math.floor((progress - 10) / (80 / totalBeats));

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <header>
        <h1 className="text-2xl font-bold">🎬 动画演绎工坊</h1>
        <p className="mt-1 text-sm text-zinc-500">
          输入一个历史故事 → 黄金公式 <code>[景别/运镜]+[主体+动作+表情]+[氛围/光线]</code> 自动拆解分镜 →
          AI 动画出片 (wan2.7-t2v) + 解说配音, 完整交代故事。
        </p>
      </header>

      <div className="space-y-2">
        <label className="block text-sm font-medium">故事文本</label>
        <textarea
          value={story}
          onChange={(e) => setStory(e.target.value)}
          rows={7}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 p-3 text-sm"
          placeholder="在这里输入要演绎的历史故事/寓言, 需包含起因经过结果。"
        />
        <div className="flex items-center gap-4">
          <label className="text-sm font-medium">画幅</label>
          {['16:9', '9:16', '1:1'].map((r) => (
            <button
              key={r}
              onClick={() => setRatio(r)}
              className={`rounded-full px-3 py-1 text-xs ${ratio === r ? 'bg-blue-600 text-white' : 'bg-zinc-800 text-zinc-400'}`}
            >
              {r}
            </button>
          ))}
          <button
            onClick={submit}
            disabled={submitting || story.trim().length < 8}
            className="ml-auto rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white disabled:opacity-40"
          >
            {submitting ? '提交中…' : '🚀 开始动画演绎'}
          </button>
        </div>
        {error && <p className="text-sm text-red-400">{error}</p>}
      </div>

      {taskId && (
        <section className="rounded-xl border border-zinc-800 bg-zinc-950 p-4">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm">
                任务 <code className="text-blue-400">{taskId}</code>
                <span className={`ml-2 rounded-full px-2 py-0.5 text-xs ${status === 'completed' ? 'bg-green-900 text-green-300' : status === 'failed' ? 'bg-red-900 text-red-300' : 'bg-blue-900 text-blue-300'}`}>
                  {status}
                </span>
              </p>
              <p className="mt-1 text-xs text-zinc-500">
                {stage || '排队中…'}{stage && shotIndex >= 0 ? ` (第 ${shotIndex + 1}/${totalBeats} 镜)` : ''}
              </p>
            </div>
            <div className="text-right">
              <p className="text-2xl font-bold text-blue-400">{progress}%</p>
              <div className="mt-1 h-2 w-48 overflow-hidden rounded-full bg-zinc-800">
                <div className="h-full bg-blue-500 transition-all" style={{ width: `${progress}%` }} />
              </div>
            </div>
          </div>

          {beats.length > 0 && (
            <div className="mt-4 space-y-2">
              <p className="text-xs font-medium text-zinc-400">黄金公式分镜矩阵 ({beats.length} 镜)</p>
              {beats.map((b, i) => (
                <div key={i} className="rounded-lg bg-zinc-900 p-3 text-xs">
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-blue-300">{i + 1}</span>
                    <span className="font-medium">{b.shot_size} · {b.movement}</span>
                    <span className="text-zinc-500">{b.duration_s}s</span>
                    {i <= nDone && status !== 'failed' && <span className="ml-auto text-green-400">✓</span>}
                  </div>
                  <p className="mt-1 text-zinc-400">
                    {[b.subject, b.action, b.emotion_expression, b.atmosphere, b.lighting].filter(Boolean).join(' | ')}
                  </p>
                </div>
              ))}
            </div>
          )}

          {videoUrl && (
            <div className="mt-4">
              <video controls className="w-full rounded-lg" src={videoUrl} />
              <div className="mt-2 flex gap-3">
                <a href={videoUrl} download className="text-sm text-blue-400 underline">下载视频</a>
                <a href="/dashboard" className="text-sm text-zinc-500 underline">在大盘查看</a>
              </div>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
