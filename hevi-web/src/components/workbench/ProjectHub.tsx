'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { canonicalProductionApi } from '@/lib/api-client';
import type { ProductionProject } from '@/types/api';

export function ProjectHub() {
  const [projects, setProjects] = useState<ProductionProject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { canonicalProductionApi.list().then(result => setProjects(result.projects)).catch(cause => setError(cause instanceof Error ? cause.message : '无法加载项目')).finally(() => setLoading(false)); }, []);
  return <main className="wb-hub"><div className="wb-hub-head"><div><span className="wb-eyebrow">STUDIO / PROJECTS</span><h1>Production projects</h1><p>从持久化 canonical project 进入 Director Workbench。</p></div><Link className="wb-primary-btn" href="/studio/one-prompt">+ One Prompt</Link></div>{loading && <p className="wb-muted">读取项目…</p>}{error && <div className="wb-inline-error">{error}</div>}<div className="wb-project-grid">{projects.map(project => <Link className="wb-project-card" key={project.id} href={`/studio/projects/${project.id}`}><div className="wb-project-card-top"><span className="wb-project-type">{project.source_kind}</span><span className="wb-status">{project.status}</span></div><h2>{project.title}</h2><p>{project.creative_brief || 'No creative brief yet.'}</p><footer><span>{project.production_mode}</span><code>{project.current_revision_id?.slice(0, 8) ?? '—'}</code></footer></Link>)}{!loading && !projects.length && <div className="wb-empty-panel">暂无项目。使用 One Prompt 创建第一个 production。</div>}</div></main>;
}
