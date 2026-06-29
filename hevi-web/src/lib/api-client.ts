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

// ── 创意辅助 ──────────────────────────────────────
export const creativeApi = {
  capabilities: () => req<CreativeCapability[]>('/api/creative/capabilities'),
  call: (id: string, body: unknown) => req<unknown>(`/api/creative/${id}`, { method: 'POST', body: JSON.stringify(body) }),
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
  // 成本预估
  estimate: (r: LongVideoTaskReq) => req<CostEstimateRes>('/api/tasks/estimate', { method: 'POST', body: JSON.stringify(r) }),
};

export { USE_MOCK, API_BASE };

// ── 模板/音效(P11.F)──────────────────────────────
export const assetApi = {
  templates: (category?: string) => req<{ id: string; name: string; desc?: string }[]>(`/api/templates${category ? `?category=${category}` : ''}`),
  audio:     (type?: string) => req<{ id: string; name: string; dur?: string }[]>(`/api/audio${type ? `?type=${type}` : ''}`),
};

// ── 画廊(§5,公开无需 token)──────────────────────
import type { GalleryItem, GalleryCategory } from '@/types/api';
export const galleryApi = {
  list: (category?: GalleryCategory) =>
    req<{ items: GalleryItem[] } | GalleryItem[]>(`/api/gallery${category ? `?category=${category}` : ''}`)
      .then(r => (Array.isArray(r) ? r : (r as { items: GalleryItem[] }).items ?? [])),
  get:  (itemId: string) => req<GalleryItem>(`/api/gallery/${itemId}`),
};
