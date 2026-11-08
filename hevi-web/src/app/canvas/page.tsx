import { HeviCanvas } from '@/components/canvas/HeviCanvas';
import { RequireAuth } from '@/components/RequireAuth';
import { TopNav } from '@/components/TopNav';

export const metadata = { title: '画布工作台 · HEVI' };

export default function Page() {
  return (
    <>
      <TopNav />
      <RequireAuth>
        <main className="product-page product-page--canvas">
          <div className="product-page__intro">
            <p className="product-page__eyebrow">HEVI 画布</p>
            <h1>每一步都看得见，只重做要改的那一步</h1>
            <p>
              新建一张口播默认图，或导入材料包；节点显示绿/黄/红自检状态，
              选中节点可单点重做并自动顺跑下游。
            </p>
          </div>
          <HeviCanvas />
        </main>
      </RequireAuth>
    </>
  );
}
