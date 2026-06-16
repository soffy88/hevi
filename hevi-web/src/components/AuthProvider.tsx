'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { syncAuthToken, logout } from '@/lib/auth-store';
import { setUnauthorizedHandler } from '@/lib/api-client';

/**
 * AuthProvider — 应用启动时:
 * 1. 从 localStorage 恢复 JWT 注入 api-client(页面刷新后保持登录)
 * 2. 注册 401 handler:token 过期 → 清登录态 → 跳登录页
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  useEffect(() => {
    syncAuthToken();
    setUnauthorizedHandler(() => {
      logout();
      router.push('/login');
    });
  }, [router]);

  return <>{children}</>;
}
