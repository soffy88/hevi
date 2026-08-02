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
import { presenterApi, productionApi, taskApi, subjectApi, providerApi, USE_MOCK } from '@/lib/api-client';
import type { ProductionSource, Presenter, ProviderPreset } from '@/types/api';
import { prefillDirector, type HubAdapterMode, type HubExecutionPreset } from '@/lib/director-prefill';
import { enhanceIdea, splitIdeaScenes, IDEA_STYLES, type IdeaStyle } from '@/lib/prompt-enhancer';
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

const ADAPTERS: Array<{ id: HubAdapterMode; label: string; icon: string; category: GalleryCategory; source: ProductionSource; hint: string }> = [
  { id: 'default', label: '极简单片', icon: '⚡', category: 'short_video', source: 'automatic', hint: '一句话 → 自动规划与出片' },
  { id: 'idea2video', label: '创意极速', icon: '💡', category: 'short_video', source: 'automatic', hint: '一句话 → Prompt 增强 → 直接出片 (Idea2Video)' },
  { id: 'explainer', label: '头像解说', icon: '🎙️', category: 'avatar_narration', source: 'explainer', hint: '文案 → 配音、字幕与数字人' },
  { id: 'tongjian', label: '资治通鉴', icon: '📜', category: 'long_video', source: 'tongjian', hint: '史料 → 带出处的讲述成片' },
  { id: 'shortdrama', label: '故事短剧', icon: '🎬', category: 'short_video', source: 'shortdrama', hint: '梗概 → 分集规划与出片' },
];

const EXECUTION_PRESETS: Array<{ id: HubExecutionPreset; label: string; hint: string }> = [
  { id: 'economy', label: '💰 省钱', hint: '本地优先 · 低成本' },
  { id: 'balanced', label: '⚖️ 均衡', hint: '推荐 · 质量与成本平衡' },
  { id: 'fast', label: '⚡ 极速', hint: '云端优先 · 更快交付' },
];

