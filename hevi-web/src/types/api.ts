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
  // 后端 oprim.CanvasNode 的真实字段名是 config,不是 inputs(HEVI 路线图 Phase1 #31
  // 修复:此前 onSave 一直发 inputs,执行时 CanvasNode.model_validate 静默丢弃,
  // 导致任何节点配置——包括视频节点的 prompt/reference_image——从未真正到达后端)。
  config?: Record<string, unknown>;
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
  // 后端 oprim.CanvasEdge 的真实字段名(同上,此前 from_id/to_id 送到执行阶段的
  // CanvasEdge.model_validate 会直接因缺必填字段报错)。
  edge_id: string;
  from_node_id: string;
  to_node_id: string;
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
  error?: string | null;
  result_video_path?: string | null;
}

// ── 统一生产契约 / 数字人 Presenter ───────────────────────────────
export type ProductionSource = 'studio' | 'automatic' | 'tongjian' | 'shortdrama' | 'explainer';
export type PresenterPerformance = 'presenter' | 'narrator' | 'character_dialogue';
export type PresenterMotion = 'still' | 'talking_head' | 'half_body' | 'full_body' | 'picture_in_picture' | 'voice_over';
export type PresenterLipsync = 'native_audio' | 'dedicated_lipsync' | 'avatar_provider' | 'none';

export interface Presenter {
  id: string;
  name: string;
  subject_id?: string | null;
  voice_profile_id?: string | null;
  performance: PresenterPerformance | string;
  motion: PresenterMotion | string;
  lipsync: PresenterLipsync | string;
  delivery?: Record<string, unknown>;
  description?: string;
}

export interface PresenterInput {
  name: string;
  subject_id?: string | null;
  voice_profile_id?: string | null;
  performance: PresenterPerformance;
  motion: PresenterMotion;
  lipsync: PresenterLipsync;
  delivery?: Record<string, unknown>;
  description?: string;
}

export interface PresenterReadiness {
  presenter_id: string;
  ready: boolean;
  issues: string[];
  strategy: Record<string, unknown>;
}

export interface ProductionRequest {
  source: ProductionSource;
  topic: string;
  duration_archetype?: DurationArchetype;
  video_provider?: string;
  audio_provider?: string;
  quality_profile?: QualityProfile;
  aspect_ratio?: AspectRatio;
  budget_usd?: number | null;
  num_characters?: number;
  subject_ids?: string[];
  presenter_id?: string | null;
  style_pack_id?: string | null;
  options?: Record<string, unknown>;
}

export interface ProductionTask extends TaskInfo {
  production_source: ProductionSource;
}

/** 后端能力目录的公共投影；不可用时包含真实原因与配置动作。 */
export interface CapabilityDescriptor {
  id: string;
  name: string;
  routes: string[];
  available: boolean;
  status: 'available' | 'unavailable';
  message: string;
  setup?: string | null;
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
export type CastingTier = 'protagonist' | 'supporting' | 'extra';

// 角色卡的专业要素(§ 角色配置规格)—— 全走 Subject.metadata 自由字段,不用改表结构。
export interface CharacterMetadata {
  age?: string;             // 年龄段,自由文本(如"20多岁")
  gender?: string;          // 性别
  build?: string;           // 体型
  persona?: string;         // 人设/性格(注入分镜 LLM 的 roster 文本)
  speech_style?: string;    // 语言风格 / 口头禅
  casting_tier?: CastingTier; // 戏份分级:主角/配角/龙套
  relationships?: string;   // 人物关系(自由文本,如"与阿熊是竞争对手")
  negative_notes?: string;  // 角色专属负向提示(如"避免多指")
  voice_ref?: string;       // 声音参考音频路径(Phase 3,上传后端写入)
  wardrobe_images?: string[]; // 造型参考图路径(与身份参考图分开管理)
  [key: string]: unknown;
}

export interface Subject {
  subject_id: string;
  kind: SubjectKind;
  name: string;
  description?: string;
  reference_images: string[];
  tags?: string[];
  metadata: CharacterMetadata;
  version?: number;
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
    character_count?: number;
    avatar?: boolean;
  };
}

