'use client';

/**
 * /register — 注册页(问题1)
 * email + password(确认 + 强度提示)+ display_name → POST /api/auth/register → 自动登录。
 */

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { authApi, USE_MOCK } from '@/lib/api-client';
import { login } from '@/lib/auth-store';

function passwordStrength(pw: string): { label: string; color: string; pct: number } {
  let score = 0;
  if (pw.length >= 8) score++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  const map = [
    { label: '太弱', color: 'var(--destructive)', pct: 25 },
    { label: '弱', color: 'oklch(0.70 0.15 65)', pct: 50 },
    { label: '中', color: 'oklch(0.70 0.14 90)', pct: 75 },
    { label: '强', color: 'var(--success, oklch(0.62 0.18 145))', pct: 100 },
  ];
  return map[Math.min(score, 4) - 1] ?? map[0];
}

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const strength = password ? passwordStrength(password) : null;

  const submit = async () => {
    setError('');
    if (!email.trim() || !password || !displayName.trim()) { setError('请填写完整信息'); return; }
    if (password.length < 8) { setError('密码至少 8 位'); return; }
    if (password !== confirm) { setError('两次密码不一致'); return; }

    setLoading(true);
    try {
      if (USE_MOCK) {
        login('mock-token', { id: 'mock-user', email, display_name: displayName });
        router.push('/');
        return;
      }
      const res = await authApi.register(email.trim(), password, displayName.trim());
      // 注册成功直接拿 token 自动登录
      login(res.token, res.user);
      router.push('/');
    } catch (e: unknown) {
      const status = (e as { message?: string })?.message ?? '';
      if (status.includes('409')) setError('该邮箱已被注册,请直接登录');
      else if (status.includes('422')) setError('信息校验失败,请检查邮箱格式和密码强度');
      else setError('注册失败,请稍后重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="hevi-auth">
      <div className="hevi-auth__card">
        <h1 className="hevi-auth__title">注册 hevi</h1>
        <p className="hevi-auth__subtitle">创建账号,开始 AI 视频创作</p>

        <div className="hevi-auth__fields">
          <label className="hevi-auth__field">
            <span>邮箱</span>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)}
              placeholder="your@email.com" autoComplete="email" />
          </label>

          <label className="hevi-auth__field">
            <span>昵称</span>
            <input type="text" value={displayName} onChange={e => setDisplayName(e.target.value)}
              placeholder="怎么称呼你" autoComplete="nickname" />
          </label>

          <label className="hevi-auth__field">
            <span>密码</span>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)}
              placeholder="至少 8 位" autoComplete="new-password" />
            {strength && (
              <div className="hevi-auth__strength">
                <div className="hevi-auth__strength-bar">
                  <div style={{ width: `${strength.pct}%`, background: strength.color }} />
                </div>
                <span style={{ color: strength.color }}>{strength.label}</span>
              </div>
            )}
          </label>

          <label className="hevi-auth__field">
            <span>确认密码</span>
            <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)}
              placeholder="再次输入密码" autoComplete="new-password"
              onKeyDown={e => { if (e.key === 'Enter') submit(); }} />
            {confirm && confirm !== password && (
              <span className="hevi-auth__hint-error">两次密码不一致</span>
            )}
          </label>
        </div>

        {error && <div className="hevi-auth__error">{error}</div>}

        <button className="hevi-auth__submit" onClick={submit} disabled={loading}>
          {loading ? '注册中…' : '注册并登录'}
        </button>

        <p className="hevi-auth__footer">
          已有账号？<a href="/login">去登录</a>
        </p>
      </div>
    </div>
  );
}
