import { SimpleGenerate } from '@/components/home/SimpleGenerate';
import { TopNav } from '@/components/TopNav';
import { RequireAuth } from '@/components/RequireAuth';

export default function Page() {
  return (
    <>
      <TopNav />
      <RequireAuth>
        <main className="product-page product-page--creation">
          <div className="product-page__intro">
            <p className="product-page__eyebrow">HEVI 创作空间</p>
            <h1>把一个想法，变成一支完整视频</h1>
            <p>从创意、故事和分镜开始，沿着真实生产流程完成成片。</p>
          </div>
          <SimpleGenerate />
        </main>
      </RequireAuth>
    </>
  );
}
