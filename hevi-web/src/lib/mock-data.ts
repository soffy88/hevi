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
