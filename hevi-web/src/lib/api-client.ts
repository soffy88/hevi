/**
 * hevi API client — REST 封装
 * 所有请求预留 Authorization header(SaaS 认证就绪后注入 JWT)。
 */
import type {
  CanvasGraph, CanvasNode, CanvasEdge,
  LongVideoTaskReq, TaskInfo, TaskShot, CostEstimateRes,
  CreativeCapability, Subject, SubjectKind,
  AuthRes, AuthUser, CreditsBalance,
} from '@/types/api';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://localhost:8000';
const USE_MOCK = (process.env.NEXT_PUBLIC_USE_MOCK ?? 'true').toLowerCase() === 'true';

// token 注入点(由 auth-store 在登录 / 启动恢复时调用)
let authToken: string | null = null;
export function setAuthToken(t: string | null) { authToken = t; }

/** 401 回调:由应用层设置(跳登录页)。 */
let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

// 401 防抖:多个并发认证请求同时 401 时,只触发一次跳转(避免控制台/路由刷屏)
let unauthorizedFiring = false;
function fireUnauthorized() {
  if (unauthorizedFiring) return;
  unauthorizedFiring = true;
  onUnauthorized?.();
  // 跳转后短暂窗口内不重复触发
  setTimeout(() => { unauthorizedFiring = false; }, 2000);
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string>),
  };
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401) {
    fireUnauthorized();
    throw new Error('401 Unauthorized');
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

/**
 * authedReq — 需登录的请求。无 token 时直接拒绝,不发请求(避免未登录触发 401 刷屏)。
 * 用于 credits/tasks/canvas/subjects 等认证接口。
 */
export async function authedReq<T>(path: string, init?: RequestInit): Promise<T> {
  if (!authToken) {
    // 未登录:不发请求,抛可识别的错误(调用方静默处理)
    throw new Error('NOT_AUTHENTICATED');
  }
  return req<T>(path, init);
}

/**
 * authedFormReq — 需登录的 multipart/form-data 上传。
 * 不设 Content-Type(交给浏览器带 boundary),只带 Authorization。
 */
async function authedFormReq<T>(path: string, form: FormData): Promise<T> {
  if (!authToken) throw new Error('NOT_AUTHENTICATED');
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${authToken}` },
    body: form,
  });
  if (res.status === 401) { fireUnauthorized(); throw new Error('401 Unauthorized'); }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

/** 当前是否有 token(供组件判断是否调认证接口)。 */
export function hasToken(): boolean { return authToken != null; }

// ── 认证(SaaS-1)──────────────────────────────────
export const authApi = {
  register: (email: string, password: string, display_name?: string) =>
    req<AuthRes>('/api/auth/register', { method: 'POST', body: JSON.stringify({ email, password, display_name }) }),
  login: (email: string, password: string) =>
    req<AuthRes>('/api/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  me: () => req<{ user: AuthUser }>('/api/auth/me'),
};

// ── 积分(SaaS-2)──────────────────────────────────
export const creditsApi = {
  balance: () => authedReq<CreditsBalance>('/api/credits/balance'),
};

// ── 画布 CRUD ─────────────────────────────────────
export const canvasApi = {
  save:   (g: Partial<CanvasGraph>) => authedReq<CanvasGraph>('/api/canvas', { method: 'POST', body: JSON.stringify(g) }),
  list:   (userId?: string) => authedReq<CanvasGraph[]>(`/api/canvas${userId ? `?user=${userId}` : ''}`),
  load:   (id: string) => authedReq<CanvasGraph>(`/api/canvas/${id}`),
  update: (id: string, patch: Partial<CanvasGraph>) => authedReq<CanvasGraph>(`/api/canvas/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  remove: (id: string) => authedReq<void>(`/api/canvas/${id}`, { method: 'DELETE' }),
  execute:(id: string) => authedReq<{ task_id: string }>(`/api/canvas/${id}/execute`, { method: 'POST' }),
  // SSE 进度 URL(配合 useSSEProgress)
  progressUrl: (id: string) => `${API_BASE}/api/canvas/${id}/execute/progress`,
  // 通用 i2v 参考图上传(不经过角色库,直接给某个视频节点做参考图)
  uploadReferenceImage: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return authedFormReq<{ path: string }>('/api/canvas/reference-image', form);
  },
};

// ── 创意辅助 (需登录) ─────────────────────────────
export const creativeApi = {
  capabilities: () => authedReq<CreativeCapability[]>('/api/creative/capabilities'),
  call: (id: string, body: unknown) => authedReq<unknown>(`/api/creative/${id}`, { method: 'POST', body: JSON.stringify(body) }),
};

