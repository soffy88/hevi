import { TopNav } from '@/components/TopNav';
import { RequireAuth } from '@/components/RequireAuth';
import { StyleLibraryBrowser } from '@/components/style/StyleLibraryBrowser';

export const metadata = { title: '风格库 · HEVI' };

export default function Page() {
  return (
    <>
      <TopNav />
      <RequireAuth>
        <main className="product-page product-page--styles">
          <div className="product-page__intro">
            <p className="product-page__eyebrow">风格库 · 370 种视觉风格 / 170 种排版 / 36 主题色</p>
            <h1>选一个编号，整片锁定同一画风</h1>
            <p>
              按编号、名称或类别搜索；选中后只重做受影响的画面节点。
              主题色与排版图型可一起锁定，关键帧漂移会自动标出。
            </p>
          </div>
          <StyleLibraryBrowser />
          <p className="style-lib__attr">
            风格库来自 <a href="https://github.com/yang0/handraw-style" target="_blank" rel="noopener noreferrer">yang0/handraw-style</a>
            （MIT License + 署名要求）。预览由 HEVI 自绘，不使用上游样图。
          </p>
        </main>
      </RequireAuth>
    </>
  );
}
