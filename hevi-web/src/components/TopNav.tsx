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

const NAV = [
  { href: '/studio', label: '创作' },
  { href: '/projects', label: '项目' },
  { href: '/assets', label: '素材' },
  { href: '/analysis', label: '视频分析' },
  { href: '/settings', label: '设置' },
];

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [authed, setAuthed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);

  useEffect(() => { setAuthed(isAuthenticated()); }, [pathname]);
  // 路由变化时关闭 drawer
  useEffect(() => { setDrawerOpen(false); }, [pathname]);

  const isActive = (href: string) =>
    href === '/' ? pathname === '/' : pathname.startsWith(href);

  return (
    <header className="hevi-topnav">
      <Link href="/studio" className="hevi-topnav__logo">HEVI</Link>

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
        {authed ? (
          <div className="hevi-topnav__profile">
            <button type="button" className="hevi-topnav__avatar" aria-label="打开用户菜单"
              aria-expanded={profileOpen} onClick={() => setProfileOpen(v => !v)}>我</button>
            {profileOpen && (
              <div className="hevi-topnav__profile-menu" role="menu">
                <Link href="/account" className="hevi-topnav__profile-item" role="menuitem">账户</Link>
                <Link href="/settings" className="hevi-topnav__profile-item" role="menuitem">设置</Link>
                <button type="button" className="hevi-topnav__profile-item" role="menuitem"
                  onClick={() => { logout(); setAuthed(false); setProfileOpen(false); router.push('/login'); }}>
                  退出登录
                </button>
              </div>
            )}
          </div>
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
