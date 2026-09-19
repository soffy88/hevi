'use client';

/**
 * D6 product workspace: project health, character library, production issues,
 * continuity + memory. All panels consume canonical authorities.
 */
import { useState } from 'react';
import { TopNav } from '@/components/TopNav';
import { RequireAuth } from '@/components/RequireAuth';
import { TabBar } from '@/components/shared/TabBar';
import { QuickStart } from '@/components/onboarding/QuickStart';
import { ProjectHealthPanel } from '@/components/production/ProjectHealthPanel';
import { CharacterLibrary } from '@/components/characters/CharacterLibrary';
import { ProductionIssuesPanel } from '@/components/repair/ProductionIssuesPanel';
import { ContinuityCheckPanel } from '@/components/continuity/ContinuityCheckPanel';
import { ProductMetricsPanel } from '@/components/production/ProductMetricsPanel';

const TABS = ['制作状态', '角色库', '制作问题', '连续性', '创作数据'] as const;
type Tab = (typeof TABS)[number];

export default function WorkspacePage() {
  const [tab, setTab] = useState<Tab>('制作状态');
  const [projectId, setProjectId] = useState('');

  return (
    <>
      <TopNav />
      <RequireAuth>
        <main className="hevi-workspace-page">
          <label className="workspace-project">
            当前项目 ID
            <input
              aria-label="当前项目 ID"
              value={projectId}
              onChange={e => setProjectId(e.target.value)}
              placeholder="选择或输入项目"
            />
          </label>
          <TabBar
            items={TABS.map(t => ({ key: t, label: t }))}
            active={tab}
            onChange={t => setTab(t as Tab)}
          />
          <div role="tabpanel">
            {tab === '制作状态' &&
              (projectId ? (
                <ProjectHealthPanel projectId={projectId} />
              ) : (
                <QuickStart onDemoProject={setProjectId} />
              ))}
            {tab === '角色库' && <CharacterLibrary projectId={projectId} />}
            {tab === '制作问题' && <ProductionIssuesPanel productionRunId={projectId} />}
            {tab === '连续性' && projectId && <ContinuityCheckPanel projectId={projectId} />}
            {tab === '连续性' && !projectId && <p>请先选择项目。</p>}
            {tab === '创作数据' && <ProductMetricsPanel />}
          </div>
        </main>
      </RequireAuth>
    </>
  );
}
