import { CreateEntry } from '@/components/create/CreateEntry';
import { RequireAuth } from '@/components/RequireAuth';
import { TopNav } from '@/components/TopNav';

export const metadata = { title: '创作 · HEVI' };

export default function Page() {
  return (
    <>
      <TopNav />
      <RequireAuth>
        <main className="product-page product-page--create">
          <CreateEntry />
        </main>
      </RequireAuth>
    </>
  );
}
