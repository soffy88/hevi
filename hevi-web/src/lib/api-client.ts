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
async function authedReq<T>(path: string, init?: RequestInit): Promise<T> {
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
  DpConcept, DpScreenplay, DpDesignList, DpShotList, DpWork, DpProduceRequest,
  DpPrepState, DpPrepMutation, DpPrepOverview,
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
  regenerateShotList: (workId: string) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/shot-list`, { method: 'POST' }),
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
  lockShotList: (workId: string, body: DpShotList) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/shot-list/lock`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  // 仅 shot_list_locked 才允许,建真实 video_task 出片
  produce: (workId: string, body: DpProduceRequest) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/produce`, {
      method: 'POST', body: JSON.stringify(body),
    }),
  // ── INC-001 §A/§G/§I/§L 逐镜头准备台 ──
  preparationOverview: (workId: string) =>
    authedReq<DpPrepOverview>(`/api/director-pipeline/works/${workId}/preparation-overview`),
  preparationState: (workId: string, shotId: string) =>
    authedReq<DpPrepState>(
      `/api/director-pipeline/works/${workId}/shots/${shotId}/preparation-state`),
  extractShot: (workId: string, shotId: string) =>
    authedReq<DpPrepMutation>(
      `/api/director-pipeline/works/${workId}/shots/${shotId}/extract`, { method: 'POST' }),
  confirmCandidate: (
    workId: string, shotId: string, candidateId: string,
    body: { kind: 'asset' | 'dialogue'; status: string;
      linked_entity_id?: string | null; linked_dialog_line_id?: string | null },
  ) =>
    authedReq<DpPrepMutation>(
      `/api/director-pipeline/works/${workId}/shots/${shotId}/candidates/${candidateId}/confirm`,
      { method: 'POST', body: JSON.stringify(body) }),
  setReadiness: (workId: string, shotId: string, skipExtraction: boolean) =>
    authedReq<DpPrepMutation>(
      `/api/director-pipeline/works/${workId}/shots/${shotId}/readiness`,
      { method: 'PATCH', body: JSON.stringify({ skip_extraction: skipExtraction }) }),
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

