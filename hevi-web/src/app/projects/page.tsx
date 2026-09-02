/**
 * Projects page - P2: Projects Information Architecture
 * 
 * Shows user's projects with filtering and actions
 * Reuses existing TaskDashboard and ProductionConsole components
 */
'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { TaskDashboard } from '@/components/dashboard/TaskDashboard';
import { ProductionConsole } from '@/components/production/ProductionConsole';

export default function ProjectsPage() {
  const pathname = usePathname();

  const tab = pathname.includes('/projects/active')
    ? '进行中'
    : pathname.includes('/projects/completed')
    ? '已完成'
    : pathname.includes('/projects/pending')
    ? '需处理'
    : pathname.includes('/projects/failed')
    ? '失败'
    : '全部';

  return (
    <div className="projects-page">
      <header className="projects-page__header">
        <h1 className="projects-page__title">项目</h1>
        <nav className="projects-page__tabs">
          <Link href="/projects" 
            className={`projects-page__tab ${tab === '全部' ? 'projects-page__tab--active' : ''}`}>
            全部
          </Link>
          <Link href="/projects/active" 
            className={`projects-page__tab ${tab === '进行中' ? 'projects-page__tab--active' : ''}`}>
            进行中
          </Link>
          <Link href="/projects/completed" 
            className={`projects-page__tab ${tab === '已完成' ? 'projects-page__tab--active' : ''}`}>
            已完成
          </Link>
          <Link href="/projects/pending" 
            className={`projects-page__tab ${tab === '需处理' ? 'projects-page__tab--active' : ''}`}>
            需处理
          </Link>
          <Link href="/projects/failed" 
            className={`projects-page__tab ${tab === '失败' ? 'projects-page__tab--active' : ''}`}>
            失败
          </Link>
        </nav>
      </header>

      {/* 根据路径决定显示哪种视图 */}
      {pathname.includes('/projects/') && !pathname.startsWith('/projects/') ? (
        <ProjectDetail />
      ) : (
        <div className="projects-page__content">
          <TaskDashboard />
          <ProductionConsole />
        </div>
      )}
    </div>
  );
}

function ProjectDetail() {
  // Stub - actual implementation in /projects/[id]/page.tsx
  return (
    <div className="projects-page__project-detail">
      <p>请从项目列表选择一个项目查看详情</p>
    </div>
  );
}