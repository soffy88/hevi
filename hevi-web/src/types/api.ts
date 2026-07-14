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
  characters_present: string[];
  narration: string;
  dialogue: DpScreenplayDialogueLine[];
  event_summary: string;
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
}

export interface DpShotList {
  shots: DpShotListItem[];
}

export type DpWorkStatus =
  | 'concept_draft' | 'concept_locked'
  | 'screenplay_draft' | 'screenplay_locked'
  | 'design_list_draft' | 'design_list_locking' | 'design_list_lock_failed' | 'design_list_locked'
  | 'shot_list_draft' | 'shot_list_generating' | 'shot_list_regenerate_failed' | 'shot_list_locked'
  | 'producing';

export interface DpWork {
  work_id: string;
  status: DpWorkStatus;
  locked_through: number; // -1..3,已锁定到第几级(见后端 _STAGES 顺序)
  material_text: string;
  created_at: string;
  concept: DpConcept | null;
  screenplay: DpScreenplay | null;
  design_list: DpDesignList | null;
  shot_list: DpShotList | null;
  video_task_id: string | null;
  error: string | null;
}

export interface DpProduceRequest {
  video_provider?: string;
  audio_provider?: string;
  quality_profile?: string;
  aspect_ratio?: string;
  budget_usd?: number | null;
}

