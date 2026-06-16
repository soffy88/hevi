/**
 * auth-store — JWT token + 当前用户管理(localStorage 持久化)。
 *
 * P0 修复:登录态需跨页面刷新保持。token 存 localStorage,
 * 应用启动时 syncAuthToken() 把 token 注入 api-client。
 */
'use client';

import type { AuthUser } from '@/types/api';
import { setAuthToken } from './api-client';

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
  setAuthToken(getToken());
}

export function isAuthenticated(): boolean {
  return getToken() != null;
}
