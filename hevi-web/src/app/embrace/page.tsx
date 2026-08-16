'use client';
import { TopNav } from '@/components/TopNav';
import { EmbraceGallery } from '@/components/embrace/EmbraceGallery';

export default function EmbracePage() {
  return (
    <>
      <TopNav />
      <main className="hevi-embrace-page">
        <EmbraceGallery />
      </main>
    </>
  );
}
