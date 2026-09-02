/**
 * TopNav — 顶部导航栏 (HEVI Frontend UX + Connectivity Closure SPEC v1.0)
 *
 * 一级导航 (P1 简化后):
 *   创建 (/) | 项目 (/projects) | 资产 (/assets) | 工作室 (/studio) | 我的 (/account)
 *
 * 移动端: 折叠为抽屉式导航(drawer/bottom nav),防止横向溢出。
 * 状态指示: ● Online / ● Offline,点击展开 SystemStatus 详情。
 */
'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { isAuthenticated, logout } from '@/lib/auth-store';
import { checkBackendHealth } from '@/lib/backend-health';
import { SystemStatus } from '@/components/SystemStatus';
import { useBackendStatus } from '@/hooks/useBackendStatus';

const NAV = [
  { href: '/', label: '创建' },
  { href: '/projects', label: '项目' },
  { href: '/assets', label: '资产' },
  { href: '/studio', label: '工作室' },
  { href: '/account', label: '我的' },
];

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [authed, setAuthed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // 实时后端连接状态(只显示 "Online / Offline" 文本指示,具体细节在 SystemStatus)
  const { online, checking, recheck } = useBackendStatus();

  useEffect(() => { setAuthed(isAuthenticated()); }, [pathname]);
  // 路由变化时关闭 drawer
  useEffect(() => { setDrawerOpen(false); }, [pathname]);

  const isActive = (href: string) =>
    href === '/' ? pathname === '/' : pathname.startsWith(href);

  return (
    <header className="hevi-topnav" data-state={online ? 'online' : 'offline'}>
      <Link href="/" className="hevi-topnav__logo">HEVI</Link>

      {/* 桌面端导航 */}
      <nav className="hevi-topnav__links hevi-topnav__links--desktop">
        {NAV.map(n => (
          <Link key={n.href} href={n.href}
            className="hevi-topnav__link"
            data-active={isActive(n.href) ? 'true' : undefined}>
            {n.label}
          </Link>
        ))}
      </nav>

      <div className="hevi-topnav__right">
        {/* 连接状态指示(可点击展开) */}
        <button type="button"
          className="hevi-topnav__status-pill"
          data-state={online ? 'online' : 'offline'}
          onClick={recheck}
          disabled={checking}
          title={online ? '后端已连接' : '后端未连接,点击重试'}>
          <span className={`hevi-topnav__dot ${online ? 'hevi-topnav__dot--online' : 'hevi-topnav__dot--offline'}`}
            aria-hidden="true" />
          <span className="hevi-topnav__status-text">
            {checking ? '检测中' : online ? 'Online' : 'Offline'}
          </span>
        </button>

        {/* System Status (展开连接详情) */}
        <SystemStatus />

        {authed ? (
          <button type="button" className="hevi-topnav__link hevi-topnav__link--auth hevi-topnav__link--btn"
            onClick={() => { logout(); setAuthed(false); router.push('/login'); }}>
            退出
          </button>
        ) : (
          <Link href="/login" className="hevi-topnav__link hevi-topnav__link--auth"
            data-active={pathname.startsWith('/login') ? 'true' : undefined}>
            登录
          </Link>
        )}

        {/* 移动端汉堡菜单按钮 */}
        <button type="button"
          className="hevi-topnav__hamburger"
          aria-label="打开菜单"
          onClick={() => setDrawerOpen(v => !v)}>
          <span></span><span></span><span></span>
        </button>
      </div>

      {/* 移动端 drawer */}
      {drawerOpen && (
        <div className="hevi-topnav__drawer" role="navigation" aria-label="移动端导航">
          {NAV.map(n => (
            <Link key={n.href} href={n.href}
              className="hevi-topnav__drawer-link"
              data-active={isActive(n.href) ? 'true' : undefined}
              onClick={() => setDrawerOpen(false)}>
              {n.label}
            </Link>
          ))}
        </div>
      )}
    </header>
  );
}
