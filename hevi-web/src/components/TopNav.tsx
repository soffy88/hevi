/**
 * TopNav — 顶部导航栏(Frontend SPEC v6.0 §4 最终精简导航)
 * 6 个职责绝对清晰的主节点:
 *   / ⚡极速生成 · /explainer 🎙️解说中心 · /tongjian 🏛️历史现场 ·
 *   /director-pipeline 🎬导演流水线 · /director 🎛️导演控制台 · /production 📊生产看板
 * 辅助工具(✂️智能拆条 / 👤数字人预设 / 🔊语音工作室 / 📁数字资产)收纳在「工具箱 ▾」弹层,
 * 次要工作台(系列/短剧台/画布/发布/我的/价格)收纳在「更多 ▾」折叠。
 * 登录入口:未登录显示「登录」,已登录显示「退出」。
 */
'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { isAuthenticated, logout } from '@/lib/auth-store';

const NAV = [
  { href: '/', label: '⚡ 极速生成' },
  { href: '/explainer', label: '🎙️ 解说中心' },
  { href: '/lite', label: '⚡ 轻量发射台' },
  { href: '/dashboard', label: '📊 任务大盘' },
  { href: '/tongjian', label: '🏛️ 历史现场' },
  { href: '/animate', label: '🎬 动画演绎' },
  { href: '/director-pipeline', label: '🎬 导演流水线' },
  { href: '/director', label: '🎛️ 导演控制台' },
  { href: '/production', label: '📊 生产看板' },
];

const TOOLBOX = [
  { href: '/embrace', label: '🎴 配方卡画廊' },
  { href: '/studio/clipper', label: '✂️ 智能拆条' },
  { href: '/presenters', label: '👤 数字人预设' },
  { href: '/voice-studio', label: '🔊 语音工作室' },
  { href: '/gallery', label: '📁 数字资产' },
  { href: '/store', label: '📼 3D 店面' },
  { href: '/studio/timeline', label: '🎞️ 时间线' },
];

const MORE = [
  { href: '/series', label: '系列' },
  { href: '/season-board', label: '短剧台' },
  { href: '/studio', label: '画布工作台' },
  { href: '/publish-studio', label: '发布工作室' },
  { href: '/account', label: '我的' },
  { href: '/pricing', label: '价格' },
];

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const [authed, setAuthed] = useState(false);
  const [toolboxOpen, setToolboxOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  useEffect(() => { setAuthed(isAuthenticated()); }, [pathname]);

  const isActive = (href: string) =>
    href === '/' ? pathname === '/' : pathname.startsWith(href);

  return (
    <header className="hevi-topnav">
      <Link href="/" className="hevi-topnav__logo">hevi</Link>
      <nav className="hevi-topnav__links">
        {NAV.map(n => (
          <Link key={n.href} href={n.href}
            className="hevi-topnav__link" data-active={isActive(n.href) ? 'true' : undefined}>
            {n.label}
          </Link>
        ))}
        <div className="hevi-topnav__more">
          <button type="button" className="hevi-topnav__link hevi-topnav__link--btn"
            data-active={TOOLBOX.some(m => isActive(m.href)) ? 'true' : undefined}
            onClick={() => { setToolboxOpen(v => !v); setMoreOpen(false); }}>
            工具箱 ▾
          </button>
          {toolboxOpen && (
            <div className="hevi-topnav__more-menu">
              {TOOLBOX.map(m => (
                <Link key={m.href} href={m.href}
                  className="hevi-topnav__more-item" data-active={isActive(m.href) ? 'true' : undefined}
                  onClick={() => setToolboxOpen(false)}>
                  {m.label}
                </Link>
              ))}
            </div>
          )}
        </div>
        <div className="hevi-topnav__more">
          <button type="button" className="hevi-topnav__link hevi-topnav__link--btn"
            data-active={MORE.some(m => isActive(m.href)) ? 'true' : undefined}
            onClick={() => { setMoreOpen(v => !v); setToolboxOpen(false); }}>
            更多 ▾
          </button>
          {moreOpen && (
            <div className="hevi-topnav__more-menu">
              {MORE.map(m => (
                <Link key={m.href} href={m.href}
                  className="hevi-topnav__more-item" data-active={isActive(m.href) ? 'true' : undefined}
                  onClick={() => setMoreOpen(false)}>
                  {m.label}
                </Link>
              ))}
            </div>
          )}
        </div>
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
