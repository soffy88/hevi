'use client';
import { TopNav } from '@/components/TopNav';
import { TongjianConsole } from '@/components/director/TongjianConsole';

export default function TongjianPage() {
  return (
    <>
      <TopNav />
      <main className="hevi-tongjian-page">
        <TongjianConsole />
      </main>
    </>
  );
}
