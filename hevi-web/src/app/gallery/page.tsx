'use client';
import { TopNav } from '@/components/TopNav';
import { ShowcaseWall } from '@/components/gallery/ShowcaseWall';

export default function GalleryPage() {
  return (
    <>
      <TopNav />
      <main className="hevi-showcase-page">
        <ShowcaseWall />
      </main>
    </>
  );
}
