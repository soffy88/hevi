/**
 * hevi API client — REST 封装
 * 所有请求预留 Authorization header(SaaS 认证就绪后注入 JWT)。
 */
import type {
  CanvasGraph, CanvasNode, CanvasEdge,
  LongVideoTaskReq, TaskInfo, TaskShot, CostEstimateRes,
  CreativeCapability, Subject, SubjectKind,
  AuthRes, AuthUser, CreditsBalance,
  CapabilityDescriptor, Presenter, PresenterInput, PresenterReadiness, ProductionRequest, ProductionTask,
  AspectRatio, QualityProfile, LiteAssemblePayload, LiteAssembleAccepted,
  LiteRunCreatePayload, LiteRunRecord, LiteCueInput,
} from '@/types/api';
export type { VoiceEffectPreset, VoicePersonalityPreset, VoiceTTSEngine } from '@/types/api';

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
  if (!res.ok) {
    let detail = '';
    try {
      const payload = await res.json() as { detail?: unknown; message?: unknown };
      if (typeof payload.detail === 'string') detail = payload.detail;
      else if (payload.detail && typeof payload.detail === 'object') {
        const data = payload.detail as { message?: unknown; setup?: unknown };
        detail = [data.message, data.setup].filter((v): v is string => typeof v === 'string').join('：');
      } else if (typeof payload.message === 'string') detail = payload.message;
    } catch { /* non-JSON error */ }
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
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
  if (!res.ok) {
    let detail = '';
    try {
      const payload = await res.json() as { detail?: unknown; message?: unknown };
      if (typeof payload.detail === 'string') detail = payload.detail;
      else if (payload.detail && typeof payload.detail === 'object') {
        const data = payload.detail as { message?: unknown; setup?: unknown };
        detail = [data.message, data.setup].filter((v): v is string => typeof v === 'string').join('：');
      } else if (typeof payload.message === 'string') detail = payload.message;
    } catch { /* non-JSON error */ }
    throw new Error(detail || `${res.status} ${res.statusText}`);
  }
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

export const studioApi = {
  tools: () => authedReq<{ tools: { id: string; kind: string; summary: string }[]; total: number }>('/api/studio/tools'),
  lines: () => authedReq<{ lines: { id: string; product: string; summary: string; tools: string[]; render_runtime?: string }[]; total: number }>('/api/studio/lines'),
  invoke: (toolId: string, payload: Record<string, unknown>) =>
    authedReq<{ status: string; payload: Record<string, unknown>; reason: string }>(`/api/studio/tools/${toolId}`, {
      method: 'POST', body: JSON.stringify({ payload }),
    }),
  slate: (line_id: string, slots: Record<string, unknown>) =>
    authedReq<Record<string, unknown>>('/api/studio/slates', { method: 'POST', body: JSON.stringify({ line_id, slots }) }),
  createTimeline: (title: string, edit_plan: Record<string, unknown>) =>
    authedReq<StudioTimeline>('/api/studio/timelines', { method: 'POST', body: JSON.stringify({ title, edit_plan }) }),
  getTimeline: (id: string) => authedReq<StudioTimeline>(`/api/studio/timelines/${id}`),
  listTimelines: () => authedReq<{ timelines: StudioTimeline[]; total: number }>('/api/studio/timelines'),
  patchTimeline: (id: string, body: Record<string, unknown>) =>
    authedReq<StudioTimeline>(`/api/studio/timelines/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  exportTimeline: (id: string, output_path?: string) =>
    authedReq<Record<string, unknown>>(`/api/studio/timelines/${id}/export`, {
      method: 'POST', body: JSON.stringify({ output_path: output_path ?? 'output/nle/timeline.mp4' }),
    }),
  veyaCapabilities: () => authedReq<Record<string, unknown>>('/api/studio/veya/capabilities'),
  veyaProduce: (body: {
    line_id: string;
    slots?: Record<string, unknown>;
    render_runtime?: string;
    execute?: boolean;
    publish?: boolean;
    platforms?: string[];
  }) => authedReq<Record<string, unknown>>('/api/studio/veya/produce', {
    method: 'POST',
    body: JSON.stringify(body),
  }),
  veyaJob: (id: string) => authedReq<Record<string, unknown>>(`/api/studio/veya/jobs/${id}`),
  dailyCalendars: () => authedReq<{ calendars: Record<string, unknown>[]; total: number }>('/api/studio/daily/calendars'),
  addDailyTopics: (calendarId: string, topics: Record<string, unknown>[]) =>
    authedReq<Record<string, unknown>>(`/api/studio/daily/calendars/${calendarId}/topics`, {
      method: 'POST',
      body: JSON.stringify({ topics }),
    }),
  tickDaily: (body?: { calendar_id?: string; now?: string; publish?: boolean }) =>
    authedReq<{ jobs: Record<string, unknown>[]; count: number }>('/api/studio/daily/tick', {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),
};

export type StudioTimelineClip = {
  clip_id: string; track: string; start_s: number; duration_s: number;
  label: string; action: string; source: string; text: string;
};
export type StudioTimeline = {
  timeline_id: string; title: string; duration_s: number; bgm: string; fps: number;
  clips: StudioTimelineClip[];
  tracks: { video: StudioTimelineClip[]; audio: StudioTimelineClip[]; captions: StudioTimelineClip[] };
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
  audioUrl: (id: string) =>
    `${API_BASE}/api/tasks/${id}/audio${authToken ? `?token=${encodeURIComponent(authToken)}` : ''}`,
  // 成本预估
  estimate: (r: LongVideoTaskReq) => req<CostEstimateRes>('/api/tasks/estimate', { method: 'POST', body: JSON.stringify(r) }),
};

// ── 统一自动生产 / 数字人预设 ─────────────────────────────────────
export const productionApi = {
  capabilities: () => authedReq<{ capabilities: CapabilityDescriptor[] }>('/api/pipeline/capabilities'),
  create: (payload: ProductionRequest) =>
    authedReq<ProductionTask>('/api/pipeline/productions', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  generate: (payload: {
    source_channel: 'hub_quick' | 'hub_idea2video' | 'director_console';
    adapter_type: 'default' | 'explainer' | 'tongjian' | 'shortdrama';
    config: {
      prompt: string;
      duration_archetype: string;
      aspect_ratio: AspectRatio;
      execution_preset: 'economy' | 'balanced' | 'fast';
      character_references?: string[];
      presenter_id?: string | null;
      emotion_aware_voiceover?: boolean;
      locked_shot_list?: Array<Record<string, unknown>> | null;
      quality_profile?: QualityProfile;
      options?: Record<string, unknown>;
    };
  }) => authedReq<ProductionTask>('/api/pipeline/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
};

export const presenterApi = {
  list: () => authedReq<Presenter[]>('/api/presenters'),
  ensureDefault: () => authedReq<Presenter>('/api/presenters/default', { method: 'POST' }),
  get: (id: string) => authedReq<Presenter>(`/api/presenters/${id}`),
  create: (payload: PresenterInput) =>
    authedReq<Presenter>('/api/presenters', { method: 'POST', body: JSON.stringify(payload) }),
  update: (id: string, payload: PresenterInput) =>
    authedReq<Presenter>(`/api/presenters/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  test: (id: string) => authedReq<PresenterReadiness>(`/api/presenters/${id}/test`, { method: 'POST' }),
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
  DpConcept, DpScreenplay, DpDesignList, DpSceneStageSet, DpShotList, DpWork, DpProduceRequest,
  DpPrepState, DpPrepMutation, DpPrepOverview, DpParseRequest, DpDispatchSeasonRequest,
} from '@/types/api';
export const directorPipelineApi = {
  parseWork: (payload: DpParseRequest) =>
    authedReq<DpWork>('/api/director-pipeline/works/parse', {
      method: 'POST', body: JSON.stringify(payload),
    }),
  dispatchSeason: (workId: string, payload: DpDispatchSeasonRequest) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/dispatch-season`, {
      method: 'POST', body: JSON.stringify(payload),
    }),
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
  // SPEC-004 ③.5 场面调度:重新生成本级草稿(逐场 SceneStage)
  regenerateSceneStage: (workId: string) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/scene-stage`, { method: 'POST' }),
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
  // SPEC-004 ③.5:锁定(可能已攻击过的)场面调度 → 后台生成④分镜草稿 + 跑 §4 lint
  lockSceneStage: (workId: string, body: DpSceneStageSet) =>
    authedReq<DpWork>(`/api/director-pipeline/works/${workId}/scene-stage/lock`, {
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
import type {
  DashboardTask,
  DashboardTaskList,
  ExplainerAssembleRequest,
  ExplainerAssemblyAccepted,
  ExplainerResearchJob,
  ExplainerResearchRequest,
  ExplainerResearchResponse,
  ExplainerRunRequest,
  ExplainerRunStatus,
  PresenterImageCheckResponse,
} from '@/types/api';
export const explainerApi = {
  /** 异步研究:立即返 202 + processing 信封,前端凭 session_id 轮询。 */
  research: (payload: ExplainerResearchRequest) =>
    authedReq<ExplainerResearchJob>('/api/explainer/research', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  /** 轮询研究任务状态;status=ready 后 payload 即完整确稿数据(断点续传也走它)。 */
  researchCache: (sessionId: string) =>
    authedReq<ExplainerResearchJob>(`/api/explainer/research/${sessionId}`, {
      method: 'GET',
    }),
  assemble: (payload: ExplainerAssembleRequest) =>
    authedReq<ExplainerAssemblyAccepted>('/api/explainer/assemble', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  startRun: (payload: ExplainerRunRequest) =>
    authedReq<{ run_id: string; status: string }>('/api/explainer/run', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  getStatus: (runId: string) =>
    authedReq<ExplainerRunStatus>(`/api/explainer/runs/${runId}`),
  listRuns: () =>
    authedReq<ExplainerRunStatus[]>('/api/explainer/runs'),
  /** v9.1 底图上传:字节落盘 + 服务端权威质检,通过后返回可读回的本地路径。 */
  uploadPresenterImage: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return authedFormReq<PresenterImageCheckResponse>(
      '/api/explainer/upload-presenter-image',
      form,
    );
  },
  /** v9.1 素材质检:远端 URL 的合法性复核(提交装配前的服务端双保险)。 */
  validatePresenterImage: (imageUrl: string) =>
    authedReq<PresenterImageCheckResponse>('/api/explainer/validate-presenter-image', {
      method: 'POST',
      body: JSON.stringify({ image_url: imageUrl }),
    }),
};

// ── v9.1 任务大盘(SQLite TaskRun + WebSocket 实时进度) ───────────────────

export const dashboardApi = {
  /** 分页 + 状态过滤的任务历史大盘,按 created_at 倒序。 */
  listTasks: (params?: { limit?: number; offset?: number; status?: string }) =>
    authedReq<DashboardTaskList>(
      `/api/dashboard/tasks?${new URLSearchParams(
        Object.entries({
          limit: String(params?.limit ?? 20),
          offset: String(params?.offset ?? 0),
          ...(params?.status ? { status: params.status } : {}),
        }),
      ).toString()}`,
    ),
  /** 单工单详情(含颗粒度 state_json,断点续传/排障可读)。 */
  getTask: (taskId: string) =>
    authedReq<DashboardTask>(`/api/dashboard/tasks/${encodeURIComponent(taskId)}`),
  /** 成片预览/下载:<video>/<a download> 不能带 header,token 走查询参数(同 taskApi.videoUrl)。 */
  outputUrl: (taskId: string) =>
    `${API_BASE}/api/dashboard/tasks/${encodeURIComponent(taskId)}/output${authToken ? `?token=${encodeURIComponent(authToken)}` : ''}`,
};

// ── v9.1 Lite 管道发射台(轻量解说: HTML→录屏→成片) ──────────────────────

export const liteApi = {
  /** 提交 Lite 装配任务;202 受理后后台执行,大盘实时看进度。 */
  assemble: (payload: LiteAssemblePayload) =>
    authedReq<LiteAssembleAccepted>('/api/lite/assemble', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  /** 选题 → LLM 文案 + veya-loop → awaiting_confirm。 */
  createRun: (payload: LiteRunCreatePayload) =>
    authedReq<LiteRunRecord>('/api/lite/runs', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  getRun: (runId: string) => authedReq<LiteRunRecord>(`/api/lite/runs/${runId}`),

  /** 审稿 HTML 预览 URL(iframe src;不落 MP4)。带 cache-bust。 */
  previewUrl: (runId: string, bust?: number | string) =>
    `${API_BASE}/api/lite/runs/${encodeURIComponent(runId)}/preview.html?t=${bust ?? Date.now()}`,

  patchScript: (
    runId: string,
    body: {
      title?: string;
      hook?: string;
      script?: string;
      cues?: LiteCueInput[];
      reloop?: boolean;
      max_rounds?: number;
    },
  ) =>
    authedReq<LiteRunRecord>(`/api/lite/runs/${runId}/script`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  reloop: (runId: string, maxRounds = 2) =>
    authedReq<LiteRunRecord>(`/api/lite/runs/${runId}/reloop?max_rounds=${maxRounds}`, {
      method: 'POST',
    }),

  /** 确认文案 → 本地零费用出片。 */
  confirm: (runId: string, body?: { script?: string; cues?: LiteCueInput[] }) =>
    authedReq<LiteRunRecord>(`/api/lite/runs/${runId}/confirm`, {
      method: 'POST',
      body: JSON.stringify(body ?? {}),
    }),
};

// ── 恢复的工作室能力（与原有工作台保持同一客户端边界） ────────────────
import type {
  VoiceEffectPreset, VoicePersonalityPreset, VoiceTTSEngine,
  ProviderPreset,
} from '@/types/api';

export const providerApi = {
  listPresets: (category?: string) => authedReq<{ presets: ProviderPreset[]; total: number; levels: string[] }>(`/api/providers/presets${category ? `?category=${category}` : ''}`),
  getPreset: (name: string) => authedReq<ProviderPreset & { resolved_config: Record<string, string> }>(`/api/providers/presets/${name}`),
};

export const voiceStudioApi = {
  listEffectPresets: () => authedReq<{ presets: VoiceEffectPreset[] }>('/api/voice-studio/effects/presets'),
  previewEffect: (preset: string, text: string) => authedReq<{ preset: string; effects_count: number; effects: Array<{ type: string; params: Record<string, unknown> }> }>('/api/voice-studio/effects/preview', { method: 'POST', body: JSON.stringify({ preset, text }) }),
  listPersonalityPresets: () => authedReq<{ presets: VoicePersonalityPreset[] }>('/api/voice-studio/personality/presets'),
  rewriteWithPersonality: (text: string, persona: string) => authedReq<{ original: string; rewritten: string; persona: string; model_used: string; confidence: number }>('/api/voice-studio/personality/rewrite', { method: 'POST', body: JSON.stringify({ text, persona }) }),
  listTTSEngines: () => authedReq<{ engines: VoiceTTSEngine[] }>('/api/voice-studio/tts/engines'),
  synthesizeTTS: (text: string, engine: string, voice?: string, language?: string, effects?: string) => authedReq<{ task_id: string; status: string; audio_url: string }>('/api/voice-studio/tts/synthesize', { method: 'POST', body: JSON.stringify({ text, engine, voice, language, effects }) }),
  compareTTS: (body: { engine_a: string; engine_b: string; text: string; language?: string; voice_a?: string; voice_b?: string }) => authedReq<{ engine_a: { task_id: string; status: string; audio_url: string; engine: string }; engine_b: { task_id: string; status: string; audio_url: string; engine: string }; text: string }>('/api/voice-studio/tts/compare', { method: 'POST', body: JSON.stringify(body) }),
  validateConfig: (voiceEffects?: string, voicePersonas?: Record<string, string>, ttsEngine?: string) => authedReq<{ valid: boolean; voice_effects: string | null; voice_personas_count: number; tts_engine: string | null }>('/api/voice-studio/config/validate', { method: 'POST', body: JSON.stringify({ voice_effects: voiceEffects, voice_personas: voicePersonas, tts_engine: ttsEngine }) }),
};

export const productionV2Api = {
  seedanceGenerate: (body: { prompt: string; image_url?: string; duration_s?: number; aspect_ratio?: string }) => authedReq<{ task_id: string; status: string }>('/api/production/v2/seedance/generate', { method: 'POST', body: JSON.stringify(body) }),
  clipVideo: (body: { video_path: string; strategy?: string; max_clips?: number }) => authedReq<{ task_id: string; status: string; clips?: Array<Record<string, unknown>> }>('/api/production/v2/clip-video', { method: 'POST', body: JSON.stringify(body) }),
  listRecipes: () => authedReq<{ recipes: Array<{ name: string; description: string; steps: number }> }>('/api/production/v2/recipes'),
  getRecipe: (name: string) => authedReq<{ name: string; description: string; steps: Array<Record<string, unknown>> }>(`/api/production/v2/recipes/${name}`),
  executeRecipe: (name: string, body: { params: Record<string, unknown> }) => authedReq<{ task_id: string; status: string }>(`/api/production/v2/recipes/${name}/execute`, { method: 'POST', body: JSON.stringify(body) }),
  digitalHumanPreflight: (body: { script: string; avatar_id?: string }) => authedReq<{ ready: boolean; warnings?: string[] }>('/api/production/v2/digital-human/preflight', { method: 'POST', body: JSON.stringify(body) }),
  digitalHumanPreview: (body: { script: string; avatar_id?: string }) => authedReq<{ task_id: string; status: string; preview_url?: string }>('/api/production/v2/digital-human/preview', { method: 'POST', body: JSON.stringify(body) }),
  digitalHumanApprove: (body: { task_id: string }) => authedReq<{ status: string; output_path?: string }>('/api/production/v2/digital-human/approve', { method: 'POST', body: JSON.stringify(body) }),
};

export const proStudioApi = {
  indexttsSynthesize: (body: { speaker: string; text: string; emo_vector?: Record<string, number>; emo_text?: string; duration_s?: number }) => authedReq<{ task_id: string; status: string; output_path?: string }>('/api/pro/indextts/synthesize', { method: 'POST', body: JSON.stringify(body) }),
  indexttsEmotionFromText: (body: { text: string }) => authedReq<{ emo_vector: Record<string, number> }>('/api/pro/indextts/emotion-from-text', { method: 'POST', body: JSON.stringify(body) }),
  indexttsEmotions: () => authedReq<{ emotions: string[] }>('/api/pro/indextts/emotions'),
  stockSearch: (body: { query: string; provider?: string; media_type?: string; count?: number }) => authedReq<{ clips: Array<Record<string, unknown>> }>('/api/pro/stock/search', { method: 'POST', body: JSON.stringify(body) }),
  livestreamCapabilities: () => authedReq<{ can_start: boolean; provider?: string | null; message: string; setup?: string }>('/api/pro/livestream/capabilities'),
  livestreamStart: (body: { presenter_id?: string; avatar_id?: string; scene?: string; script: string }) => authedReq<{ session_id: string; status: string; presenter_id?: string; stream_url?: string; message?: string }>('/api/pro/livestream/start', { method: 'POST', body: JSON.stringify(body) }),
  livestreamStop: (body: { session_id: string }) => authedReq<{ status: string }>('/api/pro/livestream/stop', { method: 'POST', body: JSON.stringify(body) }),
  livestreamStatus: (sessionId: string) => authedReq<{ status: string; viewers?: number; duration_s?: number }>(`/api/pro/livestream/status?session_id=${sessionId}`),
  livetalkingWebrtcCapabilities: () => authedReq<{ can_start: boolean; provider?: string | null; message: string; setup?: string }>('/api/pro/livetalking/webrtc/capabilities'),
  livetalkingWebrtcOffer: (body: { sdp: string; type?: string; avatar_id?: string }) => authedReq<{ session_id: string; sdp: string; type: string; provider: string; status: string }>('/api/pro/livetalking/webrtc/offer', { method: 'POST', body: JSON.stringify(body) }),
  livetalkingRtmpStatus: () => authedReq<{ provider: string; playback_url: string; reachable: boolean | null; message?: string; http_status?: number }>('/api/pro/livetalking/rtmp/status'),
  orchestrationCreatePlan: (body: { task: string; agents?: string[] }) => authedReq<{ plan_id: string; steps: Array<Record<string, unknown>> }>('/api/pro/orchestration/create-plan', { method: 'POST', body: JSON.stringify(body) }),
  orchestrationExecute: (body: { plan_id: string }) => authedReq<{ task_id: string; status: string }>('/api/pro/orchestration/execute', { method: 'POST', body: JSON.stringify(body) }),
  orchestrationRoles: () => authedReq<{ roles: Array<{ id: string; name: string; description: string }> }>('/api/pro/orchestration/roles'),
  codeExplainerGenerate: (body: { code: string; language?: string; style?: string }) => authedReq<{ task_id: string; status: string }>('/api/pro/code-explainer/generate', { method: 'POST', body: JSON.stringify(body) }),
};

export const publishStudioApi = {
  listPlatforms: () => authedReq<{ platforms: Array<{ id: string; name: string; enabled: boolean }> }>('/api/studio/publish/platforms'),
  publish: (body: { platform: string; video_path: string; title: string; description?: string; tags?: string[] }) => authedReq<{ task_id: string; status: string }>('/api/studio/publish', { method: 'POST', body: JSON.stringify(body) }),
  confirmPublish: (body: { task_id: string }) => authedReq<{ status: string; url?: string }>('/api/studio/publish/confirm', { method: 'POST', body: JSON.stringify(body) }),
  motionTemplates: (category?: string, search?: string) => { const q = new URLSearchParams(); if (category) q.set('category', category); if (search) q.set('search', search); return authedReq<{ templates: Array<Record<string, unknown>> }>(`/api/studio/motion/templates${q.toString() ? `?${q}` : ''}`); },
  motionRender: (body: { template_id: string; params: Record<string, unknown> }) => authedReq<{ task_id: string; status: string }>('/api/studio/motion/render', { method: 'POST', body: JSON.stringify(body) }),
  htmlVideoTemplates: () => authedReq<{ templates: Array<Record<string, unknown>> }>('/api/studio/html-video/templates'),
  htmlVideoRender: (body: { template_id: string; content: Record<string, unknown> }) => authedReq<{ task_id: string; status: string }>('/api/studio/html-video/render', { method: 'POST', body: JSON.stringify(body) }),
  voiceClone: (body: { reference_audio: string; text: string }) => authedReq<{ task_id: string; status: string }>('/api/studio/voice/clone', { method: 'POST', body: JSON.stringify(body) }),
  voiceDub: (body: { video_path: string; target_language: string }) => authedReq<{ task_id: string; status: string }>('/api/studio/voice/dub', { method: 'POST', body: JSON.stringify(body) }),
  danceGpuCheck: () => authedReq<{ available: boolean; gpu_name?: string; vram_mb?: number }>('/api/studio/dance/gpu-check'),
  danceGenerate: (body: { audio_path: string; dance_type: string; duration_s?: number }) => authedReq<{ task_id: string; status: string }>('/api/studio/dance/generate', { method: 'POST', body: JSON.stringify(body) }),

  // ── MPT 集成 (MoneyPrinterTurbo) ─────────────────────────────────
  mptGenerate: (body: { topic: string; video_count: number; aspect: string; voice: string; bgm: boolean; subtitle: boolean; material_mode: string }) => authedReq<{ task_id: string; status: string; message: string }>('/api/mpt/generate', { method: 'POST', body: JSON.stringify(body) }),
  mptStatus: (taskId: string) => authedReq<{ state: string; progress: number; videos: string[]; error: string | null }>('/api/mpt/status/' + taskId, { method: 'GET' }),
  mptMaterials: (body: { query: string; source: string; count: number; min_duration: number }) => authedReq<{ pexels: any; pixabay: any; archive_org: any }>('/api/mpt/materials/search', { method: 'POST', body: JSON.stringify(body) }),
  mptCrossPost: (body: { video_path: string; title: string; platforms: string[] }) => authedReq<{ success: boolean; request_id?: string; message?: string }>('/api/mpt/cross-post', { method: 'POST', body: JSON.stringify(body) }),
  mptReference: (body: { url: string }) => authedReq<{ transcript: any; rhythm: any; scenes: any; concepts: any; metadata: any }>('/api/mpt/reference/analyze', { method: 'POST', body: JSON.stringify(body) }),
  mptSubmitJob: (production_id: string, revision_id: string, topic: string, video_count: number, aspect: string, voice: string) => authedReq<{ task_id: string; status: string; message: string }>('/api/mpt/hevi/submit-job?production_id=' + production_id + '&revision_id=' + revision_id + '&topic=' + encodeURIComponent(topic) + '&video_count=' + video_count + '&aspect=' + aspect + '&voice=' + voice, { method: 'GET' }),
};

// ── 黄金公式动画演绎 (故事 → 分镜矩阵 → 动画出片) ────────────────
export const cinematicApi = {
  animate: (body: { story: string; beats_json?: string; ratio?: string; task_id?: string }) =>
    authedReq<{ task_id: string; status: string; progress: number; n_beats: number }>('/api/cinematic/animate', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  get: (taskId: string) =>
    authedReq<{ task_id: string; status: string; progress: number; error?: string; stage?: string; shot_index?: number; beats?: Array<Record<string, unknown>>; video_path?: string }>(`/api/cinematic/tasks/${taskId}`),
  videoUrl: (taskId: string) =>
    `${API_BASE}/api/cinematic/tasks/${taskId}/video${authToken ? `?token=${encodeURIComponent(authToken)}` : ''}`,
};
