'use client';
import { TopNav } from '@/components/TopNav';
import { DirectorConsole } from '@/components/director/DirectorConsole';

export default function DirectorPage() {
  return (
    <>
      <TopNav />
      <main className="hevi-director-page">
        <DirectorConsole />
      </main>
    </>
  );
}
