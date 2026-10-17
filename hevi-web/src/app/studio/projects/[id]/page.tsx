'use client';

import { useParams } from 'next/navigation';
import { RequireAuth } from '@/components/RequireAuth';
import { TopNav } from '@/components/TopNav';
import { DirectorWorkbench } from '@/components/workbench/DirectorWorkbench';

export default function DirectorWorkbenchPage() {
  const params = useParams<{ id: string }>();
  return <>
    <TopNav />
    <RequireAuth>
      <DirectorWorkbench projectId={params.id} />
    </RequireAuth>
  </>;
}
