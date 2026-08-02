'use client';
import { TopNav } from '@/components/TopNav';
import { ExplainerWorkbench } from '@/components/director/ExplainerWorkbench';

export default function ExplainerPage() {
  return (
    <>
      <TopNav />
      <main className="hevi-explainer-page">
        <ExplainerWorkbench />
      </main>
    </>
  );
}
