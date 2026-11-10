import { RequireAuth } from '@/components/RequireAuth';
import { AnidoodleStudio } from '@/components/AnidoodleStudio';
import { TopNav } from '@/components/TopNav';

export const metadata = { title: '手绘代码风格库 · HEVI' };

export default function Page() {
  return (
    <>
      <TopNav />
      <RequireAuth>
        <main className="product-page">
          <AnidoodleStudio />
        </main>
      </RequireAuth>
    </>
  );
}
