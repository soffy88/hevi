import Link from 'next/link';

/**
 * 全站页脚：只放稳定、公开的入口。
 */
export function SiteFooter() {
  return (
    <footer className="hevi-site-footer">
      <span>© {new Date().getFullYear()} hevi</span>
      <nav aria-label="法律与政策">
        <Link href="/privacy">隐私政策</Link>
        <Link href="/terms">用户协议</Link>
        <Link href="/acknowledgements">致谢</Link>
      </nav>
      <span className="hevi-site-footer__note">© 微亚人工智能有限公司 · ceo@aiinote.com</span>
    </footer>
  );
}
