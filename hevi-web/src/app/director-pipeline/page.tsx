'use client';
import { TopNav } from '@/components/TopNav';
import { DirectorPipelineConsole } from '@/components/director/DirectorPipelineConsole';

export default function DirectorPipelinePage() {
  return (
    <>
      <TopNav />
      <main className="hevi-director-pipeline-page">
        <DirectorPipelineConsole />
      </main>
    </>
  );
}
