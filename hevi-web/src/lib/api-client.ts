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

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string>),
  };
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (res.status === 401) {
    onUnauthorized?.();
    throw new Error('401 Unauthorized');
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

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
  balance: () => req<CreditsBalance>('/api/credits/balance'),
};

// ── 画布 CRUD ─────────────────────────────────────
export const canvasApi = {
  save:   (g: Partial<CanvasGraph>) => req<CanvasGraph>('/api/canvas', { method: 'POST', body: JSON.stringify(g) }),
  list:   (userId?: string) => req<CanvasGraph[]>(`/api/canvas${userId ? `?user=${userId}` : ''}`),
  load:   (id: string) => req<CanvasGraph>(`/api/canvas/${id}`),
  update: (id: string, patch: Partial<CanvasGraph>) => req<CanvasGraph>(`/api/canvas/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  remove: (id: string) => req<void>(`/api/canvas/${id}`, { method: 'DELETE' }),
  execute:(id: string) => req<{ task_id: string }>(`/api/canvas/${id}/execute`, { method: 'POST' }),
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
  create: (s: Partial<Subject>) => req<Subject>('/api/subjects', { method: 'POST', body: JSON.stringify(s) }),
  list:   (kind?: SubjectKind, query?: string) => {
    const q = new URLSearchParams();
    if (kind) q.set('kind', kind);
    if (query) q.set('query', query);
    return req<Subject[]>(`/api/subjects${q.toString() ? `?${q}` : ''}`);
  },
  get:    (id: string) => req<Subject>(`/api/subjects/${id}`),
  update: (id: string, patch: Partial<Subject>) => req<Subject>(`/api/subjects/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  remove: (id: string) => req<void>(`/api/subjects/${id}`, { method: 'DELETE' }),
};

// ── 长视频任务 ────────────────────────────────────
export const taskApi = {
  create:   (r: LongVideoTaskReq) => req<TaskInfo>('/api/tasks', { method: 'POST', body: JSON.stringify(r) }),
  list:     () => req<TaskInfo[]>('/api/tasks'),
  get:      (id: string) => req<TaskInfo>(`/api/tasks/${id}`),
  resume:   (id: string) => req<TaskInfo>(`/api/tasks/${id}/resume`, { method: 'POST' }),
  progressUrl: (id: string) => `${API_BASE}/api/tasks/${id}/progress`,
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
  list: (category?: GalleryCategory) => req<GalleryItem[]>(`/api/gallery${category ? `?category=${category}` : ''}`),
  get:  (itemId: string) => req<GalleryItem>(`/api/gallery/${itemId}`),
};