// 字幕烧录样式(与后端 hevi/assembly/subtitle_styles.py + 导演台 SUBTITLE_STYLES 对齐)。
// 仅「头像解说」适配器显示(§2.2):数字人预设 + 字幕样式。
const SUBTITLE_STYLES: { v: string; l: string }[] = [
  { v: 'default', l: '默认' },
  { v: 'bold_yellow', l: '粗体黄' },
  { v: 'large_white', l: '大号白字' },
  { v: 'compact', l: '紧凑' },
];

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
  const [adapterMode, setAdapterMode] = useState<HubAdapterMode>('default');
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
  const [executionPreset, setExecutionPreset] = useState<HubExecutionPreset>('balanced');
  const [presenters, setPresenters] = useState<Presenter[]>([]);
  const [presenterId, setPresenterId] = useState('');
  const [subtitleStyle, setSubtitleStyle] = useState('default');
  const [episodeCount, setEpisodeCount] = useState(1);

  // Idea2Video(SPEC v6.0 §2.1):创意增强 + Provider Preset 选单
  const [ideaStyle, setIdeaStyle] = useState<IdeaStyle>('cinematic');
  const [ideaMaxScenes, setIdeaMaxScenes] = useState(4);
  const [ideaEnhance, setIdeaEnhance] = useState(true);
  const [providerPresets, setProviderPresets] = useState<ProviderPreset[]>([]);
  const [providerPreset, setProviderPreset] = useState('wan_local');

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

  const switchAdapter = (mode: HubAdapterMode) => {
    const adapter = ADAPTERS.find(item => item.id === mode)!;
    setAdapterMode(mode);
    switchCategory(adapter.category);
    setPresenterId(mode === 'explainer' ? presenterId : '');
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

  useEffect(() => {
    if (USE_MOCK || !isAuthenticated()) return;
    presenterApi.list().then(setPresenters).catch(() => setPresenters([]));
    // Provider Preset 预置表(obase 下沉,SPEC v6.0 §2.4)
    providerApi.listPresets('video')
      .then(r => { if (r.presets.length > 0) { setProviderPresets(r.presets); setProviderPreset(r.presets[0]!.name); } })
      .catch(() => setProviderPresets([]));
  }, []);

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
      // Idea2Video:Prompt Enhancer 预处理 → 直接调用统一生成能力(SPEC v6.0 §2.1)
      const isIdea = adapterMode === 'idea2video';
      const enhanced = isIdea && ideaEnhance && topic.trim()
        ? enhanceIdea({ idea: topic.trim(), style: ideaStyle, aspectRatio: aspect, maxScenes: ideaMaxScenes })
        : null;
      const t = await productionApi.generate({
        source_channel: isIdea ? 'hub_idea2video' : 'hub_quick',
        adapter_type: isIdea ? 'default' : adapterMode,
        config: {
          prompt: enhanced ? enhanced.prompt : topic.trim(),
          duration_archetype: duration,
          aspect_ratio: aspect,
          execution_preset: executionPreset,
          character_references: selectedSubjectId ? [selectedSubjectId] : [],
          presenter_id: presenterId || null,
          quality_profile: quality,
          options: {
            style_preset: style,
            provider_preset: isIdea ? providerPreset : undefined,
            idea_scenes: enhanced ? enhanced.scenes : undefined,
            subtitle_style: adapterMode === 'explainer' ? subtitleStyle : undefined,
            episode_count: adapterMode === 'shortdrama' ? episodeCount : undefined,
          },
        },
      });
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
        <p className="hevi-home__eyebrow">Automated Generation Hub</p>
        <h1 className="hevi-home__headline">生成中心</h1>

        <div className="hevi-home__categories" role="tablist" aria-label="内容适配器">
          {ADAPTERS.map(adapter => (
            <button key={adapter.id} type="button" className="hevi-home__cat"
              data-active={adapterMode === adapter.id ? 'true' : undefined}
              onClick={() => switchAdapter(adapter.id)}>
              <span>{adapter.icon}</span> {adapter.label}
            </button>
          ))}
        </div>

        {/* 大 prompt 框 */}
        <textarea
          className="hevi-home__prompt"
          placeholder={adapterMode === 'idea2video' ? '输入一句话创意，自动 Prompt 增强与风格润色后直接出片…' : adapterMode === 'tongjian' ? '粘贴史料原文、章节名或 quote_id…' : adapterMode === 'shortdrama' ? '输入小说梗概或故事大纲…' : adapterMode === 'explainer' ? '输入解说文案或主题…' : '用一句话，生成你想要的视频…'}
          value={topic}
          onChange={e => setTopic(e.target.value)}
          rows={4}
        />

        {/* Idea2Video 创意增强区(SPEC v6.0 §2.1) */}
        {adapterMode === 'idea2video' && (
          <div className="hevi-home__idea">
            <div className="hevi-home__idea-bar">
              <label className="hevi-home__opt">
                <span className="hevi-home__idea-label">💡 Prompt 增强</span>
                <select value={ideaEnhance ? 'on' : 'off'} onChange={e => setIdeaEnhance(e.target.value === 'on')}>
                  <option value="on">开启（推荐）</option>
                  <option value="off">关闭</option>
                </select>
              </label>
              <label className="hevi-home__opt">
                <span className="hevi-home__idea-label">风格</span>
                <select value={ideaStyle} onChange={e => setIdeaStyle(e.target.value as IdeaStyle)}>
                  {IDEA_STYLES.map(s => <option key={s.id} value={s.id}>{s.label}</option>)}
                </select>
              </label>
              <label className="hevi-home__opt">
                <span className="hevi-home__idea-label">分镜数</span>
                <select value={ideaMaxScenes} onChange={e => setIdeaMaxScenes(Number(e.target.value))}>
                  {[2, 3, 4, 5, 6, 8].map(n => <option key={n} value={n}>{n} 个</option>)}
                </select>
              </label>
              <label className="hevi-home__opt">
                <span className="hevi-home__idea-label">Provider Preset</span>
                <select value={providerPreset} onChange={e => setProviderPreset(e.target.value)}>
                  {providerPresets.length === 0 && <option value="wan_local">wan_local（本地默认）</option>}
                  {providerPresets.map(p => <option key={p.name} value={p.name}>{p.name} · {p.description}</option>)}
                </select>
              </label>
            </div>
            {ideaEnhance && topic.trim().length >= 4 && (
              <div className="hevi-home__idea-preview">
                <div className="hevi-home__idea-preview-head">🔍 增强预览（{splitIdeaScenes(topic.trim(), ideaMaxScenes).length} 个分镜）</div>
                <pre>{enhanceIdea({ idea: topic.trim(), style: ideaStyle, aspectRatio: aspect, maxScenes: ideaMaxScenes }).prompt}</pre>
              </div>
            )}
            {adapterMode === 'idea2video' && !ideaEnhance && (
              <p className="hevi-home__adapter-hint">💡 关闭增强后直接按原句出片（provider_preset 仍生效）。</p>
            )}
          </div>
        )}

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
          {adapterMode === 'explainer' && (
            <div className="hevi-home__opt">
              <label htmlFor="hub-presenter">数字人预设</label>
              <select id="hub-presenter" value={presenterId} onChange={e => setPresenterId(e.target.value)}>
                <option value="">旁白模式</option>
                {presenters.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
          )}
          {adapterMode === 'explainer' && (
            <div className="hevi-home__opt">
              <label htmlFor="hub-subtitle-style">字幕样式</label>
              <select id="hub-subtitle-style" value={subtitleStyle} onChange={e => setSubtitleStyle(e.target.value)}>
                {SUBTITLE_STYLES.map(s => <option key={s.v} value={s.v}>{s.l}</option>)}
              </select>
            </div>
          )}
          {adapterMode === 'tongjian' && (
            <p className="hevi-home__adapter-hint">📜 自动匹配水墨/古风风格预设,并对史料做 CG2.5 史实出处检测。</p>
          )}
          {adapterMode === 'shortdrama' && (
            <div className="hevi-home__opt">
              <label>分集数</label>
              <select value={episodeCount} onChange={e => setEpisodeCount(Number(e.target.value))}>
                {[1, 3, 5, 10].map(n => <option key={n} value={n}>{n} 集</option>)}
              </select>
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

        <div className="hevi-home__preset-block">
          <label>执行档位</label>
          <div className="hevi-home__presets">
            {EXECUTION_PRESETS.map(preset => <button type="button" key={preset.id} data-active={executionPreset === preset.id ? 'true' : undefined} onClick={() => setExecutionPreset(preset.id)}><strong>{preset.label}</strong><span>{preset.hint}</span></button>)}
          </div>
        </div>

        {/* 预估 + 生成 */}
        <div className="hevi-home__footer">
          <span className="hevi-home__estimate">
            预估 <strong>{estimate.credits.toLocaleString()}</strong> credits
            {estimate.usd > 0 && <span className="hevi-home__usd"> (${estimate.usd})</span>}
          </span>
          <button className="hevi-home__generate" disabled={!topic.trim()}
            onClick={() => setConfirming(true)}>
            ▶ 开始自动出片
          </button>
          <button type="button" className="hevi-home__director-link" disabled={!topic.trim()} onClick={() => {
            prefillDirector({ prompt: topic.trim(), adapterMode, duration, aspectRatio: aspect, characters: selectedSubjectId ? [selectedSubjectId] : [], presetLevel: executionPreset });
            router.push('/director');
          }}>🎛️ 转入导演控制台精细调优 →</button>
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
