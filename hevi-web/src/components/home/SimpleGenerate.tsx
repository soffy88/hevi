/**
 * SimpleGenerate — 首页极简生成页(大众主入口)
 *
 * 对标即梦/Runway/Pika:prompt + 选项 → 实时预估 → 生成 → SSE 进度 → 成片。
 * 复用 OCostConfirmDialog + OTaskProgress(oui 通用层)。
 * v1 聚焦视频生成(§4)。
 */
'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth-store';
import { OCostConfirmDialog, OTaskProgress, useSSEProgress } from '@helios/oui';
import type {
  DurationArchetype, QualityProfile, AspectRatio, LongVideoTaskReq, VideoProvider,
  GalleryCategory, GalleryItem, StepProviders, PresetId, Subject,
} from '@/types/api';
import { STYLE_PRESETS } from '@/types/api';
import { taskApi, subjectApi, USE_MOCK } from '@/lib/api-client';
import { humanizeTaskError } from '@/lib/errorMessages';
import { mockEstimate } from '@/lib/mock-data';
import { Gallery } from './Gallery';
import { ProviderSelector } from './ProviderSelector';
import { PRESETS } from '@/lib/mock-data';

const CATEGORIES: { id: GalleryCategory; label: string; durations: DurationArchetype[]; defaultAspect: AspectRatio }[] = [
  { id: 'long_video',       label: '长视频',   durations: ['15-45min', '45min+'], defaultAspect: '16:9' },
  { id: 'short_video',      label: '短视频',   durations: ['short', '1-5min'],    defaultAspect: '9:16' },
  { id: 'avatar_narration', label: '头像解说', durations: ['1-5min', '5-15min'],  defaultAspect: '9:16' },
  { id: 'animation',        label: '动画',     durations: ['1-5min', '5-15min'],  defaultAspect: '16:9' },
  { id: 'image',            label: '图片',     durations: [],                     defaultAspect: '1:1' },
];

