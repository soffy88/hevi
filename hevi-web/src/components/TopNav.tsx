'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth-store';


/* ── 扁平导航（无二级菜单）── */
const NAV: { href: string; label: string }[] = [
  { href: '/director',           label: '导演台' },
  { href: '/director-pipeline', label: '导演流水线' },
  { href: '/tongjian',          label: '通鉴' },
  { href: '/season-board',      label: '短剧' },
  { href: '/production-tools',  label: '制片工具' },
  { href: '/pro-studio',        label: '专业工作室' },
  { href: '/publish-studio',    label: '发布工作室' },
  { href: '/voice-studio',      label: '语音工作室' },
  { href: '/ai-models',         label: 'AI模型' },
  { href: '/gallery',           label: '画廊' },
  { href: '/pricing',           label: '定价' },
  { href: '/account',           label: '账户' },
  { href: '/explainer',         label: '代码解释器' },
  { href: '/series',            label: '项目' },
  { href: '/settings',          label: '设置' },
];

const LOGO = '/brand/hevi-logo.svg';

export function TopNav() {
  const { user, logout, initialized } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const handleLogout = () => { logout(); router.push('/login'); };

  return (
    <nav className="hevi-topnav">
      <div className="hevi-topnav__bar">
        {/* ── 左区 ── */}
        <Link href="/" className="hevi-topnav__brand">
          <img src={LOGO} alt="hevi" className="hevi-topnav__logo" width={28} height={28} />
          <span>hevi</span>
        </Link>

        {/* ── 导航项（扁平一行）── */}
        <div className="hevi-topnav__links">
          {NAV.map(n => (
            <Link
              key={n.href}
              href={n.href}
              data-active={pathname === n.href || pathname.startsWith(n.href + '/')}
              className="hevi-topnav__link"
            >
              {n.label}
            </Link>
          ))}
        </div>

        {/* ── 右区 ── */}
        <div className="hevi-topnav__right">
          {!initialized ? (
            <span className="hevi-topnav__placeholder" />
          ) : user ? (
            <>
              <span className="hevi-topnav__user">
                {user.display_name || user.email}
              </span>
              <button onClick={handleLogout} className="hevi-topnav__btn">
                登出
              </button>
            </>
          ) : (
            <>
              <Link href="/login"    className="hevi-topnav__btn">登录</Link>
              <Link href="/register" className="hevi-topnav__btn hevi-topnav__btn--accent">注册</Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
