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

export type DurationArchetype = '1-5min' | '5-15min' | '15-45min' | '45min+';
export type VideoProvider = 'ltx2_cloud' | 'wan_cloud';
export type QualityProfile = 'standard' | 'high' | 'ultra';

export interface LongVideoTaskReq {
  topic: string;
  duration_archetype: DurationArchetype;
  video_provider: VideoProvider;
  audio_provider?: string;
  style_preset?: string;
  num_characters?: number;
  quality_profile: QualityProfile;
}

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
