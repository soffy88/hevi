/**
 * TopNav — 顶部导航栏(§2 IA)
 * 首页/生成 · 画布工作台 · 主体库 · 我的 · 价格
 */
'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

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
      </nav>
    </header>
  );
}
