import { RequireAuth } from '@/components/RequireAuth';
import { ScriptDoctor } from '@/components/ScriptDoctor';
import { TopNav } from '@/components/TopNav';

export const metadata = { title: '剧本门诊 · HEVI' };

export default function Page() {
  return (
    <>
      <TopNav />
      <RequireAuth>
        <main className="product-page">
          <ScriptDoctor />
        </main>
      </RequireAuth>
    </>
  );
}
