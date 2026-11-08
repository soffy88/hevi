import Link from 'next/link';

/**
 * 全站页脚：只放稳定、公开的入口。法律法规页当前为草案，页面上会明确标注。
 */
export function SiteFooter() {
  return (
    <footer className="hevi-site-footer">
      <span>© {new Date().getFullYear()} hevi</span>
      <nav aria-label="法律与政策">
        <Link href="/privacy">隐私政策</Link>
        <Link href="/terms">用户协议</Link>
      </nav>
      <span className="hevi-site-footer__note">法律文本为草案，待运营方确认</span>
    </footer>
  );
}
