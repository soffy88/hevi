'use client';
import { TopNav } from '@/components/TopNav';
import { SeasonBoard } from '@/components/season/SeasonBoard';

export default function SeasonBoardPage() {
  return (
    <>
      <TopNav />
      <main className="hevi-series-page">
        <SeasonBoard />
      </main>
    </>
  );
}
