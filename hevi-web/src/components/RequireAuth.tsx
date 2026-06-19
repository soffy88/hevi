'use client';

/**
 * RequireAuth — 路由守卫(问题2.3)
 * 需登录页面包裹:未登录 → 跳登录页。公开页(首页/画廊/登录/注册/价格)不用。
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth-store';

export function RequireAuth({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    // AuthProvider 已在启动时 syncAuthToken;这里读最终态
    if (!isAuthenticated()) {
      router.replace('/login');
    } else {
      setChecked(true);
    }
  }, [router]);

  if (!checked) {
    return (
      <div style={{ minHeight: '60vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--muted-foreground)' }}>
        正在验证登录状态…
      </div>
    );
  }
  return <>{children}</>;
}
