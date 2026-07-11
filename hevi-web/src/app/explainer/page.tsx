'use client';
import { TopNav } from '@/components/TopNav';
import { ExplainerConsole } from '@/components/director/ExplainerConsole';

export default function ExplainerPage() {
  return (
    <>
      <TopNav />
      <main className="hevi-explainer-page">
        <ExplainerConsole />
      </main>
    </>
  );
}
