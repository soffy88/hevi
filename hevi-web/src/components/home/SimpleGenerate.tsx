/**
 * SimpleGenerate — 首页极简生成页(大众主入口)
 *
 * 对标即梦/Runway/Pika:prompt + 选项 → 实时预估 → 生成 → SSE 进度 → 成片。
 * 复用 OCostConfirmDialog + OTaskProgress(oui 通用层)。
 * v1 聚焦视频生成(§4)。
 */
'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth-store';
import { OCostConfirmDialog, OTaskProgress, useSSEProgress } from '@helios/oui';
import type {
  DurationArchetype, QualityProfile, AspectRatio, LongVideoTaskReq,
  GalleryCategory, GalleryItem, StepProviders, PresetId,
} from '@/types/api';
import { STYLE_PRESETS } from '@/types/api';
import { taskApi, USE_MOCK } from '@/lib/api-client';
import { mockEstimate } from '@/lib/mock-data';
import { Gallery } from './Gallery';
import { ProviderSelector } from './ProviderSelector';
import { PRESETS } from '@/lib/mock-data';

const CATEGORIES: { id: GalleryCategory; label: string; durations: DurationArchetype[]; defaultAspect: AspectRatio }[] = [
  { id: 'long_video',       label: '长视频',   durations: ['15-45min', '45min+'], defaultAspect: '16:9' },
  { id: 'short_video',      label: '短视频',   durations: ['1-5min'],             defaultAspect: '9:16' },
  { id: 'avatar_narration', label: '头像解说', durations: ['1-5min', '5-15min'],  defaultAspect: '9:16' },
  { id: 'animation',        label: '动画',     durations: ['1-5min', '5-15min'],  defaultAspect: '16:9' },
  { id: 'image',            label: '图片',     durations: [],                     defaultAspect: '1:1' },
];

const DURATIONS: { id: DurationArchetype; label: string }[] = [
  { id: '1-5min', label: '1–5 分钟' },
  { id: '5-15min', label: '5–15 分钟' },
  { id: '15-45min', label: '15–45 分钟' },
  { id: '45min+', label: '45 分钟+' },
];

const QUALITIES: { id: QualityProfile; label: string }[] = [
  { id: 'standard', label: '标清' },
  { id: 'high', label: '高清' },
  { id: 'ultra', label: '超清' },
];

const ASPECTS: AspectRatio[] = ['9:16', '16:9', '1:1'];

