/**
 * hevi 后端 API 契约类型
 * 来源:hevi 二代前端需求文档(2026-06-13)
 * schema 以后端 OpenAPI 实际响应为准,这里是结构框架。
 */

// ── 画布节点系统 ──────────────────────────────────
export type NodeType = 'text' | 'image' | 'video' | 'audio' | 'script';

export interface CanvasNode {
  node_id: string;
  node_type: NodeType;
  inputs: Record<string, unknown>;   // 因 type 而异
  upstream_ids: string[];
  // 前端补充(画布位置 + 执行状态)
  position?: { x: number; y: number };
  status?: TaskStatus;
  result?: NodeResult;
}

export interface NodeResult {
  kind: 'text' | 'image' | 'video' | 'audio' | 'data';
  url?: string;          // 图/视频/音频预览
  text?: string;
  data?: unknown;        // 结构化(三视图/多机位 prompt 等)
}

export interface CanvasEdge {
  from_id: string;
  to_id: string;
}

export interface CanvasGraph {
  id: string;
  name: string;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  user_id?: string | null;
  created_at?: string;
  updated_at?: string;
}

// 连线兼容矩阵(后端 canvas_edge_validate 5×5)
export type EdgeValidation = { valid: boolean; reason?: string };

// ── 任务/进度 ─────────────────────────────────────
export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'paused';

export type DurationArchetype = 'short' | '1-5min' | '5-15min' | '15-45min' | '45min+';
export type VideoProvider = 'wan_local' | 'veo3' | 'kling_v2' | 'hailuo' | 'ltx2_cloud' | 'wan_cloud';
export type QualityProfile = 'standard' | 'high' | 'ultra';

export interface LongVideoTaskReq {
  topic: string;
  duration_archetype: DurationArchetype;
  video_provider: VideoProvider;
  audio_provider?: string;
  style_preset?: string;
  aspect_ratio?: AspectRatio;
  num_characters?: number;
  quality_profile: QualityProfile;
  step_providers?: StepProviders;
  subject_id?: string;   // 选中角色后带上,后端用其参考图锁定每个镜头的人物身份
}

export type AspectRatio = '9:16' | '16:9' | '1:1';
export const STYLE_PRESETS = ['科普', '严肃', '搞笑'] as const;
export type StylePreset = typeof STYLE_PRESETS[number];

export interface TaskInfo {
  task_id: string;
  status: TaskStatus;
  percent: number;
  stage?: string;
  created_at?: string;
}

// 质量档(文档 1.9)
export interface QualitySpec {
  profile: QualityProfile;
  resolution: string;
  fps: number;
  bitrate: string;
  cost_multiplier: number;
}

export const QUALITY_SPECS: QualitySpec[] = [
  { profile: 'standard', resolution: '720×1280',  fps: 24, bitrate: '2500k',  cost_multiplier: 1.0 },
  { profile: 'high',     resolution: '1080×1920', fps: 30, bitrate: '5000k',  cost_multiplier: 1.5 },
  { profile: 'ultra',    resolution: '2160×3840', fps: 30, bitrate: '12000k', cost_multiplier: 2.5 },
];

// ── 创意辅助(9 项)─────────────────────────────────
export type CreativeCapabilityId =
  | 'three-view' | 'storyboard' | 'story-predict' | 'multi-angle'
  | 'transition' | 'element-edit'
  | 'workflow/character-consistency' | 'workflow/storyboard' | 'workflow/comic-to-animation';

export interface CreativeCapability {
  id: CreativeCapabilityId;
  label: string;
  description?: string;
  // 输入 schema(供面板动态渲染表单)
  input_schema?: Record<string, unknown>;
  returns: 'data' | 'prompt' | 'media';   // L-029:多数返回 data/prompt
}

// ── 主体库 ────────────────────────────────────────
export type SubjectKind = 'character' | 'portrait' | 'product' | 'scene';

export interface Subject {
  subject_id: string;
  kind: SubjectKind;
  name: string;
  reference_images: string[];
  metadata: Record<string, unknown>;
}

// ── 成本预估 ──────────────────────────────────────
export interface CostEstimateRes {
  credits: number;
  usd?: number;
  breakdown?: { label: string; credits: number }[];
}

// ── 认证(SaaS-1)──────────────────────────────────
export interface AuthUser {
  id: string;
  email: string;
  display_name?: string;
}
export interface AuthRes {
  user: AuthUser;
  token: string;
}
export interface CreditsBalance {
  balance: number;
}

// ── 首页画廊(§5)──────────────────────────────────
export type GalleryCategory = 'long_video' | 'short_video' | 'avatar_narration' | 'animation' | 'image';

export interface GenParams {
  category: GalleryCategory;
  duration_archetype?: DurationArchetype;
  style_preset?: string;
  quality_profile?: QualityProfile;
  aspect_ratio?: AspectRatio;
  [key: string]: unknown;
}

