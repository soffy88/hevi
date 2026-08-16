'use client';
import { TopNav } from '@/components/TopNav';
import { TongjianConsole } from '@/components/director/TongjianConsole';

export default function TongjianPage() {
  return (
    <>
      <TopNav />
      <main className="hevi-tongjian-page">
        <div className="mx-auto flex max-w-6xl justify-end px-4 pt-4">
          <a
            href="/animate"
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow hover:bg-blue-500"
          >
            🎬 儿童动画演绎
          </a>
        </div>
        <TongjianConsole />
      </main>
    </>
  );
}