// ── 主体库 ────────────────────────────────────────
export const subjectApi = {
  create: (s: Partial<Subject>) => authedReq<Subject>('/api/subjects', { method: 'POST', body: JSON.stringify(s) }),
  list:   (kind?: SubjectKind, query?: string) => {
    const q = new URLSearchParams();
    if (kind) q.set('kind', kind);
    if (query) q.set('query', query);
    return authedReq<Subject[]>(`/api/subjects${q.toString() ? `?${q}` : ''}`);
  },
  get:    (id: string) => authedReq<Subject>(`/api/subjects/${id}`),
  update: (id: string, patch: Partial<Subject>) => authedReq<Subject>(`/api/subjects/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  remove: (id: string) => authedReq<void>(`/api/subjects/${id}`, { method: 'DELETE' }),
  // 上传一张照片直接建角色
  fromPhoto: (file: File, name = '我的角色', kind: SubjectKind = 'character', description?: string) => {
    const form = new FormData();
    form.append('file', file);
    form.append('name', name);
    form.append('kind', kind);
    if (description) form.append('description', description);
    return authedFormReq<Subject>('/api/subjects/from-photo', form);
  },
  // 给已有角色再加一张参考图
  uploadReference: (subjectId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return authedFormReq<Subject>(`/api/subjects/${subjectId}/reference`, form);
  },
  // 一次批量传多张参考图(替代逐张调 uploadReference)
  uploadReferences: (subjectId: string, files: File[]) => {
    const form = new FormData();
    files.forEach(f => form.append('files', f));
    return authedFormReq<Subject>(`/api/subjects/${subjectId}/references`, form);
  },
  // 整体替换参考图列表 —— 设封面(挪到第 0 位)/ 删除 / 排序,前端传目标顺序
  reorderReferences: (subjectId: string, referenceImages: string[]) =>
    authedReq<Subject>(`/api/subjects/${subjectId}/references`, {
      method: 'PUT',
      body: JSON.stringify({ reference_images: referenceImages }),
    }),
  // 上传声音参考片段(VibeVoice 零样本声音克隆用,存进 metadata.voice_ref)
  uploadVoice: (subjectId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return authedFormReq<Subject>(`/api/subjects/${subjectId}/voice`, form);
  },
  // 上传造型/服装参考图(与身份参考图分开管理,存进 metadata.wardrobe_images)
  uploadWardrobe: (subjectId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return authedFormReq<Subject>(`/api/subjects/${subjectId}/wardrobe`, form);
  },
  // 角色参考图预览:<img src> 不能带 header,token 走查询参数(同 progressUrl/videoUrl)
  // source='reference'(身份参考图,默认)| 'wardrobe'(造型参考图)
  imageUrl: (subjectId: string, idx = 0, source: 'reference' | 'wardrobe' = 'reference') =>
    `${API_BASE}/api/subjects/${subjectId}/image?token=${authToken ? encodeURIComponent(authToken) : ''}&idx=${idx}&source=${source}`,
};

// ── 长视频任务 ────────────────────────────────────
export const taskApi = {
  create:   (r: LongVideoTaskReq) => authedReq<TaskInfo>('/api/tasks', { method: 'POST', body: JSON.stringify(r) }),
  list:     () => authedReq<TaskInfo[]>('/api/tasks'),
  get:      (id: string) => authedReq<TaskInfo>(`/api/tasks/${id}`),
  // 镜头级卡片(剧集看板)——逐镜状态 + 一致性/诊断摘要
  shots:    (id: string) => authedReq<TaskShot[]>(`/api/tasks/${id}/shots`),
  // C3 verdict→定向返工(剧集看板可编辑,SPEC-001 §4.3):后台重生成指定镜头,fire-and-forget
  regenerateShots: (id: string, shotIds: number[], hints?: Record<number, string>) =>
    authedReq<TaskInfo>(`/api/tasks/${id}/regenerate`, {
      method: 'POST',
      body: JSON.stringify({ shot_ids: shotIds, hints: hints ?? null }),
    }),
  resume:   (id: string) => authedReq<TaskInfo>(`/api/tasks/${id}/resume`, { method: 'POST' }),
  // SSE 进度:EventSource 无法带 Authorization 头,token 以查询参数传递
  progressUrl: (id: string) =>
    `${API_BASE}/api/tasks/${id}/progress${authToken ? `?token=${encodeURIComponent(authToken)}` : ''}`,
  // 成片播放/下载:<video src> 同样不能带 header,token 走查询参数
  videoUrl: (id: string) =>
    `${API_BASE}/api/tasks/${id}/video${authToken ? `?token=${encodeURIComponent(authToken)}` : ''}`,
  // 封面:装配器自动产出,此前无端点暴露;<img src> 同样走 ?token=
  coverUrl: (id: string) =>
    `${API_BASE}/api/tasks/${id}/cover${authToken ? `?token=${encodeURIComponent(authToken)}` : ''}`,
  // 按格式导出(mp4/mov/webm/gif);mp4 直传,其余按需转码
  exportUrl: (id: string, format: string) =>
    `${API_BASE}/api/tasks/${id}/export?format=${format}${authToken ? `&token=${encodeURIComponent(authToken)}` : ''}`,
  // 翻译配音导出(§3 L2 护城河):ASR+翻译+目标语种 TTS+mux,首次现算较慢,产物缓存
  dubUrl: (id: string, language: string) =>
    `${API_BASE}/api/tasks/${id}/dub?language=${language}${authToken ? `&token=${encodeURIComponent(authToken)}` : ''}`,
  // 成本预估
  estimate: (r: LongVideoTaskReq) => req<CostEstimateRes>('/api/tasks/estimate', { method: 'POST', body: JSON.stringify(r) }),
};

export { USE_MOCK, API_BASE };

// ── 模板/音效(P11.F,需登录:返回官方+自有)──────────
export const assetApi = {
  templates: (category?: string) => authedReq<{ id: string; name: string; desc?: string }[]>(`/api/templates${category ? `?category=${category}` : ''}`),
  audio:     (type?: string) => authedReq<{ id: string; name: string; dur?: string }[]>(`/api/audio${type ? `?type=${type}` : ''}`),
};

// ── 画廊 / 展示墙(§4-5,读公开无需 token;投稿需登录)──────────────────────
import type { GalleryItem, GalleryCategory, GalleryCreatePayload } from '@/types/api';
export const galleryApi = {
  list: (category?: GalleryCategory) =>
    req<{ items: GalleryItem[] } | GalleryItem[]>(`/api/gallery${category ? `?category=${category}` : ''}`)
      .then(r => (Array.isArray(r) ? r : (r as { items: GalleryItem[] }).items ?? [])),
  get:  (itemId: string) => req<GalleryItem>(`/api/gallery/${itemId}`),
  create: (payload: GalleryCreatePayload) =>
    authedReq<GalleryItem>('/api/gallery', { method: 'POST', body: JSON.stringify(payload) }),
};

// ── 系列 / 风格包(§3 L2,需登录)──────────────────────
import type { Series, SeriesCreatePayload, Episode, StylePack, StylePackCreatePayload } from '@/types/api';
export const seriesApi = {
  list:   () => authedReq<Series[]>('/api/series'),
  get:    (id: string) => authedReq<Series>(`/api/series/${id}`),
  create: (payload: SeriesCreatePayload) =>
    authedReq<Series>('/api/series', { method: 'POST', body: JSON.stringify(payload) }),
  episodes: (id: string) => authedReq<Episode[]>(`/api/series/${id}/episodes`),
  createEpisode: (id: string, topic: string) =>
    authedReq<Episode>(`/api/series/${id}/episodes`, { method: 'POST', body: JSON.stringify({ topic }) }),
};
export const styleApi = {
  get:     (id: string) => authedReq<StylePack>(`/api/style-packs/${id}`),
  create:  (payload: StylePackCreatePayload) =>
    authedReq<StylePack>('/api/style-packs', { method: 'POST', body: JSON.stringify(payload) }),
  resolve: (id: string) =>
    authedReq<{ resolved: Record<string, string>; version: number }>(`/api/style-packs/${id}/resolve`),
  update:  (id: string, overrides: Record<string, string>) =>
    authedReq<StylePack>(`/api/style-packs/${id}`, { method: 'PATCH', body: JSON.stringify({ overrides }) }),
  // 参考图/视频 → VLM 拆解出 style/lighting/camera/color_grade 草稿(不落库,前端确认/编辑后再 create)
  draftFromReference: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return authedFormReq<{ style: string; lighting: string; camera: string; color_grade: string }>(
      '/api/style-packs/draft-from-reference', form,
    );
  },
};

// ── 导演层(§3 L4,需登录)片表单 → 预览 / 产集 / 逐镜编辑渲染 ──────────
import type {
  DirectorPlanResult, DirectorEpisodeResult, DirectorEpisodePayload,
  DirectorRenderPayload, DirectorRenderResult,
} from '@/types/api';
export const directorApi = {
  plan: (text: string, numShots = 4) =>
    authedReq<DirectorPlanResult>('/api/director/plan', {
      method: 'POST',
      body: JSON.stringify({ text, num_shots: numShots }),
    }),
  createEpisode: (payload: DirectorEpisodePayload) =>
    authedReq<DirectorEpisodeResult>('/api/director/episodes', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  render: (payload: DirectorRenderPayload) =>
    authedReq<DirectorRenderResult>('/api/director/render', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

// ── 通鉴全自动流水线(HEVI-SPEC-01,需登录)────────────────────────────────────
import type { TongjianRunRequest, TongjianRunStatus, TongjianScriptReview, TongjianScriptLine } from '@/types/api';
export const tongjianApi = {
  startRun: (payload: TongjianRunRequest) =>
    authedReq<{ run_id: string; status: string }>('/api/tongjian/run', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getStatus: (runId: string) =>
    authedReq<TongjianRunStatus>(`/api/tongjian/runs/${runId}`),
  listRuns: () =>
    authedReq<TongjianRunStatus[]>('/api/tongjian/runs'),
  // 人工审核:取回待审的立意+剧本
  getScript: (runId: string) =>
    authedReq<TongjianScriptReview>(`/api/tongjian/runs/${runId}/script`),
  // 提交编辑后的剧本(+可选立意);只保存不续跑
  updateScript: (runId: string, payload: { script: { lines: TongjianScriptLine[] }; constitution?: Record<string, unknown> }) =>
    authedReq<{ run_id: string; status: string; lines: string }>(`/api/tongjian/runs/${runId}/script`, {
      method: 'PUT', body: JSON.stringify(payload),
    }),
  // 审核通过 → 续跑 L3-L8 渲染
  resume: (runId: string) =>
    authedReq<{ run_id: string; status: string }>(`/api/tongjian/runs/${runId}/resume`, { method: 'POST' }),
  // 剧本不满意 → 重出一版(仍停在审核态)
  regenerate: (runId: string) =>
    authedReq<{ run_id: string; status: string }>(`/api/tongjian/runs/${runId}/regenerate`, { method: 'POST' }),
  // 成片播放/下载:<video src>/<a download> 不能带 header,token 走查询参数
  videoUrl: (runId: string) =>
    `${API_BASE}/api/tongjian/runs/${runId}/video${authToken ? `?token=${encodeURIComponent(authToken)}` : ''}`,
};

// ── 短剧创建入口(SPEC-001 §7 阶段1,需登录)──────────────────────────────────
import type { ShortdramaRunRequest, ShortdramaRunStatus, ShortdramaConfirmRequest } from '@/types/api';
export const shortdramaApi = {
  startRun: (payload: ShortdramaRunRequest) =>
    authedReq<{ run_id: string; status: string }>('/api/shortdrama/runs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getStatus: (runId: string) =>
    authedReq<ShortdramaRunStatus>(`/api/shortdrama/runs/${runId}`),
  listRuns: () =>
    authedReq<ShortdramaRunStatus[]>('/api/shortdrama/runs'),
  // 对抽取/分集结果不满意 → 重新抽取+规划
  replan: (runId: string) =>
    authedReq<{ run_id: string; status: string }>(`/api/shortdrama/runs/${runId}/replan`, { method: 'POST' }),
  // 重新触发故事开发(不重跑抽取和规划)
  develop: (runId: string) =>
    authedReq<{ run_id: string; status: string }>(`/api/shortdrama/runs/${runId}/develop`, { method: 'POST' }),
  // 给某个角色上传参考图建号并绑定(confirm 时该角色不再自动生成)
  uploadCharacterReference: (runId: string, charId: string, file: File) => {
    const form = new FormData();
    form.append('file', file);
    return authedFormReq<{ char_id: string; subject_id: string }>(
      `/api/shortdrama/runs/${runId}/characters/${charId}/upload`, form,
    );
  },
  // 角色绑定确认 → 派发(真实生成,由后台队列自动执行)
  confirm: (runId: string, payload: ShortdramaConfirmRequest) =>
    authedReq<{ run_id: string; status: string }>(`/api/shortdrama/runs/${runId}/confirm`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};

// ── SPEC-003 主线导演流水线(director-pipeline,需登录)───────────────────────
// 立意→剧本→设计清单→分镜,逐级人审核锁定才放行下游,详见
// docs/specs/SPEC-003-mainline-director-pipeline.md。
import type {
  DpConcept, DpScreenplay, DpDesignList, DpWorldBible, DpSceneScriptSet, DpWork, DpProduceRequest,
} from '@/types/api';
export const directorPipelineApi = {
  createWork: (materialText: string, intentHint = '') =>
    authedReq<DpWork>('/api/director-pipeline/works', {
      method: 'POST',
      body: JSON.stringify({ material_text: materialText, intent_hint: intentHint }),
    }),
  listWorks: () => authedReq<DpWork[]>('/api/director-pipeline/works'),
  getWork: (workId: string) => authedReq<DpWork>(`/api/director-pipeline/works/${workId}`),
  // 重新生成本级草稿;若本级此前已锁定(或更下游已锁定),后端会先回退+清空全部下游
  regenerateConcept: (workId: string) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/concept`, { method: 'POST' }),
  regenerateScreenplay: (workId: string) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/screenplay`, { method: 'POST' }),
  regenerateDesignList: (workId: string) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/design-list`, { method: 'POST' }),
  // V1→V2(2026-07-21):④World Bible 替换 V1 的③.5 场面调度,重新生成本级草稿(四卷)。
  // visualStyle(2026-07-22):影像美学预设(realistic 真人写实 / inkwash 国风水墨),
  // 传入即切换该 work 的画风偏好后重新生成;不传保持既有偏好。
  regenerateWorldBible: (workId: string, visualStyle?: 'realistic' | 'inkwash') =>
    authedReq<DpWork>(
      `/api/director-pipeline/works/${workId}/world-bible` +
        (visualStyle ? `?visual_style=${visualStyle}` : ''),
      { method: 'POST' },
    ),
  // ⑤Scene Script 替换 V1 的④分镜,重新生成本级草稿(逐场链式)
  regenerateSceneScript: (workId: string) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/scene-script`, { method: 'POST' }),
  // 锁定(可能已编辑的)内容 → 自动生成下一级草稿
  lockConcept: (workId: string, body: DpConcept) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/concept/lock`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  lockScreenplay: (workId: string, body: DpScreenplay) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/screenplay/lock`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  lockDesignList: (workId: string, body: DpDesignList) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/design-list/lock`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  // V1→V2(2026-07-21):锁定(可能已编辑的)World Bible → 后台生成⑤Scene Script 草稿(逐场链式)
  lockWorldBible: (workId: string, body: DpWorldBible) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/world-bible/lock`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  lockSceneScript: (workId: string, body: DpSceneScriptSet) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/scene-script/lock`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  // 仅 scene_script_locked 才允许,走 V2 document-first 管线出真实成片
  produce: (workId: string, body: DpProduceRequest) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/produce`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  // V1→V2(2026-07-21):逐镜头准备台(INC-001 §A/§G/§I/§L)端点已随后端一起删除,
  // V2 没有对应的候选确认流程——world_bible/scene_script 的 draft→人审→lock 循环本身
  // 就是生成前的人工确认门。preparationOverview/preparationState/extractShot/
  // confirmCandidate/setReadiness 不再存在,不留占位。
};

// ── 自媒体解说短视频通道(hevi.explainer,需登录)──────────────────────────────
import type { ExplainerRunRequest, ExplainerRunStatus } from '@/types/api';
export const explainerApi = {
  startRun: (payload: ExplainerRunRequest) =>
    authedReq<{ run_id: string; status: string }>('/api/explainer/run', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getStatus: (runId: string) =>
    authedReq<ExplainerRunStatus>(`/api/explainer/runs/${runId}`),
  listRuns: () =>
    authedReq<ExplainerRunStatus[]>('/api/explainer/runs'),
};

// ── 生产工具集(production-tools,对标 OpenMontage 新能力)──────────────────────
export interface ReferenceAnalyzeRequest {
  video_url: string;
  generate_concepts?: boolean;
}

export interface ReferenceAnalysis {
  task_id: string;
  status: string;
  pacing: {
    avg_shot_duration_s: number;
    cuts_per_minute: number;
    pacing_category: string;
  };
  style: {
    palette: string[];
    lighting: string;
    color_temperature: string;
    saturation: string;
    camera_motion: string[];
    visual_mood: string;
    aspect_ratio: string;
  };
  concepts: Array<{
    title: string;
    description: string;
    style_direction: string;
    pacing_match: string;
    estimated_cost_usd: number;
    differentiation: string;
  }>;
}

export interface StockSearchRequest {
  query: string;
  provider?: string;
  per_page?: number;
  orientation?: string;
}

export interface StockClip {
  url: string;
  provider: string;
  width: number;
  height: number;
  duration_s: number;
  description: string;
  license: string;
}

export interface EnhanceRequest {
  tool: string;
  params?: Record<string, any>;
}

export interface MediaProfile {
  name: string;
  width: number;
  height: number;
  aspect: string;
  max_duration_s: number | null;
  fps: number;
  notes: string;
}

export interface RemotionRenderRequest {
  manifest: Record<string, any>;
  composition: string;
  width?: number;
  height?: number;
  fps?: number;
}

export interface BacklotData {
  task_id: string;
  title: string;
  status: string;
  stage_rail: Array<{ stage: string; state: string }>;
  scene_cards: Array<{ shot_id: string; index: number; status: string; provider: string; duration_s: number; video_path: string }>;
  cost_meter: {
    estimated_usd: number;
    actual_usd: number;
    budget_usd: number;
    remaining_usd: number;
  };
}

// ── ViMax 集成(对标 HKUDS/ViMax 高级功能)────────────────────────────────────
import type {
  VimMaxPreset, VimMaxIdea2VideoRequest, VimMaxIdea2VideoResponse,
  VimMaxNovel2VideoRequest, VimMaxNovel2VideoResponse,
  VimMaxAutoCameoRequest, VimMaxAutoCameoResponse,
} from '@/types/api';

export const vimaxApi = {
  // Provider Presets
  listPresets: (category?: string) =>
    authedReq<{ presets: VimMaxPreset[]; total: number }>(
      `/api/director-pipeline/provider-presets${category ? `?category=${category}` : ''}`
    ),
  getPreset: (name: string) =>
    authedReq<VimMaxPreset & { resolved_config: Record<string, string> }>(
      `/api/director-pipeline/provider-presets/${name}`
    ),

  // Idea2Video — 一句话创意 → 完整视频
  idea2Video: (req: VimMaxIdea2VideoRequest) =>
    authedReq<VimMaxIdea2VideoResponse>('/api/director-pipeline/idea2video', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  // Novel2Video — 长文本/小说 → 视频
  novel2Video: (req: VimMaxNovel2VideoRequest) =>
    authedReq<VimMaxNovel2VideoResponse>('/api/director-pipeline/novel2video', {
      method: 'POST',
      body: JSON.stringify(req),
    }),

  // AutoCameo — 参考照片人物插入视频
  autocameo: (req: VimMaxAutoCameoRequest) =>
    authedReq<VimMaxAutoCameoResponse>('/api/director-pipeline/autocameo', {
      method: 'POST',
      body: JSON.stringify(req),
    }),
};

export const productionToolsApi = {
  // 参考视频分析
  analyzeReference: (req: ReferenceAnalyzeRequest) =>
    authedReq<{ task_id: string; status: string; output_dir: string }>('/api/production/reference-analyze', {
      method: 'POST',
      body: JSON.stringify(req),
    }),
  
  // Stock footage 检索
  searchStock: (query: string, provider = 'pexels', per_page = 5, orientation = 'portrait') =>
    req<{ query: string; provider: string; count: number; clips: StockClip[] }>(
      `/api/production/stock/search?query=${encodeURIComponent(query)}&provider=${provider}&per_page=${per_page}&orientation=${orientation}`
    ),
  
  // 对位校验
  matchStock: (caption: string, clip_url?: string, clip_description = '') =>
    req<{ score: number; matched_keywords: string[]; missed_keywords: string[]; eligible: boolean }>(
      `/api/production/stock/match?caption=${encodeURIComponent(caption)}&clip_url=${encodeURIComponent(clip_url || '')}&clip_description=${encodeURIComponent(clip_description)}`
    ),
  
  // 图像增强
  enhanceImage: (tool: string, file: File, params: Record<string, any> = {}) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('params', JSON.stringify(params));
    return authedFormReq<Blob>(`/api/production/enhance/${tool}`, formData);
  },
  
  // Playbook 列表
  listPlaybooks: () =>
    authedReq<{ playbooks: Array<{ id: string; name: string; type: string; [key: string]: any }> }>('/api/production/playbooks'),
  
  // 编译 Playbook prompt
  compilePlaybook: (req: { playbook_id: string; provider?: string; genre?: string; scene_description?: string }) =>
    authedReq<Record<string, string>>('/api/production/playbooks/compile', {
      method: 'POST',
      body: JSON.stringify(req),
    }),
  
  // Remotion 合成
  renderRemotion: (req: RemotionRenderRequest) =>
    authedReq<{ task_id: string; status: string; output_path: string }>('/api/production/render/remotion', {
      method: 'POST',
      body: JSON.stringify(req),
    }),
  
  // 媒体 Profile 列表
  listMediaProfiles: () =>
    authedReq<{ profiles: MediaProfile[] }>('/api/production/media-profiles'),
  
  // 获取 FFmpeg 参数
  getFFmpegArgs: (profileName: string) =>
    authedReq<{ profile: string; ffmpeg_args: string[] }>('/api/production/media-profiles/' + profileName + '/ffmpeg-args'),
  
  // Backlot 看板数据
  getBacklotData: (taskId: string) =>
    authedReq<BacklotData>(`/api/production/backlot/${taskId}`),
};

// ── 声音工作室(VoiceBox 集成)──────────────────────────────────────────────
export interface VoiceEffectPreset {
  name: string;
  effects: Array<{
    type: string;
    params: Record<string, any>;
    enabled: boolean;
  }>;
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

export const voiceStudioApi = {
  // Effects
  listEffectPresets: () =>
    authedReq<{ presets: VoiceEffectPreset[] }>('/api/voice-studio/effects/presets'),
  previewEffect: (preset: string, text: string) =>
    authedReq<{ preset: string; effects_count: number; effects: Array<{ type: string; params: Record<string, any> }> }>(
      '/api/voice-studio/effects/preview',
      { method: 'POST', body: JSON.stringify({ preset, text }) },
    ),

  // Personality
  listPersonalityPresets: () =>
    authedReq<{ presets: VoicePersonalityPreset[] }>('/api/voice-studio/personality/presets'),
  rewriteWithPersonality: (text: string, persona: string) =>
    authedReq<{ original: string; rewritten: string; persona: string; model_used: string; confidence: number }>(
      '/api/voice-studio/personality/rewrite',
      { method: 'POST', body: JSON.stringify({ text, persona }) },
    ),

  // TTS Engines
  listTTSEngines: () =>
    authedReq<{ engines: VoiceTTSEngine[] }>('/api/voice-studio/tts/engines'),
  synthesizeTTS: (text: string, engine: string, voice?: string, language?: string, effects?: string) =>
    authedReq<{ engine: string; message: string }>(
      '/api/voice-studio/tts/synthesize',
      { method: 'POST', body: JSON.stringify({ text, engine, voice, language, effects }) },
    ),

  // Config validation
  validateConfig: (voiceEffects?: string, voicePersonas?: Record<string, string>, ttsEngine?: string) =>
    authedReq<{ valid: boolean; voice_effects: string | null; voice_personas_count: number; tts_engine: string | null }>(
      '/api/voice-studio/config/validate',
      { method: 'POST', body: JSON.stringify({ voice_effects: voiceEffects, voice_personas: voicePersonas, tts_engine: ttsEngine }) },
    ),
};

// ── 发布工作室(publish_studio.py, prefix /studio)──────────────────────────────
export const publishStudioApi = {
  // 多平台发布
  listPlatforms: () =>
    authedReq<{ platforms: Array<{ id: string; name: string; enabled: boolean }> }>('/api/studio/publish/platforms'),
  publish: (body: { platform: string; video_path: string; title: string; description?: string; tags?: string[] }) =>
    authedReq<{ task_id: string; status: string }>('/api/studio/publish', { method: 'POST', body: JSON.stringify(body) }),
  confirmPublish: (body: { task_id: string }) =>
    authedReq<{ status: string; url?: string }>('/api/studio/publish/confirm', { method: 'POST', body: JSON.stringify(body) }),
  // 动效模板
  motionTemplates: (category?: string, search?: string) => {
    const q = new URLSearchParams();
    if (category) q.set('category', category);
    if (search) q.set('search', search);
    return authedReq<{ templates: Array<Record<string, unknown>> }>(`/api/studio/motion/templates${q.toString() ? `?${q}` : ''}`);
  },
  motionRender: (body: { template_id: string; params: Record<string, unknown> }) =>
    authedReq<{ task_id: string; status: string }>('/api/studio/motion/render', { method: 'POST', body: JSON.stringify(body) }),
  // HTML 视频
  htmlVideoTemplates: () =>
    authedReq<{ templates: Array<Record<string, unknown>> }>('/api/studio/html-video/templates'),
  htmlVideoRender: (body: { template_id: string; content: Record<string, unknown> }) =>
    authedReq<{ task_id: string; status: string }>('/api/studio/html-video/render', { method: 'POST', body: JSON.stringify(body) }),
  // 本地语音(OmniVoice)
  voiceClone: (body: { reference_audio: string; text: string }) =>
    authedReq<{ task_id: string; status: string }>('/api/studio/voice/clone', { method: 'POST', body: JSON.stringify(body) }),
  voiceDub: (body: { video_path: string; target_language: string }) =>
    authedReq<{ task_id: string; status: string }>('/api/studio/voice/dub', { method: 'POST', body: JSON.stringify(body) }),
  // 音乐编舞
  danceGpuCheck: () =>
    authedReq<{ available: boolean; gpu_name?: string; vram_mb?: number }>('/api/studio/dance/gpu-check'),
  danceGenerate: (body: { audio_path: string; dance_type: string; duration_s?: number }) =>
    authedReq<{ task_id: string; status: string }>('/api/studio/dance/generate', { method: 'POST', body: JSON.stringify(body) }),
};

// ── Pro 工作室(pro_studio.py, prefix /pro)─────────────────────────────────────
export const proStudioApi = {
  // IndexTTS2 情感语音
  indexttsSynthesize: (body: { speaker: string; text: string; emo_vector?: Record<string, number>; emo_text?: string; duration_s?: number }) =>
    authedReq<{ task_id: string; status: string; output_path?: string }>('/api/pro/indextts/synthesize', { method: 'POST', body: JSON.stringify(body) }),
  indexttsEmotionFromText: (body: { text: string }) =>
    authedReq<{ emo_vector: Record<string, number> }>('/api/pro/indextts/emotion-from-text', { method: 'POST', body: JSON.stringify(body) }),
  indexttsEmotions: () =>
    authedReq<{ emotions: string[] }>('/api/pro/indextts/emotions'),
  // 素材搜索
  stockSearch: (body: { query: string; provider?: string; media_type?: string; count?: number }) =>
    authedReq<{ clips: Array<Record<string, unknown>> }>('/api/pro/stock/search', { method: 'POST', body: JSON.stringify(body) }),
  // 数字人直播
  livestreamStart: (body: { avatar_id?: string; scene?: string }) =>
    authedReq<{ session_id: string; status: string }>('/api/pro/livestream/start', { method: 'POST', body: JSON.stringify(body) }),
  livestreamStop: (body: { session_id: string }) =>
    authedReq<{ status: string }>('/api/pro/livestream/stop', { method: 'POST', body: JSON.stringify(body) }),
  livestreamStatus: (sessionId: string) =>
    authedReq<{ status: string; viewers?: number; duration_s?: number }>(`/api/pro/livestream/status?session_id=${sessionId}`),
  // 多 Agent 编排
  orchestrationCreatePlan: (body: { task: string; agents?: string[] }) =>
    authedReq<{ plan_id: string; steps: Array<Record<string, unknown>> }>('/api/pro/orchestration/create-plan', { method: 'POST', body: JSON.stringify(body) }),
  orchestrationExecute: (body: { plan_id: string }) =>
    authedReq<{ task_id: string; status: string }>('/api/pro/orchestration/execute', { method: 'POST', body: JSON.stringify(body) }),
  orchestrationRoles: () =>
    authedReq<{ roles: Array<{ id: string; name: string; description: string }> }>('/api/pro/orchestration/roles'),
  // 代码解说
  codeExplainerGenerate: (body: { code: string; language?: string; style?: string }) =>
    authedReq<{ task_id: string; status: string }>('/api/pro/code-explainer/generate', { method: 'POST', body: JSON.stringify(body) }),
};

// ── 生产工具 V2(production_tools_v2.py, prefix /production/v2)─────────────────
export const productionV2Api = {
  seedanceGenerate: (body: { prompt: string; image_url?: string; duration_s?: number; aspect_ratio?: string }) =>
    authedReq<{ task_id: string; status: string }>('/api/production/v2/seedance/generate', { method: 'POST', body: JSON.stringify(body) }),
  clipVideo: (body: { video_path: string; strategy?: string; max_clips?: number }) =>
    authedReq<{ task_id: string; status: string; clips?: Array<Record<string, unknown>> }>('/api/production/v2/clip-video', { method: 'POST', body: JSON.stringify(body) }),
  listRecipes: () =>
    authedReq<{ recipes: Array<{ name: string; description: string; steps: number }> }>('/api/production/v2/recipes'),
  getRecipe: (name: string) =>
    authedReq<{ name: string; description: string; steps: Array<Record<string, unknown>> }>(`/api/production/v2/recipes/${name}`),
  executeRecipe: (name: string, body: { params: Record<string, unknown> }) =>
    authedReq<{ task_id: string; status: string }>(`/api/production/v2/recipes/${name}/execute`, { method: 'POST', body: JSON.stringify(body) }),
  digitalHumanPreflight: (body: { script: string; avatar_id?: string }) =>
    authedReq<{ ready: boolean; warnings?: string[] }>('/api/production/v2/digital-human/preflight', { method: 'POST', body: JSON.stringify(body) }),
  digitalHumanPreview: (body: { script: string; avatar_id?: string }) =>
    authedReq<{ task_id: string; status: string; preview_url?: string }>('/api/production/v2/digital-human/preview', { method: 'POST', body: JSON.stringify(body) }),
  digitalHumanApprove: (body: { task_id: string }) =>
    authedReq<{ status: string; output_path?: string }>('/api/production/v2/digital-human/approve', { method: 'POST', body: JSON.stringify(body) }),
};

