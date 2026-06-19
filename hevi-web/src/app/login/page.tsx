'use client';

import { useState } from 'react';
import { OLoginPage } from '@helios/oui';
import { useRouter } from 'next/navigation';
import { authApi, USE_MOCK } from '@/lib/api-client';
import { login } from '@/lib/auth-store';

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLogin = async (data: { email: string; password: string; remember: boolean }) => {
    setError(''); setLoading(true);
    try {
      if (USE_MOCK) {
        // mock 模式:本地造登录态,便于无后端时开发
        login('mock-token', { id: 'mock-user', email: data.email, display_name: '体验用户' });
        router.push('/');
        return;
      }
      const res = await authApi.login(data.email, data.password);
      login(res.token, res.user);
      router.push('/');
    } catch {
      setError('登录失败,请检查邮箱和密码');
    } finally {
      setLoading(false);
    }
  };

  return (
    <OLoginPage
      title="登录 hevi"
      subtitle="AI 视频创作工作台"
      methods={['email']}
      errorMessage={error || undefined}
      loading={loading}
      onEmailLogin={handleLogin}
      links={
        <span>
          还没有账号？<a href="/register" style={{ color: 'var(--primary)' }}>立即注册</a>
          {' · '}
          <a href="/pricing">查看套餐</a>
        </span>
      }
    />
  );
}
