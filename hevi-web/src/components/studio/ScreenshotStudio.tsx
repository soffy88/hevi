'use client';

import { useEffect, useState } from 'react';
import { screenshotStudioApi } from '@/lib/api-client';

type Project = { project_id: string; title: string; frame: string; width: number; height: number; duration_s?: number; version?: number };

export function ScreenshotStudio() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [title, setTitle] = useState('产品功能展示');
  const [source, setSource] = useState('');
  const [frame, setFrame] = useState('browser');
  const [background, setBackground] = useState('#eef2ff');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const load = () => void screenshotStudioApi.projects().then((res) => setProjects(res.projects as Project[])).catch((e: unknown) => setMessage(e instanceof Error ? e.message : '加载失败'));
  useEffect(load, []);

  const create = async () => {
    setBusy(true); setMessage('');
    try { await screenshotStudioApi.create({ title, screenshot_path: source, frame, background }); setMessage('截图项目已创建'); load(); }
    catch (e) { setMessage(e instanceof Error ? e.message : '创建失败'); }
    finally { setBusy(false); }
  };

  const exportProject = async (id: string) => {
    setBusy(true);
    try { const result = await screenshotStudioApi.export(id); setMessage(`已导出：${String(result.output_path ?? '')}`); }
    catch (e) { setMessage(e instanceof Error ? e.message : '导出失败'); }
    finally { setBusy(false); }
  };

  return (
    <main style={{ maxWidth: 1100, margin: '0 auto', padding: '30px 16px' }}>
      <header style={{ marginBottom: 20 }}><p style={{ color: 'var(--primary)', fontWeight: 800, fontSize: 12 }}>SCREENSHOT STUDIO</p><h1 style={{ margin: 0 }}>产品截图合成器</h1><p style={{ color: 'var(--muted-foreground)' }}>浏览器/设备外框、背景和标注先形成可审项目，再导出静态宣传素材。</p></header>
      <section style={{ display: 'grid', gap: 12, padding: 22, border: '1px solid var(--border)', borderRadius: 14, background: 'var(--card)' }}>
        <label>项目名称<input value={title} onChange={(e) => setTitle(e.target.value)} style={{ display: 'block', width: '100%', marginTop: 6, padding: 10 }} /></label>
        <label>本地截图路径<input value={source} onChange={(e) => setSource(e.target.value)} placeholder="/absolute/path/product.png" style={{ display: 'block', width: '100%', marginTop: 6, padding: 10 }} /></label>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <label>外框<select value={frame} onChange={(e) => setFrame(e.target.value)} style={{ display: 'block', marginTop: 6, padding: 10 }}><option value="browser">Browser</option><option value="safari">Safari</option><option value="phone">Phone</option><option value="laptop">Laptop</option><option value="plain">Plain</option></select></label>
          <label>背景<input type="color" value={background} onChange={(e) => setBackground(e.target.value)} style={{ display: 'block', marginTop: 6, width: 80, height: 40 }} /></label>
        </div>
        <button type="button" onClick={create} disabled={busy || !title} style={{ width: 'fit-content', padding: '10px 16px' }}>创建项目</button>
        {message && <p style={{ margin: 0, color: 'var(--muted-foreground)' }}>{message}</p>}
      </section>
      <section style={{ display: 'grid', gap: 10, marginTop: 20 }}>
        {projects.map((project) => <article key={project.project_id} style={{ padding: 16, border: '1px solid var(--border)', borderRadius: 12, background: 'var(--card)' }}><strong>{project.title}</strong><span style={{ marginLeft: 10, fontSize: 12, color: 'var(--muted-foreground)' }}>{project.frame} · {project.width}×{project.height} · v{project.version}</span><button type="button" onClick={() => void exportProject(project.project_id)} disabled={busy} style={{ float: 'right', padding: '6px 10px' }}>导出 PNG</button></article>)}
        {projects.length === 0 && <p style={{ color: 'var(--muted-foreground)' }}>暂无截图项目。</p>}
      </section>
    </main>
  );
}
