/**
 * hevi mock 数据 — USE_MOCK=true 时用,后端未真跑期间让 UI 可看可点。
 */
import type {
  CreativeCapability, Subject, CanvasGraph, TaskInfo, CostEstimateRes,
} from '@/types/api';

export const MOCK_CAPABILITIES: CreativeCapability[] = [
  { id: 'three-view',   label: '角色三视图', description: '生成角色正/侧/背三视图参考', returns: 'data',
    input_schema: { character_desc: 'string', style: 'string' } },
  { id: 'storyboard',   label: '宫格分镜', description: '9/25 宫格分镜', returns: 'data',
    input_schema: { script: 'string', grid: '9|25' } },
  { id: 'story-predict',label: '剧情推演', description: 'forward/backward/both 推演剧情', returns: 'data',
    input_schema: { premise: 'string', direction: 'forward|backward|both' } },
  { id: 'multi-angle',  label: '多机位', description: '同场景多机位视角', returns: 'data',
    input_schema: { scene: 'string', angles: 'number' } },
  { id: 'transition',   label: '首尾帧过渡', description: '两帧之间生成过渡', returns: 'media',
    input_schema: { start_frame: 'string', end_frame: 'string' } },
  { id: 'element-edit', label: '元素编辑', description: 'replace/insert/delete 视频元素', returns: 'media',
    input_schema: { video_id: 'string', op: 'replace|insert|delete' } },
  { id: 'workflow/character-consistency', label: '角色一致性', description: '跨镜头角色一致性工作流', returns: 'media',
    input_schema: { subject_id: 'string', shots: 'number' } },
  { id: 'workflow/storyboard', label: '多镜头分镜', description: '多镜头分镜工作流', returns: 'media',
    input_schema: { script: 'string' } },
  { id: 'workflow/comic-to-animation', label: '漫画转动画', description: '漫画转动画', returns: 'media',
    input_schema: { comic_images: 'string[]' } },
];

export const MOCK_SUBJECTS: Subject[] = [
  { subject_id: 'sub-1', kind: 'character', name: '小明', reference_images: [], metadata: { age: 12 } },
  { subject_id: 'sub-2', kind: 'character', name: '老师', reference_images: [], metadata: {} },
  { subject_id: 'sub-3', kind: 'scene',     name: '教室',  reference_images: [], metadata: {} },
  { subject_id: 'sub-4', kind: 'product',   name: '产品A', reference_images: [], metadata: {} },
  { subject_id: 'sub-5', kind: 'portrait',  name: '主持人', reference_images: [], metadata: {} },
];

export const MOCK_CANVASES: CanvasGraph[] = [
  { id: 'cv-1', name: '产品宣传片', nodes: [], edges: [], updated_at: '2026-06-10' },
  { id: 'cv-2', name: '教学动画 第3课', nodes: [], edges: [], updated_at: '2026-06-12' },
];

export const MOCK_TASKS: TaskInfo[] = [
  { task_id: 't-1', status: 'completed', percent: 100, stage: '完成', created_at: '2026-06-11' },
  { task_id: 't-2', status: 'running',   percent: 62,  stage: '渲染第 3 镜头', created_at: '2026-06-13' },
  { task_id: 't-3', status: 'failed',    percent: 34,  stage: '配音失败', created_at: '2026-06-13' },
];

export function mockEstimate(durationArchetype: string, quality: string): CostEstimateRes {
  const base = { '1-5min': 200, '5-15min': 600, '15-45min': 1500, '45min+': 3000 }[durationArchetype] ?? 400;
  const mult = { standard: 1, high: 1.5, ultra: 2.5 }[quality] ?? 1;
  const credits = Math.round(base * mult);
  return {
    credits,
    usd: Math.round(credits * 0.06),
    breakdown: [
      { label: `视频生成 (${durationArchetype} · ${quality})`, credits: Math.round(credits * 0.8) },
      { label: 'TTS 配音 + BGM', credits: Math.round(credits * 0.2) },
    ],
  };
}

