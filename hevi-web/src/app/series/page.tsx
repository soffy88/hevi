'use client';
import { TopNav } from '@/components/TopNav';
import { SeriesManager } from '@/components/series/SeriesManager';

export default function SeriesPage() {
  return (
    <>
      <TopNav />
      <main className="hevi-series-page">
        <SeriesManager />
      </main>
    </>
  );
}
