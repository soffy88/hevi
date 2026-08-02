/**
 * auth-store — JWT token + 当前用户管理(localStorage 持久化)。
 *
 * P0 修复:登录态需跨页面刷新保持。token 存 localStorage,
 * 应用启动时 syncAuthToken() 把 token 注入 api-client。
 */
'use client';

import type { AuthUser } from '@/types/api';
import { setAuthToken, USE_MOCK } from './api-client';

const TOKEN_KEY = 'hevi_token';
const USER_KEY = 'hevi_user';

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function getUser(): AuthUser | null {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw) as AuthUser; } catch { return null; }
}

export function getUserId(): string | null {
  return getUser()?.id ?? null;
}

/** 登录成功后调用:存 token + user,并注入 api-client。 */
export function login(token: string, user: AuthUser): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  setAuthToken(token);
}

export function logout(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  setAuthToken(null);
}

/** 应用启动 / 页面刷新时调用:从 localStorage 恢复 token 到 api-client。 */
export function syncAuthToken(): void {
  const token = getToken();
  // 生产环境切换出 mock 后，清掉旧版本遗留的 mock-token，避免工作台
  // 被误判为已登录，点击任务接口却只得到 401 后静默跳转。
  if (!USE_MOCK && token === 'mock-token') {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setAuthToken(null);
    return;
  }
  setAuthToken(token);
}

export function isAuthenticated(): boolean {
  const token = getToken();
  return token != null && (USE_MOCK || token !== 'mock-token');
}
