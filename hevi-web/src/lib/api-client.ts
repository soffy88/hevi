/**
 * hevi API client — REST 封装
 * 所有请求预留 Authorization header(SaaS 认证就绪后注入 JWT)。
 */
import type {
  CanvasGraph, CanvasNode, CanvasEdge,
  LongVideoTaskReq, TaskInfo, CostEstimateRes,
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
  // 角色参考图预览:<img src> 不能带 header,token 走查询参数(同 progressUrl/videoUrl)
  imageUrl: (subjectId: string, idx = 0) =>
    `${API_BASE}/api/subjects/${subjectId}/image?token=${authToken ? encodeURIComponent(authToken) : ''}&idx=${idx}`,
};

// ── 长视频任务 ────────────────────────────────────
export const taskApi = {
  create:   (r: LongVideoTaskReq) => authedReq<TaskInfo>('/api/tasks', { method: 'POST', body: JSON.stringify(r) }),
  list:     () => authedReq<TaskInfo[]>('/api/tasks'),
  get:      (id: string) => authedReq<TaskInfo>(`/api/tasks/${id}`),
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
