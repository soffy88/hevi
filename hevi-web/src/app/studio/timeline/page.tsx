'use client';

import { TopNav } from '@/components/TopNav';
import { TimelineEditor } from '@/components/studio/TimelineEditor';

export default function TimelinePage() {
  return (
    <>
      <TopNav />
      <main>
        <TimelineEditor />
      </main>
    </>
  );
}
