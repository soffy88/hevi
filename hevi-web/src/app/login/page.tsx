'use client';

/**
 * /login — 登录 + 注册(v0.7.0)
 * 注册能力已上提到 @helios/oui 1.7.0:OLoginPage 内置登录/注册 tab 切换。
 * 不再手写 /register 页 —— onEmailRegister 直接接后端 register 接口,注册成功自动登录。
 */

import { useState } from 'react';
import { OLoginPage } from '@helios/oui';
import { useRouter } from 'next/navigation';
import { authApi, USE_MOCK } from '@/lib/api-client';
import { login } from '@/lib/auth-store';

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState('');
  const [registerError, setRegisterError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleLogin = async (data: { email: string; password: string; remember: boolean }) => {
    setError(''); setLoading(true);
    try {
      if (USE_MOCK) {
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

  const handleRegister = async (data: { email: string; password: string; displayName: string }) => {
    setRegisterError(''); setLoading(true);
    try {
      if (USE_MOCK) {
        login('mock-token', { id: 'mock-user', email: data.email, display_name: data.displayName });
        router.push('/');
        return;
      }
      const res = await authApi.register(data.email, data.password, data.displayName);
      // 注册成功直接拿 token 自动登录
      login(res.token, res.user);
      router.push('/');
    } catch (e: unknown) {
      const status = (e as { message?: string })?.message ?? '';
      if (status.includes('409')) setRegisterError('该邮箱已被注册,请直接登录');
      else if (status.includes('422')) setRegisterError('信息校验失败,请检查邮箱格式和密码强度');
      else setRegisterError('注册失败,请稍后重试');
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
      registerError={registerError || undefined}
      loading={loading}
      onEmailLogin={handleLogin}
      onEmailRegister={handleRegister}
      links={<a href="/pricing">查看套餐</a>}
    />
  );
}