// 导演台片表单 → 建集(8 层结构化字段)
export interface DirectorEpisodePayload {
  text: string;
  duration_archetype?: string;
  aspect_ratio?: string;
  mood?: string | null;
  genre?: string | null;
  narrative_hook?: string | null;
  character_subject_ids?: string[];
  subject_id?: string | null;
  avatar_portrait?: string | null;
  num_characters?: number;
  scene_notes?: string | null;
  props?: string | null;
  style_preset?: string | null;
  prompt_style?: string | null;
  prompt_lighting?: string | null;
  prompt_camera?: string | null;
  prompt_color_grade?: string | null;
  style_reference_image?: string | null;
  shot_keyframes?: Record<string, { first_frame: string; last_frame: string }>;
  transition?: string;
  per_shot_routing?: boolean;
  language?: string;
  audio_provider?: string | null;
  bgm?: string | null;
  sfx?: string | null;
  voice_rate?: string | null;
  voice_pitch?: string | null;
  voice_name?: string | null;
  emotion_aware_voiceover?: boolean;
  quality_profile?: string;
  subtitle_style?: string;
  bilingual_language?: string | null;
  intro_clip?: string | null;
  outro_clip?: string | null;
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
  sfx?: string | null;
  intro_clip?: string | null;
  outro_clip?: string | null;
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

// 剧集看板幕级结构:dispatch 塞进 task.config_json.episode_plan(SPEC-001 §3.3 子集)
export interface EpisodePlanLite {
  ep_number?: number;
  title?: string;
  beats?: string[];
  event_ids?: string[];
  characters_present?: string[];
  locations?: string[];
  target_emotion_arc?: string;
}

export interface Episode {
  id: string;                 // = 底层 video_task id(分集 endpoint 直接返 video_tasks 行)
  topic?: string;
  status?: string;
  episode_index?: number;
  result_video_path?: string | null;
  task_id?: string;           // 通常为空,任务 id 用 id 字段
  config_json?: { episode_plan?: EpisodePlanLite } & Record<string, unknown>;
}

// 剧集看板镜级卡片(GET /api/tasks/{id}/shots 投影)
export interface TaskShot {
  shot_index: number;
  status: string;
  has_output: boolean;
  consistency_score?: number | null;
  passed?: boolean | null;
  diagnosis_category?: string | null;
  retry_count?: number | null;
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

// ── 通鉴流水线(HEVI-SPEC-01)──────────────────────────────────────────────────
export type TongjianLayerStatus = 'PENDING' | 'RUNNING' | 'PASSED' | 'DEGRADED' | 'FAILED';
export type TongjianRunStatusVal = 'PENDING' | 'RUNNING' | 'AWAITING_REVIEW' | 'COMPLETED' | 'FAILED';

// 一行剧本(对应后端 hevi.tongjian.schemas.ScriptLine)。人工审核台里逐行可编辑。
export interface TongjianScriptLine {
  line_id: string;
  act: number;
  type: string;            // narration / dialogue / commentary
  speaker: string;         // NARRATOR 或角色 character_id
  text: string;
  event_id: string | null;
  quote_id: string | null;
  dramatized: boolean;     // true=戏剧化改编对白(非逐字引语)
  emotion: string;
  visual_hint: string;
}

// 待审核的立意+剧本(GET /runs/{id}/script)。constitution 用宽松形状,只取展示/可编辑字段。
export interface TongjianScriptReview {
  constitution: Record<string, unknown> & { logline?: string; tone?: string[]; thesis?: string };
  script: { lines: TongjianScriptLine[] };
  status: TongjianRunStatusVal;
}

export interface TongjianLayerState {
  layer: string;                // L0..L8
  status: TongjianLayerStatus;
  retry_count: number;
  degraded: boolean;
  artifact_path: string | null;
  gate_report: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface TongjianRunStatus {
  run_id: string;
  status: TongjianRunStatusVal;
  source_name: string;
  created_at: string;
  completed_at: string | null;
  current_layer: string | null;
  layers: TongjianLayerState[];
  result_video_path: string | null;
  error: string | null;
}

// 单层的模型选择 + 可调参数(后端 hevi.tongjian.schemas.LayerConfig)。全自动生成有偏差时
// 逐层调参重跑。model=空走该层默认;params 由各层解释(如 L6 avatar: style/say_char_sec)。
export interface TongjianLayerConfig {
  model?: string | null;
  params?: Record<string, unknown>;
}

export interface TongjianRunRequest {
  source_name: string;
  raw_text: string;
  target_duration_sec?: number;
  aspect_ratio?: string;
  // ="L2" 时跑完剧本暂停等人工审核(AWAITING_REVIEW),审核后 resume 再渲染;省略=一口气跑完。
  pause_after?: string | null;
  // 每层配置,键 "L0".."L8"。例:{ L6: { model: "cloud_avatar", params: { style: "..." } } }
  layer_config?: Record<string, TongjianLayerConfig>;
}

// ── 自媒体解说短视频通道(hevi.explainer)────────────────────────────────────
export type ExplainerLayerStatus = 'PENDING' | 'RUNNING' | 'PASSED' | 'FAILED';
export type ExplainerRunStatusVal = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';

export interface ExplainerLayerState {
  layer: string;                // E0/E1/E2
  status: ExplainerLayerStatus;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  gate_report: Record<string, unknown> | null;
}

export interface ExplainerRunStatus {
  run_id: string;
  status: ExplainerRunStatusVal;
  topic: string;
  created_at: string;
  completed_at: string | null;
  current_layer: string | null;
  layers: ExplainerLayerState[];
  result_portrait_path: string | null;
  result_landscape_path: string | null;
  error: string | null;
}

export interface ExplainerRunRequest {
  topic: string;
}

// ── Explainer Master v6: research → human cue review → assembly ───────────
export type ExplainerVisualType =
  | 'heygen_avatar'
  | 'broll_news'
  | 'browser_broll'
  | 'broll_stock'
  | 'data_screenshot'
  | 'remotion_chart'
  | 'remotion_code'
  | 'manim_scene'
  | 'voiceover';

export interface ExplainerResearchRequest {
  topic_or_url: string;
  voice_profile?: string;
  heygen_presenter_id?: string | null;
  /** 断点续传:携带已有 session_id 覆盖旧缓存;空值由服务端生成并返回。 */
  session_id?: string;
  /** 精准目标时长:"1-3"/"3-6"/"6-10"/"10-15" 等范围档,或单个分钟数如 "8"。 */
  target_duration?: string;
}

export interface ExplainerFact {
  claim: string;
  source: string | null;
  confidence: number;
}

// 🚨 素材吸收与扩写映射表条目(反压缩机制):原文素材点 + 至少 150 字的深度扩写。
export interface ConceptExpansion {
  original_material_point: string;
  deep_explanation: string;
  source?: string;
}

// v9: 递进式 Hook 矩阵节点。LLM 从主题知识图谱产出,不再携带“推荐/不推荐”标签。
export type HookNarrativeFunction =
  | 'opening_suspense'
  | 'mid_conflict'
  | 'climax_breakthrough';

export interface ExplainerHookNode {
  hook_id: string;
  title: string;
  narrative_function: HookNarrativeFunction;
  suggested_placement_s: number;
  text: string;
  associated_concepts: string[];
}

export interface ExplainerCue {
  time_range: string;
  visual_type: ExplainerVisualType;
  text: string;
  visual_config?: Record<string, unknown>;
  step_id?: number | string;
  time_estimate_s?: number;
  target_url?: string | null;
  highlight_selector?: string | null;
  chart_data?: Record<string, unknown> | null;
  code_text?: string | null;
  language?: string | null;
}

export interface ExplainerScriptDraft {
  id: string;
  version_id?: string | null;
  title: string;
  viewpoint: string;
  hook: string;
  /** 思考链:LLM 在写台词前先说明本版如何把核心理论讲透。 */
  reasoning_depth?: string;
  /** 🚨 素材吸收与扩写矩阵:100% 覆盖全部素材点的深度扩写(写台词前强制输出)。 */
  material_coverage_matrix?: ConceptExpansion[];
  cues: ExplainerCue[];
}

export interface ExplainerResearchResponse {
  topic_or_url: string;
  research_summary: string;
  facts: ExplainerFact[];
  hooks: ExplainerHookNode[];
  hook_details?: ExplainerHookNode[];
  scripts: ExplainerScriptDraft[];
  script_versions: ExplainerScriptDraft[];
  provider: string;
  decision_trail: Array<Record<string, unknown>>;
  /** 🚨 素材吸收与扩写映射表(跨脚本版本并集):确稿台可先查看全部素材点如何被扩写。 */
  material_coverage_matrix?: ConceptExpansion[];
  /** 断点续传:本次调研的缓存 key,刷新后凭它恢复确稿台。 */
  session_id: string;
}

export type ExplainerResearchStatus = 'pending' | 'processing' | 'ready' | 'failed';

/** 异步研究任务的状态信封:POST /research 立即返 202,前端轮询 GET 拿到它。
 *  status=processing 继续等、ready 后 payload 即完整确稿数据、failed 显示 error。 */
export interface ExplainerResearchJob {
  session_id: string;
  status: ExplainerResearchStatus;
  topic_or_url?: string;
  error?: string | null;
  payload?: ExplainerResearchResponse | null;
}

export interface ExplainerAssembleRequest {
  topic_or_url: string;
  voice_profile?: string;
  presenter_id?: string | null;
  heygen_presenter_id?: string | null;
  selected_hook: string;
  selected_hooks: string[];
  hook_combination: 'chain' | 'fusion';
  final_script_cues: ExplainerCue[];
  enable_remotion_code_render: boolean;
  enable_manim_render?: boolean;
  enable_circle_avatar_mask: boolean;
  enable_browser_broll: boolean;
  aspect_ratio: '9:16' | '16:9';
  /** 断点续传:关联到 research 阶段的缓存会话(仅记录)。 */
  session_id?: string;
  /** 数字人母体照片(经素材质检的本地路径/URL)。 */
  presenter_image_url?: string;
  presenter_reference_video?: string;
  /** 60–90 秒试播。全片须 preview_confirmed。 */
  preview_mode?: boolean;
  preview_confirmed?: boolean;
}

export interface ExplainerAssemblyAccepted {
  task_id: string;
  status: string;
  estimated_seconds: number;
  sse_channel: string;
  production_source: string;
  engine_version: string;
  adapter_version: string;
}

// ── v9.1 素材质检 / 任务大盘 ───────────────────────────────────────────────

export interface PresenterImageCheckResponse {
  valid: boolean;
  reason: string;
  width?: number | null;
  height?: number | null;
  face_count?: number | null;
  face_ratio?: number | null;
  face_check?: string;
}

/** SQLite TaskRun 行(SQLModel,见 hevi/core/models.py)。 */
export interface DashboardTask {
  id: number;
  task_id: string;
  pipeline_type: string;
  status: string;
  progress: number;
  error_log?: string | null;
  /** 颗粒度状态机快照:如 {tts_status: "done", html_status: "done"}。 */
  state_json?: Record<string, unknown> | null;
  /** 完成任务的成片沙盒路径(非 null 时输出端点可下载)。 */
  result_video_path?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DashboardTaskList {
  total: number;
  limit: number;
  offset: number;
  /** 各状态计数(进行中/完成/失败…), 供统计卡片。 */
  status_counts?: Record<string, number>;
  items: DashboardTask[];
}

// ── v9.1 Lite 管道发射台 ─────────────────────────────────────────

/** Lite 镜头: 一句旁白对应一张 HTML 卡片。 */
export interface LiteCueInput {
  index: number;
  narration: string;
}

export interface LiteAssemblePayload {
  topic: string;
  cues: LiteCueInput[];
  width?: number;
  height?: number;
  fps?: number;
}

/** POST /api/lite/assemble → 202 受理响应。 */
export interface LiteAssembleAccepted {
  task_id: string;
  status: 'pending' | 'completed' | 'failed';
  progress: number;
  video_path?: string | null;
  error?: string | null;
  decision_trail?: Array<Record<string, unknown>>;
}

/** Lite 完整闭环 run 状态(选题→veya-loop→确认→本地出片)。 */
export type LiteRunStatus =
  | 'drafting'
  | 'reviewing'
  | 'awaiting_confirm'
  | 'rendering'
  | 'completed'
  | 'failed';

export interface LiteScriptIssue {
  code: string;
  message: string;
  severity: 'hard' | 'soft';
  cue_index?: number | null;
  fix_hint?: string;
}

export interface LiteScriptVerdict {
  passed: boolean;
  score: number;
  issues: LiteScriptIssue[];
  summary: string;
  round: number;
  source: 'deterministic' | 'llm' | 'hybrid';
}

export interface LiteScriptDraft {
  topic: string;
  title: string;
  hook: string;
  cues: LiteCueInput[];
  target_cues?: number;
  language?: string;
}

export interface LiteVeyaLoopResult {
  draft: LiteScriptDraft;
  passed: boolean;
  rounds: number;
  verdicts: LiteScriptVerdict[];
  decision_trail: Array<Record<string, unknown>>;
}

export interface LiteRunRecord {
  run_id: string;
  status: LiteRunStatus;
  topic: string;
  draft?: LiteScriptDraft | null;
  loop?: LiteVeyaLoopResult | null;
  task_id?: string | null;
  video_path?: string | null;
  /** 审稿 HTML 预览路径(服务端);前端用 GET /api/lite/runs/{id}/preview.html */
  preview_html_path?: string | null;
  error?: string | null;
  progress: number;
  decision_trail?: Array<Record<string, unknown>>;
  width?: number;
  height?: number;
  fps?: number;
}

export interface LiteRunCreatePayload {
  topic: string;
  target_cues?: number;
  max_rounds?: number;
  width?: number;
  height?: number;
  fps?: number;
  script?: string;
  cues?: LiteCueInput[];
}

// ── 短剧创建入口(SPEC-001 §7 阶段1,建季能力)──────────────────────────────
export type ShortdramaRunStatusVal =
  | 'PENDING' | 'RUNNING' | 'AWAITING_CHARACTERS' | 'DISPATCHING' | 'DISPATCHED' | 'FAILED';

export interface ShortdramaCharacterLite {
  char_id: string;
  name: string;
  aliases: string[];
  description: string;
  role: string;
}

export interface ShortdramaRelationshipLite {
  from_char: string;
  to_char: string;
  relation_type: string;
  valence: number;
}

export interface ShortdramaEventLite {
  event_id: string;
  summary: string;
  beat_type: string;
}

export interface StoryGraphLite {
  characters: ShortdramaCharacterLite[];
  relationships: ShortdramaRelationshipLite[];
  events: ShortdramaEventLite[];
}

export interface ShortdramaEpisodeLite {
  ep_number: number;
  title: string;
  characters_present: string[];
  target_emotion_arc: string;
  beats: string[];
}

export interface SeasonPlanLite {
  target_episodes: number;
  episodes: ShortdramaEpisodeLite[];
}

// 每个角色当前的绑定状态(GET /runs/{id} 里的 characters 数组投影)
export interface ShortdramaCharacterBindingState {
  char_id: string;
  name: string;
  bound: boolean;
  subject_id: string | null;
}

export interface ShortdramaGateResult {
  passed: boolean;
  errors: string[];
  warnings: string[];
}

export interface ShortdramaRunStatus {
  run_id: string;
  status: ShortdramaRunStatusVal;
  source_name: string;
  target_episodes: number;
  created_at: string;
  series_id: string | null;
  error: string | null;
  // 派发中的当前步骤(如"建角色参考图 2/3: 道士"),派发完/未开始派发时为 null
  progress: string | null;
  story_graph?: StoryGraphLite;
  characters?: ShortdramaCharacterBindingState[];
  season_plan?: SeasonPlanLite;
  gate?: ShortdramaGateResult;
}

export interface ShortdramaRunRequest {
  source_name: string;
  raw_text: string;
  target_episodes?: number;
}

// 提交绑定时用的选择(mode="auto" 默认自动生成参考图 | "existing" 复用已有角色/刚上传的)
export interface ShortdramaCharacterBinding {
  mode: 'auto' | 'existing';
  subject_id?: string | null;
}

export interface ShortdramaConfirmRequest {
  bindings: Record<string, ShortdramaCharacterBinding>;
  video_provider?: string;
  duration_archetype?: string;
  series_budget_usd?: number;
  style_pack_id?: string | null;
}

// ── SPEC-003 主线导演流水线(director-pipeline)—— 立意→剧本→设计清单→分镜 ──────
// 类型跟 hevi/director/pipeline_schemas.py 的 Pydantic 模型逐字段对齐。

export interface DpConcept {
  theme: string;
  tone: string;
  style: string;
  target_audience: string;
  duration_archetype: string;
  quality_bar: string;
}

export interface DpScreenplayDialogueLine {
  character_name: string;
  text: string;
}

export interface DpScreenplayScene {
  scene_no: number;
  time: string;
  location: string;
  int_ext?: string;
  day_night?: string;
  characters_present: string[];
  narration: string;
  dialogue: DpScreenplayDialogueLine[];
  event_summary: string;
  visual_actions?: string[];
  production_complexity?: string;
  cg_level?: string;
}

export interface DpScreenplay {
  scenes: DpScreenplayScene[];
}

export interface DpDesignCharacter {
  name: string;
  appearance: string;
  wardrobe: string;
  hairstyle: string;
  personality: string;
  is_lead: boolean;
  voice_hint: string;
  subject_id: string | null;
  voice_id: string | null;
}

export interface DpDesignScene {
  name: string;
  environment: string;
  lighting: string;
  mood: string;
  is_primary: boolean;
  subject_id: string | null;
}

export interface DpDesignProp {
  name: string;
  appearance: string;
  subject_id: string | null;
}

export interface DpDesignList {
  characters: DpDesignCharacter[];
  scenes: DpDesignScene[];
  props: DpDesignProp[];
}

export interface DpShotDialogueLine {
  character_name: string; // 空 = 旁白
  text: string;
  target_name?: string; // INC-001 §H 对谁说 → eyeline
}

export interface DpShotBlocking {
  character_name: string;
  position: string;
  facing: string;
}

export interface DpShotListItem {
  shot_id: string;
  scene_no: number;
  shot_size: string;
  camera: string;
  visual_prompt: string;
  dialogue_lines: DpShotDialogueLine[];
  blocking: DpShotBlocking[];
  character_names: string[];
  scene_name: string;
  prop_names: string[];
  duration_s: number;
  action_beats?: string[]; // INC-001 §B 动作弧拍点
  // SPEC-004 ③.5 场事实引用(阶段 3,确定性链接填充)
  scene_stage_ref?: number | null;
  beat_range?: string[];
  camera_setup_ref?: string;
  attention_ref?: string;
}

// ── SPEC-004 ③.5 场面调度 SceneStage ─────────────────────────────────────────
export interface DpSceneZone { zone_id: string; name: string; rel_position: string }
export interface DpSceneLandmark { name: string; zone_id: string }
export interface DpSceneSpaceMap { zones: DpSceneZone[]; landmarks: DpSceneLandmark[] }
export interface DpSceneBeat {
  beat_id: string; order: number; trigger: string; dialogue_ref: string; duration_hint: number;
}
export interface DpInitialPosition {
  char_id: string; zone_id: string; facing: string; posture: string;
  facing_deg?: number | null; // SPEC-004 v2:朝向角(0前/90画右/180背/270画左)→ Subject3D 选视图
}
export interface DpBlockingMove {
  char_id: string; at_beat: string; from_zone: string; to_zone: string; action: string;
}
export interface DpSightline { at_beat: string; char_id: string; looking_at: string; assumed: boolean }
export interface DpSceneBlocking {
  initial_positions: DpInitialPosition[]; moves: DpBlockingMove[]; sightlines: DpSightline[];
}
export interface DpAxisShift { at_beat: string; new_axis: string[]; reason: string }
export interface DpSceneAxis { primary_axis: string[]; axis_shifts: DpAxisShift[]; side_convention: string }
export interface DpAttentionBeat {
  at_beat: string; focus_target: string; reason: string;
  transition: string; // cut/pan/push/rack_focus/follow
  intensity: string; // exclusive/primary/shared
}
export interface DpCameraSetup {
  setup_id: string; position: string; axis_side: string; shot_size: string;
  serves_beats: string[]; subjects: string[];
  azimuth_deg?: number | null; // SPEC-004 v2:机位方位角(0正面/90画右侧/180背后/270画左侧)
}
export interface DpCoveragePlan { master: DpCameraSetup | null; setups: DpCameraSetup[] }
export interface DpSceneStage {
  scene_ref: number;
  space_map: DpSceneSpaceMap;
  beats: DpSceneBeat[];
  blocking: DpSceneBlocking;
  axis: DpSceneAxis;
  attention_script: DpAttentionBeat[];
  coverage_plan: DpCoveragePlan;
  assumed: boolean;
}
export interface DpSceneStageSet { stages: DpSceneStage[] }
export interface DpLintFinding {
  rule: string; scene_no: number; shot_ids: string[]; message: string; severity: string;
}

export interface DpShotList {
  shots: DpShotListItem[];
}

export interface DpStoryCharacter {
  char_id: string;
  name: string;
  aliases: string[];
  description: string;
  role: string;
  subject_id?: string | null;
}

export interface DpStoryGraph {
  meta: { source: string; char_count: number; chapter_refs: string[] };
  characters: DpStoryCharacter[];
  events: Array<{
    event_id: string; summary: string; beat_type: string; dramatic_weight: number;
  }>;
  locations: Array<{ location_id: string; name: string; type: string }>;
  quotes: Array<{ quote_id: string; speaker: string; original: string; modern: string }>;
  relationships: Array<Record<string, unknown>>;
  arcs: Array<Record<string, unknown>>;
}

export interface DpSeasonEpisode {
  ep_number: number;
  title: string;
  event_ids: string[];
  beats: string[];
  characters_present: string[];
  locations: string[];
  target_emotion_arc: string;
}

export interface DpSeasonPlan {
  season_id: string;
  story_source: string;
  target_episodes: number;
  stylepack_ref: string | null;
  subject_refs: Array<{ char_id: string; subject_id: string | null; name: string }>;
  episodes: DpSeasonEpisode[];
  continuity_constraints: Array<{ char_id: string; present_in_episodes: number[] }>;
}

export interface DpGateCheck {
  key: string;
  label: string;
  passed: boolean;
  score: number;
  detail: string;
}

export interface DpGateReport {
  passed: boolean;
  score: number;
  estimated_cost_usd: number;
  identity_readiness: number;
  checks: DpGateCheck[];
  errors: string[];
  warnings: string[];
}

export interface DpDecisionTrailItem {
  at: string;
  stage: string;
  status: string;
  detail: string;
}

// ── INC-001 §A/§G/§I/§L 逐镜头准备台 ──────────────────────────────────────────
export interface DpAssetCandidate {
  id: string;
  candidate_type: string; // character / scene / prop / costume
  candidate_name: string;
  candidate_status: string; // pending / linked / ignored
  linked_entity_id: string | null;
}
export interface DpDialogueCandidate {
  id: string;
  line_index: number;
  text: string;
  speaker_name: string | null;
  target_name: string | null; // §H
  candidate_status: string; // pending / accepted / ignored
  linked_dialog_line_id: string | null;
}
export interface DpPrepState {
  shot_id: string;
  status: string; // pending / ready
  skip_extraction: boolean;
  extracted: boolean;
  assets_overview: DpAssetCandidate[];
  dialogue_candidates: DpDialogueCandidate[];
  saved_dialogue_lines: DpDialogueCandidate[];
  pending_confirm_count: number;
  ready_for_generation: boolean;
}
export interface DpPrepMutation {
  action: string;
  state: DpPrepState;
}
export interface DpPrepOverviewShot {
  shot_id: string;
  status: string;
  extracted: boolean;
  skip_extraction: boolean;
}
export interface DpPrepOverview {
  shots: DpPrepOverviewShot[];
  blockers: string[];
}

export type DpWorkStatus =
  | 'parsing' | 'inspection_ready' | 'parse_failed'
  | 'dispatching' | 'dispatched' | 'dispatch_failed' | 'dispatch_cancelled'
  | 'concept_draft' | 'concept_locked'
  | 'screenplay_generating' | 'screenplay_generate_failed' | 'screenplay_draft' | 'screenplay_locked'
  | 'design_list_draft' | 'design_list_locking' | 'design_list_lock_failed' | 'design_list_locked'
  | 'scene_stage_draft' | 'scene_stage_generating' | 'scene_stage_regenerate_failed'
  | 'scene_stage_locking' | 'scene_stage_lock_failed'
  | 'shot_list_draft' | 'shot_list_generating' | 'shot_list_regenerate_failed' | 'shot_list_locked'
  | 'producing';

export interface DpWork {
  work_id: string;
  status: DpWorkStatus;
  locked_through: number; // -1..4,已锁定到第几级(concept0/screenplay1/design_list2/scene_stage3/shot_list4)
  material_text: string;
  created_at: string;
  concept: DpConcept | null;
  screenplay: DpScreenplay | null;
  design_list: DpDesignList | null;
  scene_stage: DpSceneStageSet | null; // SPEC-004 ③.5 场面调度(每场一个 SceneStage)
  shot_list: DpShotList | null;
  scene_stage_lint: DpLintFinding[]; // SPEC-004 §4 链接后的确定性 lint findings
  video_task_id: string | null;
  work_name?: string;
  target_episodes?: number;
  episode_duration?: string;
  task_ids?: string[];
  series_id?: string | null;
  story_graph?: DpStoryGraph | null;
  season_plan?: DpSeasonPlan | null;
  gate_report?: DpGateReport | null;
  estimated_cost_usd?: number;
  decision_trail?: DpDecisionTrailItem[];
  production_config?: Record<string, unknown>;
  error: string | null;
}

export interface DpParseRequest {
  work_name: string;
  material_text: string;
  target_episodes: number;
  episode_duration: string;
  intent_hint: string;
  season_budget_usd: number;
  video_provider: string;
  audio_provider: string;
}

export interface DpDispatchSeasonRequest {
  season_budget_usd: number;
  video_provider: string;
  audio_provider: string;
  duration_archetype: string;
  quality_profile: string;
  aspect_ratio: string;
  concept?: DpConcept;
  screenplay?: DpScreenplay;
  design_list?: DpDesignList;
  season_plan?: DpSeasonPlan;
}

export interface DpProduceRequest {
  video_provider?: string;
  audio_provider?: string;
  quality_profile?: string;
  aspect_ratio?: string;
  budget_usd?: number | null;
  // SPEC v6.0 §2.2/§2.3 AutoCameo:角色锁脸/入戏参考
  character_references?: string[];
  autocameo?: boolean;
}

// ── 工作室扩展能力（制片工具 / ViMax / 语音工作室） ─────────────────────
export interface VoiceEffectPreset {
  name: string;
  effects: Array<{ type: string; params: Record<string, unknown>; enabled: boolean }>;
}
export interface VoicePersonalityPreset {
  name: string;
  description: string;
  speaking_style: string;
  vocabulary: string[];
  emotional_tendency: string;
}
export interface VoiceTTSEngine {
  id: string;
  name: string;
  type: 'cloud' | 'local';
  description: string;
  requires_gpu: boolean;
  languages?: string[];
  paralinguistic_tags?: string[];
  voice_categories?: Record<string, number>;
}

// Provider Presets 预置策略(SPEC v6.0 §2.4,后端 obase.ProviderRegistry 下沉)
export interface ProviderPreset {
  name: string;
  level: 'economy' | 'fast' | 'balanced' | 'premium';
  category: 'llm' | 'image' | 'video';
  provider: string;
  description: string;
  base_url: string | null;
  context_window: number;
  api_key_env: string | null;
  strategy: Record<string, unknown>;
}
