'use client';
import { TopNav } from '@/components/TopNav';
import { LiteWorkbench } from '@/components/lite/LiteWorkbench';

export default function LitePage() {
  return (
    <>
      <TopNav />
      <main className="hevi-dashboard-page">
        <LiteWorkbench />
      </main>
    </>
  );
}