// ── 画廊 mock(官方示例,冷启动)──────────────────
import type { GalleryItem } from '@/types/api';
export const MOCK_GALLERY: GalleryItem[] = [
  { item_id: 'g1', category: 'long_video', title: '宇宙的尺度', description: '从地球到可观测宇宙的震撼之旅', prompt: '制作一部介绍宇宙尺度的科普长片,从地球出发逐级放大到可观测宇宙边缘,画面震撼,旁白沉稳',
    gen_params: { category: 'long_video', duration_archetype: '15-45min', style_preset: '科普', quality_profile: 'high', aspect_ratio: '16:9' }, sort_order: 1 },
  { item_id: 'g2', category: 'short_video', title: '咖啡的一天', description: '竖屏短片 · 治愈系', prompt: '一杯咖啡从烘焙到冲煮的治愈系短视频,暖色调,慢镜头',
    gen_params: { category: 'short_video', duration_archetype: '1-5min', style_preset: '严肃', quality_profile: 'high', aspect_ratio: '9:16' }, sort_order: 2 },
  { item_id: 'g3', category: 'avatar_narration', title: 'AI 主播播报', description: '数字人口播 · 新闻风', prompt: '数字人主播播报今日科技新闻,专业播音腔',
    gen_params: { category: 'avatar_narration', style_preset: '严肃', quality_profile: 'high' }, sort_order: 3 },
  { item_id: 'g4', category: 'animation', title: '像素小镇', description: 'LTX-2 真动作动画', prompt: '一个像素风格的小镇,居民们日常活动,复古游戏画风',
    gen_params: { category: 'animation', duration_archetype: '1-5min', style_preset: '搞笑', quality_profile: 'standard' }, sort_order: 4 },
  { item_id: 'g5', category: 'image', title: '角色三视图', description: '创意辅助 · 概念设计', prompt: '一个赛博朋克风格的女性角色,生成正侧背三视图',
    gen_params: { category: 'image', style_preset: '科普' }, sort_order: 5 },
  { item_id: 'g6', category: 'long_video', title: '黑洞的秘密', description: '科普长片', prompt: '介绍黑洞的形成、特性和最新观测,画面震撼有旁白',
    gen_params: { category: 'long_video', duration_archetype: '15-45min', style_preset: '科普', quality_profile: 'ultra', aspect_ratio: '16:9' }, sort_order: 6 },
];

// ── 逐步 provider:三预设(§4)+ provider 选项(§3)──────
import type { GenPreset, ProviderOption, CostEstimateV2, StepProviders } from '@/types/api';

export const PRESETS: GenPreset[] = [
  { id: 'economy', label: '省钱', icon: '💰', tagline: '全本地',
    step_providers: { llm: 'qwen_local', video: 'wan_local', audio: 'vibevoice_local' },
    est_cost_usd: 0, est_credits: 0, est_time_min: 16, quality: '480P' },
  { id: 'balanced', label: '均衡', icon: '⚖️', tagline: '推荐(默认)',
    step_providers: { llm: 'dashscope', video: 'wan_local', audio: 'vibevoice_local' },
    est_cost_usd: 0.01, est_credits: 1, est_time_min: 16, quality: '480P' },
  { id: 'turbo', label: '极速', icon: '⚡', tagline: '全云',
    step_providers: { llm: 'dashscope', video: 'ltx2_cloud', audio: 'cloud' },
    est_cost_usd: 7.7, est_credits: 770, est_time_min: 2, quality: '720P' },
];

// 各步 provider 选项(§3,后端 GET /api/providers 就绪前硬编码)
export const PROVIDER_OPTIONS: Record<string, ProviderOption[]> = {
  llm: [
    { id: 'qwen_local', label: '本地 Qwen', choice: 'local', hint: '慢,免费' },
    { id: 'dashscope',  label: '云 Qwen',   choice: 'cloud', hint: '快' },
  ],
  video: [
    { id: 'wan_local',  label: '本地 Wan',  choice: 'local', hint: '480P,慢,免费' },
    { id: 'ltx2_cloud', label: '云 LTX-2',  choice: 'cloud', hint: '720P,快,$7.2' },
  ],
  audio: [
    { id: 'vibevoice_local', label: '本地 VibeVoice', choice: 'local', hint: '免费' },
    { id: 'cloud',           label: '云',             choice: 'cloud', hint: '快' },
  ],
  avatar: [
    { id: 'duix_local', label: '本地 Duix', choice: 'local', hint: '免费' },
    { id: 'cloud',      label: '云',        choice: 'cloud', hint: '快' },
  ],
};

// mock 逐步成本估算(后端 cost_model 就绪前)
export function mockEstimateV2(sp: StepProviders, hasVideo: boolean, hasAudio: boolean): CostEstimateV2 {
  const cost = (id: string) => {
    if (id === 'ltx2_cloud') return 7.2;
    if (id === 'dashscope') return 0.01;
    if (id === 'cloud') return 0.3;
    return 0; // 本地免费
  };
  const per_step = [{ step: '脚本', cost_usd: cost(sp.llm) }];
  if (hasVideo) per_step.push({ step: '视频', cost_usd: cost(sp.video) });
  if (hasAudio) per_step.push({ step: '配音', cost_usd: cost(sp.audio) });
  const total = per_step.reduce((s, x) => s + x.cost_usd, 0);
  // 本地视频慢
  const isLocalVideo = sp.video.includes('local');
  return {
    per_step, total_usd: Number(total.toFixed(2)),
    total_credits: Math.round(total * 100),
    est_time_min: isLocalVideo ? 16 : 2,
  };
}
