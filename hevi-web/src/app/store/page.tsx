'use client';
import { TopNav } from '@/components/TopNav';
import { StorefrontGallery } from '@/components/store3d/StorefrontGallery';

export default function StorePage() {
  return (
    <>
      <TopNav />
      <main>
        <StorefrontGallery />
      </main>
    </>
  );
}