export interface GalleryItem {
  item_id: string;
  category: GalleryCategory;
  title: string;
  description?: string;
  media_url?: string;
  thumbnail_url?: string;
  prompt: string;
  gen_params: GenParams;
  sort_order?: number;
}

// ── L4 导演层(§3)──────────────────────────────────
export interface ProducerPlan {
  topic: string;
  duration_archetype: string;
  video_provider: string;
  audio_provider: string;
  style: string;
  num_characters: number;
  estimated_usd: number;
  budget_usd: number | null;
  budget_ok: boolean;
  feasible: boolean;
  notes: string[];
}

export interface DirectorPlanResult {
  intent: Record<string, unknown>;
  plan: ProducerPlan;
  shot_prompts: string[];
  graph: { name: string; nodes: unknown[]; edges: unknown[] };
}

export interface DirectorEpisodeResult {
  task_id: string;
  status: string;
  intent: Record<string, unknown>;
  plan: ProducerPlan;
  spec?: {
    duration_archetype?: string;
    aspect_ratio?: string;
    quality_profile?: string;
    video_provider?: string;
    audio_provider?: string;
    num_characters?: number;
    subject_locked?: boolean;
    avatar?: boolean;
  };
}

// 导演台片表单 → 建集(8 层结构化字段)
export interface DirectorEpisodePayload {
  text: string;
  duration_archetype?: string;
  aspect_ratio?: string;
  subject_id?: string | null;
  avatar_portrait?: string | null;
  num_characters?: number;
  style_preset?: string | null;
  prompt_style?: string | null;
  prompt_lighting?: string | null;
  prompt_camera?: string | null;
  prompt_color_grade?: string | null;
  transition?: string;
  per_shot_routing?: boolean;
  language?: string;
  audio_provider?: string | null;
  bgm?: string | null;
  quality_profile?: string;
  preset?: string | null;
  video_provider?: string | null;
  budget_usd?: number;
  auto_rework_rounds?: number;
}

// 逐镜编辑回路:提交编辑过的分镜图 → 执行装配成片
export interface DirectorRenderPayload {
  name?: string;
  topic?: string;
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  quality_profile?: string;
  aspect_ratio?: string;
  transition?: string;
  bgm?: string | null;
}

export interface DirectorRenderResult {
  task_id: string;
  graph_id: string;
  status: string;
  shot_count: number;
}

// ── L2 系列 / 风格包(§3 L2)──────────────────────────
export interface Series {
  id: string;
  name: string;
  style_preset?: string;
  style_pack_id?: string | null;
  style_pack_version?: number;
  subject_ids?: string[];
  episode_count?: number;
  created_at?: string;
}

export interface SeriesCreatePayload {
  name: string;
  subject_ids?: string[];
  style_preset?: string;
  style_pack_id?: string | null;
  spec?: Record<string, unknown>;
  intro_template_id?: string | null;
  outro_template_id?: string | null;
}

export interface Episode {
  id: string;
  topic?: string;
  status?: string;
  episode_index?: number;
  result_video_path?: string | null;
  task_id?: string;
}

export interface StylePack {
  id: string;
  name: string;
  base_preset?: string;
  version?: number;
  overrides_json?: Record<string, string>;
}

export interface StylePackCreatePayload {
  name: string;
  base_preset?: string;
  overrides?: Record<string, string>;
}

// 投稿:成片上墙(需登录)
export interface GalleryCreatePayload {
  category: GalleryCategory;
  title: string;
  media_url?: string;
  description?: string;
  thumbnail_url?: string;
  prompt?: string;
  gen_params?: Record<string, unknown>;
  sort_order?: number;
}

// ── 逐步 provider 选项(§3)──────────────────────────
export type ProviderChoice = 'local' | 'cloud';

export interface StepProviders {
  llm: string;     // qwen_local | dashscope
  video: string;   // wan_local | ltx2_cloud
  audio: string;   // vibevoice_local | cloud
  avatar?: string; // duix_local | cloud(仅头像解说)
}

export type PresetId = 'economy' | 'balanced' | 'turbo';

export interface GenPreset {
  id: PresetId;
  label: string;
  icon: string;
  tagline: string;        // 全本地 / 推荐 / 全云
  step_providers: StepProviders;
  est_cost_usd: number;
  est_credits: number;
  est_time_min: number;
  quality: string;        // 480P / 720P
}

export interface ProviderOption {
  id: string;
  label: string;
  choice: ProviderChoice;
  hint: string;           // 慢,免费 / 快,$7.2 等
}

export interface StepEstimate {
  step: string;
  cost_usd: number;
}

export interface CostEstimateV2 {
  per_step: StepEstimate[];
  total_usd: number;
  total_credits: number;
  est_time_min: number;
}