const DURATIONS: { id: DurationArchetype; label: string }[] = [
  { id: 'short', label: '极速单片 (~10秒·连贯单镜头)' },
  { id: '1-5min', label: '1–5 分钟 (多镜头分场景)' },
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

// 视频模型/画质档(真人写实)。value 对应后端 video_provider
// 成本从低到高排序;默认本地免费档(fal 云档偏贵,按需选用)。
const VIDEO_PROVIDERS: { id: VideoProvider; label: string }[] = [
  { id: 'wan_local',  label: '本地免费(Wan·零成本·需本机GPU)' },
  { id: 'ltx2_cloud', label: '极速草稿(fal·便宜·画质弱)' },
  { id: 'hailuo',     label: '海螺(fal·写实·💰中)' },
  { id: 'kling_v2',   label: '可灵v2(fal·写实·💰💰)' },
  { id: 'veo3',       label: 'Veo3(fal·最写实·💰💰💰最贵)' },
];

export function SimpleGenerate() {
  const router = useRouter();
  const [category, setCategory] = useState<GalleryCategory>('short_video');
  const [topic, setTopic] = useState('');
  const [duration, setDuration] = useState<DurationArchetype>('short');
  const [style, setStyle] = useState<string>(STYLE_PRESETS[0]);
  const [quality, setQuality] = useState<QualityProfile>('standard');
  const [aspect, setAspect] = useState<AspectRatio>('9:16');
  const [videoProvider, setVideoProvider] = useState<VideoProvider>('wan_local');  // 默认本地免费档
  const [stepProviders, setStepProviders] = useState<StepProviders>(
    PRESETS.find(p => p.id === 'balanced')!.step_providers
  );

  const [estimate, setEstimate] = useState({ credits: 0, usd: 0 });
  const [confirming, setConfirming] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);

  // 角色库(可选):选中后生成时锁定人物身份
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubjectId, setSelectedSubjectId] = useState<string | null>(null);
  const [subjectUploading, setSubjectUploading] = useState(false);
  const [subjectError, setSubjectError] = useState<string | null>(null);
  const subjectFileRef = useRef<HTMLInputElement>(null);

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
    topic, duration_archetype: duration, video_provider: videoProvider,
    quality_profile: quality, style_preset: style, aspect_ratio: aspect,
    step_providers: stepProviders,
    ...(selectedSubjectId ? { subject_id: selectedSubjectId } : {}),
  });

  // 拉取角色列表(仅非图片分类、已登录、非 mock 时)
  const refreshSubjects = async () => {
    try { setSubjects(await subjectApi.list('character')); }
    catch { /* 未登录/失败:静默,保持空列表 */ }
  };
  useEffect(() => {
    if (USE_MOCK || isImage || !isAuthenticated()) { setSubjects([]); return; }
    refreshSubjects();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [category]);

  // 上传照片建角色 → 刷新列表并自动选中
  const onSubjectFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';   // 允许再次选同一文件
    if (!file) return;
    setSubjectError(null);
    setSubjectUploading(true);
    try {
      const s = await subjectApi.fromPhoto(file);
      await refreshSubjects();
      setSelectedSubjectId(s.subject_id);
    } catch (err: unknown) {
      setSubjectError((err as { message?: string })?.message === 'NOT_AUTHENTICATED' ? '请先登录' : '上传失败,请重试');
    } finally {
      setSubjectUploading(false);
    }
  };

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
  }, [duration, quality, style, aspect, category, videoProvider]);

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
    const queueInfo = p as typeof p & { ahead?: number; estimated_wait_s?: number };
    const isLocalVideo = stepProviders.video.includes('local');
    const isQueued = !USE_MOCK && queueInfo.ahead != null;
    return (
      <div className="hevi-home">
        <div className="hevi-home__panel">
          <h1 className="hevi-home__title">生成中</h1>
          {/* 本地任务排队提示(§2)*/}
          {isLocalVideo && isQueued && (
            <div className="hevi-queue-notice">
              ⏳ 本地任务已进队列。当前排队中(前面 {queueInfo.ahead} 个),
              预计等待约 {Math.ceil((queueInfo.estimated_wait_s ?? 0) / 60)} 分钟。
              可关闭页面,稍后在「我的」查看进度。
            </div>
          )}
          <OTaskProgress
            percent={p.percent} stage={p.stage} status={p.status} stages={p.stages}
            etaSeconds={USE_MOCK ? 360 : undefined}
            errorMessage={USE_MOCK ? undefined : humanizeTaskError(progress.error)}
            onResume={() => taskId && taskApi.resume(taskId)}
            onCancel={() => setTaskId(null)}
            resultSlot={
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, alignItems: 'center' }}>
                {!USE_MOCK && progress.status === 'completed' && (
                  <video
                    src={taskApi.videoUrl(taskId)}
                    controls
                    autoPlay
                    playsInline
                    style={{ width: '100%', maxHeight: '70vh', borderRadius: 8, background: '#000' }}
                  />
                )}
                <div style={{ display: 'flex', gap: 12 }}>
                  {!USE_MOCK && progress.status === 'completed' && (
                    <a className="oui-btn" href={taskApi.videoUrl(taskId)} download>下载</a>
                  )}
                  <button className="oui-btn-primary" onClick={() => setTaskId(null)}>再生成一个</button>
                </div>
              </div>
            }
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
              <label>模型/画质</label>
              <select value={videoProvider} onChange={e => setVideoProvider(e.target.value as VideoProvider)}>
                {VIDEO_PROVIDERS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>
            </div>
          )}
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

        {/* 角色(可选):选中后生成时锁定人物身份(图片类型不显示)*/}
        {!isImage && (
          <div className="hevi-home__opt" style={{ display: 'block' }}>
            <label>角色(可选)</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 6, alignItems: 'stretch' }}>
              {/* 不锁定角色(默认)*/}
              <button type="button"
                data-active={selectedSubjectId == null ? 'true' : undefined}
                onClick={() => setSelectedSubjectId(null)}
                style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                  width: 72, height: 88, borderRadius: 8, fontSize: 12, cursor: 'pointer',
                  border: selectedSubjectId == null ? '2px solid var(--oui-accent, #6366f1)' : '1px solid #d0d0d8',
                  background: 'transparent',
                }}>
                不锁定角色
              </button>

              {subjects.map(s => {
                const active = selectedSubjectId === s.subject_id;
                return (
                  <button key={s.subject_id} type="button"
                    data-active={active ? 'true' : undefined}
                    onClick={() => setSelectedSubjectId(s.subject_id)}
                    title={s.name}
                    style={{
                      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
                      width: 72, padding: 4, borderRadius: 8, cursor: 'pointer',
                      border: active ? '2px solid var(--oui-accent, #6366f1)' : '1px solid #d0d0d8',
                      background: 'transparent',
                    }}>
                    <img src={subjectApi.imageUrl(s.subject_id)} alt={s.name}
                      onError={e => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden'; }}
                      style={{ width: 60, height: 60, objectFit: 'cover', borderRadius: 6, background: '#f0f0f4' }} />
                    <span style={{ fontSize: 12, maxWidth: 64, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
                  </button>
                );
              })}

              {/* + 上传照片建角色 */}
              <button type="button" className="oui-btn"
                disabled={subjectUploading}
                onClick={() => subjectFileRef.current?.click()}
                style={{ width: 72, height: 88, borderRadius: 8, fontSize: 12, borderStyle: 'dashed' }}>
                {subjectUploading ? '上传中…' : '+ 上传照片'}
              </button>
              <input ref={subjectFileRef} type="file" accept="image/*" hidden onChange={onSubjectFile} />
            </div>
            {subjectError && <div style={{ color: '#e5484d', fontSize: 12, marginTop: 4 }}>{subjectError}</div>}
          </div>
        )}

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
