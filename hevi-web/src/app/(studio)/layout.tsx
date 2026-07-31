'use client';

import { TopNav } from '@/components/TopNav';
import { RequireAuth } from '@/components/RequireAuth';

export default function StudioLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <TopNav />
      <RequireAuth>{children}</RequireAuth>
    </>
  );
}
