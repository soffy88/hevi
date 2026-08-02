'use client';

import { TopNav } from '@/components/TopNav';
import { RequireAuth } from '@/components/RequireAuth';
import { ClipperConsole } from '@/components/studio/ClipperConsole';

export default function ClipperPage() {
  return (
    <>
      <TopNav />
      <RequireAuth>
        <ClipperConsole />
      </RequireAuth>
    </>
  );
}
