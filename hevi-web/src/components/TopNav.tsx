/**
 * TopNav — 顶部导航栏(§2 IA)
 * 首页/生成 · 画布工作台 · 主体库 · 我的 · 价格
 *
 * 登录入口(2026-07-13 修复):此前整个导航栏没有任何"登录"链接——需登录的页面
 * (导演/通鉴/系列/短剧/画布工作台等)都没被 RequireAuth 包裹,允许未登录用户
 * 一路填完表单,直到点提交才撞见 authedReq 抛的 NOT_AUTHENTICATED,而这个应用
 * 压根没地方能点进去登录。这里加一个根据登录态切换的入口:未登录显示"登录",
 * 已登录显示"退出"(此前也没有任何登出入口)。
 */
'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { isAuthenticated, logout } from '@/lib/auth-store';

const NAV = [
  { href: '/', label: '生成' },
  { href: '/director', label: '导演' },
  { href: '/tongjian', label: '通鉴' },
  { href: '/explainer', label: '解说' },
  { href: '/series', label: '系列' },
  { href: '/season-board', label: '短剧' },
  { href: '/studio', label: '画布工作台' },
  { href: '/gallery', label: '展示墙' },
  { href: '/account', label: '我的' },
  { href: '/pricing', label: '价格' },
];

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  // 首屏(SSR/hydration 前)读不到 localStorage,统一先当未登录渲染,挂载后再
  // 校正——跟 RequireAuth 同样的处理方式,避免 hydration 报警。
  const [authed, setAuthed] = useState(false);
  useEffect(() => { setAuthed(isAuthenticated()); }, [pathname]);

  return (
    <header className="hevi-topnav">
      <Link href="/" className="hevi-topnav__logo">hevi</Link>
      <nav className="hevi-topnav__links">
        {NAV.map(n => {
          const active = n.href === '/' ? pathname === '/' : pathname.startsWith(n.href);
          return (
            <Link key={n.href} href={n.href}
              className="hevi-topnav__link" data-active={active ? 'true' : undefined}>
              {n.label}
            </Link>
          );
        })}
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
      </nav>
    </header>
  );
}