export function SimpleGenerate() {
  const router = useRouter();
  const [category, setCategory] = useState<GalleryCategory>('short_video');
  const [topic, setTopic] = useState('');
  const [duration, setDuration] = useState<DurationArchetype>('1-5min');
  const [style, setStyle] = useState<string>(STYLE_PRESETS[0]);
  const [quality, setQuality] = useState<QualityProfile>('standard');
  const [aspect, setAspect] = useState<AspectRatio>('9:16');
  const [stepProviders, setStepProviders] = useState<StepProviders>(
    PRESETS.find(p => p.id === 'balanced')!.step_providers
  );

  const [estimate, setEstimate] = useState({ credits: 0, usd: 0 });
  const [confirming, setConfirming] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);

  const catDef = CATEGORIES.find(c => c.id === category)!;
  const isImage = category === 'image';

  // 切分区 → 调整生成参数(各类型参数集不同)
  const switchCategory = (cat: GalleryCategory) => {
    setCategory(cat);
    const def = CATEGORIES.find(c => c.id === cat)!;
    if (def.durations.length > 0) setDuration(def.durations[0]!);
    setAspect(def.defaultAspect);
  };

  // 用同款:填回 prompt + 切类型 + 预填参数
  const useTemplate = (item: GalleryItem) => {
    setCategory(item.category);
    setTopic(item.prompt);
    const gp = item.gen_params;
    if (gp.duration_archetype) setDuration(gp.duration_archetype);
    if (gp.style_preset) setStyle(gp.style_preset);
    if (gp.quality_profile) setQuality(gp.quality_profile);
    if (gp.aspect_ratio) setAspect(gp.aspect_ratio);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const progress = useSSEProgress(taskId && !USE_MOCK ? taskApi.progressUrl(taskId) : null);

  const buildReq = (): LongVideoTaskReq => ({
    topic, duration_archetype: duration, video_provider: 'ltx2_cloud',
    quality_profile: quality, style_preset: style, aspect_ratio: aspect,
    step_providers: stepProviders,
  });

  // 选项变化 → 实时预估成本
  useEffect(() => {
    let live = true;
    (async () => {
      if (USE_MOCK) { const e = mockEstimate(duration, quality); if (live) setEstimate({ credits: e.credits, usd: e.usd ?? 0 }); return; }
      try { const e = await taskApi.estimate(buildReq()); if (live) setEstimate({ credits: e.credits, usd: e.usd ?? 0 }); }
      catch { /* 预估失败不阻塞 */ }
    })();
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [duration, quality, style, aspect, category]);

  const start = async () => {
    setConfirming(false);
    if (USE_MOCK) { setTaskId('mock-task'); return; }
    // 生成需登录:未登录跳登录页
    if (!isAuthenticated()) { router.push('/login'); return; }
    try {
      const t = await taskApi.create(buildReq());
      setTaskId(t.task_id);
    } catch (e: unknown) {
      if ((e as { message?: string })?.message === 'NOT_AUTHENTICATED') router.push('/login');
    }
  };

  // 生成中 → 进度
  if (taskId) {
    const mockP = { percent: 62, stage: '渲染第 3 镜头', status: 'running' as const,
      stages: [
        { id: 's1', label: '分镜脚本', status: 'completed' as const },
        { id: 's2', label: '画面生成', status: 'running' as const },
        { id: 's3', label: '配音合成', status: 'pending' as const },
      ] };
    const p = USE_MOCK ? mockP : progress;
    const isLocalVideo = stepProviders.video.includes('local');
    return (
      <div className="hevi-home">
        <div className="hevi-home__panel">
          <h1 className="hevi-home__title">生成中</h1>
          {/* 本地任务排队提示(§2)*/}
          {isLocalVideo && (
            <div className="hevi-queue-notice">
              ⏳ 本地任务已进队列。当前排队中(前面 2 个),预计等待约 8 分钟。
              可关闭页面,稍后在「我的」查看进度。
            </div>
          )}
          <OTaskProgress
            percent={p.percent} stage={p.stage} status={p.status} stages={p.stages}
            etaSeconds={USE_MOCK ? 360 : undefined}
            onResume={() => taskId && taskApi.resume(taskId)}
            onCancel={() => setTaskId(null)}
            resultSlot={<button className="oui-btn-primary" onClick={() => setTaskId(null)}>查看成片</button>}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="hevi-home">
      <div className="hevi-home__panel">
        <h1 className="hevi-home__headline">用一句话,生成你想要的</h1>

        {/* 5 分区 tab */}
        <div className="hevi-home__categories">
          {CATEGORIES.map(c => (
            <button key={c.id} type="button" className="hevi-home__cat"
              data-active={category === c.id ? 'true' : undefined}
              onClick={() => switchCategory(c.id)}>{c.label}</button>
          ))}
        </div>

        {/* 大 prompt 框 */}
        <textarea
          className="hevi-home__prompt"
          placeholder={isImage ? '描述你想要的图片…' : '描述你想要的视频…例如:介绍黑洞的科普短片,画面震撼,有旁白'}
          value={topic}
          onChange={e => setTopic(e.target.value)}
          rows={4}
        />

        {/* 选项(按 category 差异化)*/}
        <div className="hevi-home__options">
          {catDef.durations.length > 0 && (
            <div className="hevi-home__opt">
              <label>时长</label>
              <select value={duration} onChange={e => setDuration(e.target.value as DurationArchetype)}>
                {DURATIONS.filter(d => catDef.durations.includes(d.id)).map(d => <option key={d.id} value={d.id}>{d.label}</option>)}
              </select>
            </div>
          )}
          <div className="hevi-home__opt">
            <label>{isImage ? '图片类型' : '风格'}</label>
            <select value={style} onChange={e => setStyle(e.target.value)}>
              {isImage
                ? ['三视图', '宫格', '多机位'].map(s => <option key={s} value={s}>{s}</option>)
                : STYLE_PRESETS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="hevi-home__opt">
            <label>画质</label>
            <select value={quality} onChange={e => setQuality(e.target.value as QualityProfile)}>
              {QUALITIES.map(q => <option key={q.id} value={q.id}>{q.label}</option>)}
            </select>
          </div>
          {!isImage && (
            <div className="hevi-home__opt">
              <label>画幅</label>
              <div className="hevi-home__aspect">
                {ASPECTS.map(a => (
                  <button key={a} type="button" data-active={aspect === a ? 'true' : undefined}
                    onClick={() => setAspect(a)}>{a}</button>
                ))}
              </div>
            </div>
          )}
          {category === 'avatar_narration' && (
            <div className="hevi-home__opt">
              <label>数字人形象</label>
              <select><option>主播 A</option><option>主播 B</option></select>
            </div>
          )}
        </div>

        {/* 逐步 provider 选择(图片类型只有出图一步,不显示)*/}
        {!isImage && (
          <ProviderSelector
            category={category}
            stepProviders={stepProviders}
            onChange={(sp) => setStepProviders(sp)}
          />
        )}

        {/* 预估 + 生成 */}
        <div className="hevi-home__footer">
          <span className="hevi-home__estimate">
            预估 <strong>{estimate.credits.toLocaleString()}</strong> credits
            {estimate.usd > 0 && <span className="hevi-home__usd"> (${estimate.usd})</span>}
          </span>
          <button className="hevi-home__generate" disabled={!topic.trim()}
            onClick={() => setConfirming(true)}>
            {isImage ? '生成图片' : '生成视频'}
          </button>
        </div>
      </div>

      {/* 作品画廊(按当前分区筛选)*/}
      <Gallery category={category} onUseTemplate={useTemplate} />

      <OCostConfirmDialog
        open={confirming}
        estimate={{ credits: estimate.credits, usd: estimate.usd,
          breakdown: [
            { label: `${catDef.label} (${quality})`, credits: Math.round(estimate.credits * 0.8) },
            { label: '配音 + BGM', credits: Math.round(estimate.credits * 0.2) },
          ] }}
        balance={USE_MOCK ? 3500 : undefined}
        onConfirm={start}
        onCancel={() => setConfirming(false)}
      />
    </div>
  );
}
