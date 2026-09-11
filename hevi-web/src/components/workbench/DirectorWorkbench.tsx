'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { assetApi, canonicalProductionApi as productionApi, studioApi } from '@/lib/api-client';
import type {
  ProductionDirectorDecision,
  ProductionGraphSnapshot,
  ProductionShot,
  ReadinessState,
  RevisionPatchOperation,
} from '@/types/api';

type Tab = 'story' | 'storyboard' | 'canvas' | 'timeline' | 'assets' | 'qa';

const tabs: Array<{ id: Tab; label: string; icon: string }> = [
  { id: 'story', label: '故事', icon: '✦' },
  { id: 'storyboard', label: '分镜', icon: '▦' },
  { id: 'canvas', label: '画布', icon: '⌘' },
  { id: 'timeline', label: '时间线', icon: '◷' },
  { id: 'assets', label: '资产', icon: '◇' },
  { id: 'qa', label: '质量', icon: '✓' },
];

const statusLabels: Record<string, string> = {
  DRAFT: '草稿', ANALYZED: '已分析', ASSETS_PENDING: '等待资产',
  REFERENCES_PENDING: '等待参考', PREFLIGHT_FAILED: '预检失败', READY: '就绪',
  QUEUED: '排队中', GENERATING: '生成中', GENERATED: '已生成', QA_FAILED: '质检失败',
  QA_PASSED: '质检通过', APPROVED: '已批准', LOCKED: '已锁定',
};

function shortId(value?: string | null) { return value ? value.slice(0, 8) : '—'; }

export function DirectorWorkbench({ projectId }: { projectId: string }) {
  const [snapshot, setSnapshot] = useState<ProductionGraphSnapshot | null>(null);
  const [tab, setTab] = useState<Tab>('storyboard');
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null);
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [directorText, setDirectorText] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<ProductionDirectorDecision[]>([]);
  const [tasks, setTasks] = useState<Array<Record<string, unknown>>>([]);
  const [revisionHistory, setRevisionHistory] = useState<ProductionGraphSnapshot['revision'][]>([]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await productionApi.get(projectId);
      setSnapshot(next);
      setSelectedShotId(current => current && next.shots.some(item => item.id === current) ? current : next.shots[0]?.id ?? null);
      setSelectedSceneId(current => current && next.scenes.some(item => item.id === current) ? current : next.scenes[0]?.id ?? null);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '无法加载 canonical production project');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void refresh(); }, [refresh]);
  useEffect(() => { productionApi.tasks().then(result => setTasks(result.tasks)).catch(() => setTasks([])); }, [snapshot?.revision.id]);
  useEffect(() => { productionApi.revisions(projectId).then(result => setRevisionHistory(result.revisions)).catch(() => setRevisionHistory([])); }, [projectId, snapshot?.revision.id]);

  const shot = useMemo(() => snapshot?.shots.find(item => item.id === selectedShotId) ?? null, [snapshot, selectedShotId]);
  const scene = useMemo(() => snapshot?.scenes.find(item => item.id === (selectedSceneId ?? shot?.scene_id)) ?? null, [snapshot, selectedSceneId, shot]);
  const episode = useMemo(() => snapshot?.episodes.find(item => item.id === scene?.episode_id) ?? null, [snapshot, scene]);
  const readiness = useMemo(() => shot ? [...(snapshot?.readiness_results ?? [])].reverse().find(item => item.shot_id === shot.id) : null, [snapshot, shot]);

  async function mutate(action: () => Promise<unknown>, success: string) {
    setBusy(true); setError(null); setNotice(null);
    try { await action(); await refresh(); setNotice(success); }
    catch (cause) {
      const message = cause instanceof Error ? cause.message : '操作失败';
      setError(message.includes('revision') || message.includes('409') ? 'Revision 已过期，请刷新后重试（未覆盖他人修改）。' : message);
    } finally { setBusy(false); }
  }

  async function saveStory(brief: string) {
    const baseRevisionId = snapshot?.revision.id;
    await mutate(() => productionApi.patchProject(projectId, { creative_brief: brief }, baseRevisionId), '故事修改已创建新 revision');
  }

  async function changeMode(mode: string) {
    await mutate(() => productionApi.patchProject(projectId, { production_mode: mode }, snapshot?.revision.id), `Production mode 已切换为 ${mode}`);
  }

  async function prepare() {
    if (!shot) return;
    await mutate(() => productionApi.prepareShot(shot.id), '已运行 canonical readiness preflight');
  }

  async function transition(action: 'approve' | 'lock') {
    if (!shot) return;
    await mutate(() => action === 'approve' ? productionApi.approveShot(shot.id) : productionApi.lockShot(shot.id), action === 'approve' ? 'Shot 已批准' : 'Shot 已锁定');
  }

  async function generate(regenerate = false) {
    if (!shot) return;
    const provider = {
      provider_id: 'remotion', model: 'remotion-cpu', supported_intents: ['REMOTION'],
      supported_reference_roles: [], max_reference_items: 8, max_duration_s: 60,
      min_duration_s: 0.1, max_prompt_length: 4000, supported_resolutions: ['720p'],
      default_resolution: '720p', supports_negative_prompt: true, supports_audio: false,
    };
    await mutate(
      () => regenerate ? productionApi.regenerateShot(shot.id, provider) : productionApi.generateShot(shot.id, provider),
      regenerate ? '已提交 targeted regeneration' : '已提交 canonical generation',
    );
  }

  async function toggleKeyframe(keyframeId: string, locked: boolean) {
    if (!shot || !snapshot) return;
    await mutate(
      () => productionApi.patchShot(shot.id, locked ? 'keyframe unlocked for replacement' : 'keyframe locked by director', [{ op: 'replace', path: `/keyframes/${keyframeId}/locked`, value: !locked }], snapshot.revision.id),
      locked ? 'Keyframe 已解锁，等待 replacement' : 'Keyframe 已锁定',
    );
  }

  async function openDirector() {
    if (sessionId || !snapshot) return sessionId;
    const result = await productionApi.createDirectorSession(projectId, 'Assist the director with canonical production revisions.');
    setSessionId(result.session.id);
    return result.session.id;
  }

  async function sendDirector(apply = false) {
    const message = directorText.trim();
    if (!message) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      const id = await openDirector();
      if (!id) throw new Error('DirectorSession 未创建');
      const operations = apply && selectedShotId ? [{ op: 'replace' as const, path: `/shots/${selectedShotId}/cinematography_notes`, value: message }] : [];
      const result = await productionApi.directorMessage(id, { base_revision_id: snapshot?.revision.id, decision_type: apply ? 'creative_revision_applied' : 'creative_revision_proposed', rationale: message, inputs: { user_message: message, selected_shot_id: selectedShotId }, operations });
      setDecisions(current => [...current, result.decision]);
      setDirectorText('');
      await refresh();
      setNotice('DirectorDecision 已持久化；请在预览后执行具体 revision 操作');
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Director 操作失败'); }
    finally { setBusy(false); }
  }

  if (loading) return <div className="wb-loading" role="status">正在从 Studio API v2 恢复 ProductionRevision…</div>;
  if (error && !snapshot) return <div className="wb-error-state"><h1>无法打开 Workbench</h1><p>{error}</p><button type="button" onClick={() => void refresh()}>重试</button></div>;
  if (!snapshot) return null;

  const readyCount = snapshot.shots.filter(item => ['READY', 'GENERATED', 'QA_PASSED', 'APPROVED', 'LOCKED'].includes(item.readiness_state)).length;
  const failedCount = snapshot.readiness_results.filter(item => !item.passed).length;

  return (
    <main className="director-workbench" data-testid="director-workbench">
      <header className="wb-topbar">
        <div className="wb-brand"><span className="wb-brand-mark">H</span><span>Director Workbench</span></div>
        <div className="wb-project-heading"><strong>{snapshot.project.title || 'Untitled production'}</strong><span>Revision {snapshot.revision.revision_no} · {shortId(snapshot.revision.id)}</span></div>
        <div className="wb-top-actions"><label className="wb-mode-select"><span className="sr-only">Production mode</span><select value={snapshot.project.production_mode} onChange={event => void changeMode(event.target.value)} disabled={busy}><option value="AUTO">FULL_AUTO</option><option value="KEYFRAME_REVIEW">KEYFRAME_REVIEW</option><option value="SHOT_REVIEW">SHOT_REVIEW</option><option value="MANUAL_DIRECTOR">MANUAL_DIRECTOR</option></select></label><span className="wb-health">{readyCount}/{snapshot.shots.length || 0} 就绪</span><button type="button" className="wb-quiet-btn" onClick={() => void refresh()} disabled={busy}>刷新</button></div>
      </header>

      <div className="wb-body">
        <aside className="wb-navigator" aria-label="Project navigator">
          <div className="wb-pane-title"><span>项目结构</span><small>{snapshot.revision.reason}</small></div>
          <button type="button" className="wb-tree-project" onClick={() => { setSelectedSceneId(null); setSelectedShotId(null); setTab('story'); }}>▾ {snapshot.project.title}</button>
          <div className="wb-tree-group"><span className="wb-tree-label">EPISODES</span>{snapshot.episodes.length === 0 && <em className="wb-muted">暂无 Episode</em>}{snapshot.episodes.map(ep => {
            const scenes = snapshot.scenes.filter(item => item.episode_id === ep.id);
            return <div key={ep.id} className="wb-episode"><button type="button" className={`wb-tree-item ${episode?.id === ep.id ? 'is-selected' : ''}`} onClick={() => { setSelectedSceneId(scenes[0]?.id ?? null); setSelectedShotId(null); setTab('storyboard'); }}>▸ {ep.number}. {ep.title || 'Untitled episode'} <span>{scenes.length}</span></button>{episode?.id === ep.id && scenes.map(item => <button type="button" key={item.id} className={`wb-tree-child ${scene?.id === item.id ? 'is-selected' : ''}`} onClick={() => { setSelectedSceneId(item.id); setSelectedShotId(snapshot.shots.find(s => s.scene_id === item.id)?.id ?? null); setTab('storyboard'); }}>Scene {shortId(item.id)} <span>{snapshot.shots.filter(s => s.scene_id === item.id).length}</span></button>)}</div>;
          })}</div>
          <div className="wb-tree-group"><span className="wb-tree-label">RESOURCES</span>{[['Characters', snapshot.characters.length], ['Locations', snapshot.locations.length], ['Props', snapshot.props.length], ['Assets', snapshot.keyframes.length + snapshot.reference_bundles.length]].map(([label, count]) => <button type="button" className="wb-resource-link" key={String(label)} onClick={() => setTab('assets')}>{label}<span>{count}</span></button>)}</div>
          <div className="wb-nav-footer"><span>Canonical graph</span><strong>● synced</strong><small>{snapshot.sources.length} sources · {snapshot.provenance_links.length} provenance links</small></div>
        </aside>

        <section className="wb-main">
          <nav className="wb-tabs" aria-label="Workbench views">{tabs.map(item => <button type="button" key={item.id} className={tab === item.id ? 'is-active' : ''} onClick={() => setTab(item.id)}><span>{item.icon}</span>{item.label}</button>)}</nav>
          {notice && <div className="wb-notice" role="status">✓ {notice}</div>}
          {error && <div className="wb-inline-error" role="alert">{error}</div>}
          {tab === 'story' && <StoryView snapshot={snapshot} revisions={revisionHistory} onSave={saveStory} busy={busy} />}
          {tab === 'storyboard' && <StoryboardView snapshot={snapshot} selectedShotId={selectedShotId} onSelect={setSelectedShotId} onPrepare={prepare} onApprove={() => void transition('approve')} onLock={() => void transition('lock')} onGenerate={() => void generate()} onRegenerate={() => void generate(true)} busy={busy} />}
          {tab === 'canvas' && <CanvasProjection snapshot={snapshot} onSelectShot={id => { setSelectedShotId(id); setTab('storyboard'); }} />}
          {tab === 'timeline' && <TimelineView snapshot={snapshot} onSelectShot={id => { setSelectedShotId(id); setTab('storyboard'); }} />}
          {tab === 'assets' && <AssetsView snapshot={snapshot} onToggleKeyframe={toggleKeyframe} />}
          {tab === 'qa' && <QaView snapshot={snapshot} />}
        </section>

        <aside className="wb-inspector" aria-label="Director and inspector">
          <Inspector shot={shot} scene={scene} episode={episode} readiness={readiness?.state ?? null} onPrepare={prepare} onApprove={() => void transition('approve')} onLock={() => void transition('lock')} onGenerate={() => void generate()} busy={busy} />
          <DirectorPanel text={directorText} setText={setDirectorText} decisions={[...decisions, ...snapshot.director_decisions].slice(-5)} selectedShotId={selectedShotId} onSend={() => void sendDirector(false)} onApply={() => void sendDirector(true)} busy={busy} />
        </aside>
      </div>
      <footer className="wb-task-rail"><span className="wb-task-live"><i /> Task Center</span><span>{tasks.length} persisted tasks</span><span>{snapshot.execution_attempts.length} execution attempts</span><span>{snapshot.execution_plans.length} plans</span><span>{failedCount ? `${failedCount} QA/readiness findings` : 'No active blockers'}</span><span className="wb-task-context">Project {shortId(snapshot.project.id)} · Revision {snapshot.revision.revision_no}</span></footer>
    </main>
  );
}

function StoryView({ snapshot, revisions, onSave, busy }: { snapshot: ProductionGraphSnapshot; revisions: ProductionGraphSnapshot['revision'][]; onSave: (value: string) => Promise<void>; busy: boolean }) {
  const [brief, setBrief] = useState(snapshot.project.creative_brief);
  useEffect(() => setBrief(snapshot.project.creative_brief), [snapshot.project.creative_brief]);
  return <div className="wb-view wb-story-view"><div className="wb-view-head"><div><span className="wb-eyebrow">STORY / CANONICAL NARRATIVE</span><h1>故事结构</h1><p>编辑会通过 RevisionPatch 创建新 revision，历史版本保持可读。</p></div><span className="wb-revision-chip">source {snapshot.sources.length} · events {snapshot.narrative?.events.length ?? 0}</span></div><section className="wb-editor-card"><label htmlFor="creative-brief">Creative brief</label><textarea id="creative-brief" value={brief} onChange={event => setBrief(event.target.value)} rows={5} /><div className="wb-card-actions"><span>{snapshot.revision.snapshot_hash ? `hash ${shortId(snapshot.revision.snapshot_hash)}` : '未计算 snapshot hash'}</span><button type="button" className="wb-primary-btn" disabled={busy || brief === snapshot.project.creative_brief} onClick={() => void onSave(brief)}>保存为新 revision</button></div></section><div className="wb-story-grid"><section className="wb-data-card"><h2>Narrative events</h2>{(snapshot.narrative?.events ?? []).map(event => <article className="wb-event" key={event.id}><span>{String(event.temporal_order).padStart(2, '0')}</span><div><strong>{event.summary}</strong><small>{event.source_refs.length} source refs · {event.plot_thread_ids.length} plot threads</small></div></article>)}{!snapshot.narrative?.events.length && <p className="wb-empty">尚未建立 NarrativeGraph。</p>}</section><section className="wb-data-card"><h2>Plot threads</h2>{(snapshot.narrative?.plot_threads ?? []).map(thread => <article className="wb-thread" key={String(thread.id)}><span className="wb-thread-dot" /><div><strong>{String(thread.title ?? 'Plot thread')}</strong><small>{thread.resolution_event_id ? 'resolved' : 'unresolved'} · {thread.unresolved_event_ids?.length ?? 0} open events</small></div></article>)}{!snapshot.narrative?.plot_threads.length && <p className="wb-empty">暂无 unresolved PlotThread。</p>}</section><section className="wb-data-card"><h2>Revision history</h2>{revisions.slice(-6).reverse().map(item => <article className="wb-thread" key={item.id}><span className="wb-thread-dot" /><div><strong>Revision {item.revision_no}</strong><small>{item.reason} · {shortId(item.id)}</small></div></article>)}</section></div></div>;
}

function StoryboardView({ snapshot, selectedShotId, onSelect, onPrepare, onApprove, onLock, onGenerate, onRegenerate, busy }: { snapshot: ProductionGraphSnapshot; selectedShotId: string | null; onSelect: (id: string) => void; onPrepare: () => void; onApprove: () => void; onLock: () => void; onGenerate: () => void; onRegenerate: () => void; busy: boolean }) {
  return <div className="wb-view"><div className="wb-view-head"><div><span className="wb-eyebrow">STORYBOARD / SHOT-CENTRIC</span><h1>分镜板</h1><p>就绪、连续性、生成与锁定状态来自 canonical backend。</p></div><span className="wb-revision-chip">{snapshot.shots.length} shots</span></div><div className="wb-shot-grid">{snapshot.shots.map(shot => <ShotCard key={shot.id} shot={shot} selected={shot.id === selectedShotId} onSelect={() => onSelect(shot.id)} />)}{!snapshot.shots.length && <div className="wb-empty-panel">此 revision 尚无 Shot。</div>}</div>{selectedShotId && <div className="wb-selection-actions"><span>Selected <code>{shortId(selectedShotId)}</code></span><button type="button" onClick={onPrepare} disabled={busy}>Prepare</button><button type="button" onClick={onGenerate} disabled={busy}>Generate</button><button type="button" onClick={onRegenerate} disabled={busy}>Regenerate</button><button type="button" onClick={onApprove} disabled={busy}>Approve</button><button type="button" onClick={onLock} disabled={busy}>Lock</button></div>}</div>;
}

function ShotCard({ shot, selected, onSelect }: { shot: ProductionShot; selected: boolean; onSelect: () => void }) {
  return <button type="button" className={`wb-shot-card ${selected ? 'is-selected' : ''}`} onClick={onSelect}><div className="wb-shot-thumb"><span>{shot.camera?.shot_size ? String(shot.camera.shot_size) : 'SHOT'}</span><b>{statusLabels[shot.readiness_state] ?? shot.readiness_state}</b></div><div className="wb-shot-card-body"><strong>{shortId(shot.id)}</strong><span>{shot.action_description || '未填写 action description'}</span><small>{shot.duration_target}s · {shot.character_ids.length} characters · {shot.keyframe_ids.length} keyframes</small></div></button>;
}

function Inspector({ shot, scene, episode, readiness, onPrepare, onApprove, onLock, onGenerate, busy }: { shot: ProductionShot | null; scene: ProductionGraphSnapshot['scenes'][number] | null; episode: ProductionGraphSnapshot['episodes'][number] | null; readiness: ReadinessState | null; onPrepare: () => void; onApprove: () => void; onLock: () => void; onGenerate: () => void; busy: boolean }) {
  if (!shot) return <section className="wb-inspector-section"><span className="wb-eyebrow">INSPECTOR</span><h2>选择一个 Shot</h2><p className="wb-muted">从左侧结构或 Storyboard 选择 canonical object。</p></section>;
  return <section className="wb-inspector-section"><div className="wb-inspector-title"><span className="wb-eyebrow">SHOT INSPECTOR</span><span className={`wb-status wb-status--${String(shot.readiness_state).toLowerCase()}`}>{statusLabels[shot.readiness_state] ?? shot.readiness_state}</span></div><h2>{shortId(shot.id)}</h2><dl className="wb-detail-list"><dt>Episode</dt><dd>{episode?.title || shortId(episode?.id)}</dd><dt>Scene</dt><dd>{shortId(scene?.id)}</dd><dt>Camera</dt><dd>{String(shot.camera?.shot_size ?? '—')} · {String(shot.camera?.movement ?? '—')}</dd><dt>Duration</dt><dd>{shot.duration_target}s</dd><dt>Readiness</dt><dd>{readiness ?? shot.readiness_state}</dd><dt>References</dt><dd>{shot.reference_bundle_id ? shortId(shot.reference_bundle_id) : 'missing'}</dd></dl><div className="wb-inspector-actions"><button type="button" onClick={onPrepare} disabled={busy}>Run readiness</button><button type="button" onClick={onGenerate} disabled={busy || shot.readiness_state !== 'READY'}>Generate</button><button type="button" onClick={onApprove} disabled={busy}>Approve</button><button type="button" onClick={onLock} disabled={busy}>Lock</button></div></section>;
}

function DirectorPanel({ text, setText, decisions, selectedShotId, onSend, onApply, busy }: { text: string; setText: (value: string) => void; decisions: ProductionDirectorDecision[]; selectedShotId: string | null; onSend: () => void; onApply: () => void; busy: boolean }) {
  return <section className="wb-director-panel"><div className="wb-panel-head"><div><span className="wb-eyebrow">DIRECTOR</span><h2>Creative control</h2></div><span className="wb-online-dot">● live</span></div><div className="wb-director-history">{decisions.length ? decisions.map(item => <article key={item.id}><span>{item.decision_type}</span><p>{item.rationale || item.decision_type}</p><small>{shortId(item.id)}</small></article>) : <p className="wb-empty">提出一个创作意图，DirectorDecision 会写入 canonical graph。</p>}</div><label className="wb-director-input"><span>给 Director 的指令</span><textarea value={text} onChange={event => setText(event.target.value)} placeholder="例如：这一场更紧张一点。" rows={3} /><div className="wb-director-actions"><button type="button" className="wb-quiet-btn" onClick={onSend} disabled={busy || !text.trim()}>保存 proposal</button><button type="button" className="wb-primary-btn" onClick={onApply} disabled={busy || !text.trim() || !selectedShotId}>Apply to selected shot</button></div></label><p className="wb-director-note">PROPOSE → REVIEW → APPLY。Apply 会创建 RevisionPatch；不会直接调用 provider。</p></section>;
}

function CanvasProjection({ snapshot, onSelectShot }: { snapshot: ProductionGraphSnapshot; onSelectShot: (id: string) => void }) {
  const nodes = [...(snapshot.narrative?.events ?? []).map(item => ({ id: item.id, type: 'NarrativeEvent', label: item.summary })), ...snapshot.scenes.map(item => ({ id: item.id, type: 'Scene', label: item.purpose || 'Scene' })), ...snapshot.shots.map(item => ({ id: item.id, type: 'Shot', label: item.action_description || shortId(item.id) }))];
  return <div className="wb-view"><div className="wb-view-head"><div><span className="wb-eyebrow">CANVAS / PROJECTION ONLY</span><h1>Production canvas</h1><p>节点引用 canonical IDs；语义修改必须通过 Studio API v2。</p></div></div><div className="wb-canvas-grid">{nodes.map(node => <article className={`wb-canvas-node wb-canvas-node--${node.type.toLowerCase()}`} key={`${node.type}-${node.id}`}><span>{node.type}</span><strong>{node.label}</strong><code>{shortId(node.id)}</code>{node.type === 'Shot' && <button type="button" onClick={() => onSelectShot(node.id)}>inspect</button>}</article>)}{!nodes.length && <p className="wb-empty">暂无 canonical nodes。</p>}</div></div>;
}

function TimelineView({ snapshot, onSelectShot }: { snapshot: ProductionGraphSnapshot; onSelectShot: (id: string) => void }) {
  return <div className="wb-view"><div className="wb-view-head"><div><span className="wb-eyebrow">TIMELINE / SEMANTIC ORDER</span><h1>时间线</h1><p>当前视图按 Episode → Scene → Shot 投影，不在前端创建影子 timeline。</p></div></div><div className="wb-timeline">{snapshot.episodes.map(ep => <section key={ep.id}><header><strong>EP {ep.number}</strong><span>{ep.title}</span></header>{snapshot.scenes.filter(scene => scene.episode_id === ep.id).map(scene => <div className="wb-timeline-scene" key={scene.id}><span>Scene {shortId(scene.id)}</span><div>{snapshot.shots.filter(shot => shot.scene_id === scene.id).map(shot => <button type="button" key={shot.id} className={`wb-timeline-shot wb-status-border--${shot.readiness_state.toLowerCase()}`} onClick={() => onSelectShot(shot.id)}><b>{Math.round(shot.duration_target * 10) / 10}s</b><small>{shortId(shot.id)}</small></button>)}</div></div>)}</section>)}{!snapshot.episodes.length && <p className="wb-empty">暂无 Episode timeline。</p>}</div></div>;
}

function AssetsView({ snapshot, onToggleKeyframe }: { snapshot: ProductionGraphSnapshot; onToggleKeyframe: (keyframeId: string, locked: boolean) => Promise<void> }) {
  const groups = [['Characters', snapshot.characters], ['Character states', snapshot.character_states], ['Look variants', snapshot.look_variants], ['Locations', snapshot.locations], ['Location states', snapshot.location_states], ['Props', snapshot.props], ['Prop states', snapshot.prop_states], ['Keyframes', snapshot.keyframes], ['Reference bundles', snapshot.reference_bundles]] as const;
  return <div className="wb-view"><div className="wb-view-head"><div><span className="wb-eyebrow">ASSETS / CANONICAL REFERENCES</span><h1>资产与参考</h1><p>ReferenceBundle 与 Keyframe 是生产图的一部分，不是 provider-specific 表单。</p></div></div><div className="wb-asset-grid">{groups.map(([label, items]) => <section className="wb-data-card" key={label}><div className="wb-card-heading"><h2>{label}</h2><span>{items.length}</span></div>{items.slice(0, 8).map(item => { const keyframe = label === 'Keyframes' ? item as Record<string, unknown> : null; const locked = Boolean(keyframe?.locked); return <div className="wb-asset-row" key={String(item.id)}><span className="wb-asset-icon">◇</span><div><strong>{String(item.name ?? item.role ?? item.title ?? item.id).slice(0, 42)}</strong><small>{keyframe ? `${String(keyframe.role ?? 'frame')} · ${shortId(String(item.id))}` : shortId(String(item.id))}</small></div>{keyframe && <button type="button" className="wb-asset-action" onClick={() => void onToggleKeyframe(String(item.id), locked)}>{locked ? 'Unlock' : 'Lock'}</button>}</div>; })}{!items.length && <p className="wb-empty">暂无。</p>}</section>)}</div><ReferenceManager bundles={snapshot.reference_bundles} /><CreativeRegistry /></div>;
}

function ReferenceManager({ bundles }: { bundles: Array<Record<string, unknown>> }) {
  const items = bundles.flatMap(bundle => (Array.isArray(bundle.items) ? bundle.items : []).map(item => ({ bundle, item: item as Record<string, unknown> })));
  return <section className="wb-data-card wb-reference-manager"><div className="wb-card-heading"><div><span className="wb-eyebrow">REFERENCE MANAGER</span><h2>Typed reference compatibility</h2></div><span>{items.length} bindings</span></div><p className="wb-muted">角色身份、造型、地点、道具与帧引用由 canonical ReferenceBundle 提供；provider capability 状态由 compiler/runtime 返回。</p>{items.map(({ bundle, item }) => { const artifactId = item.artifact_id as string | undefined; const status = artifactId ? 'BOUND' : 'MISSING'; return <div className="wb-asset-row" key={`${String(bundle.id)}-${String(item.id)}`}><span className={`wb-reference-status wb-reference-status--${status.toLowerCase()}`}>{status}</span><div><strong>{String(item.role ?? 'REFERENCE')}</strong><small>bundle {shortId(String(bundle.id))} · {artifactId ? `artifact ${shortId(artifactId)}` : 'required artifact missing'}</small></div></div>; })}{!items.length && <p className="wb-empty">暂无 ReferenceBundle items；生成前会由 compiler 进行 capability 检查。</p>}</section>;
}

function CreativeRegistry() {
  const [templates, setTemplates] = useState<Array<{ id: string; name: string; desc?: string }>>([]);
  const [tools, setTools] = useState<Array<{ id: string; kind: string; summary: string }>>([]);
  useEffect(() => {
    assetApi.templates().then(setTemplates).catch(() => setTemplates([]));
    studioApi.tools().then(result => setTools(result.tools)).catch(() => setTools([]));
  }, []);
  return <section className="wb-data-card wb-creative-registry"><div className="wb-card-heading"><div><span className="wb-eyebrow">CREATIVE SYSTEMS</span><h2>Templates & skills</h2></div><span>{templates.length + tools.length}</span></div><div className="wb-registry-grid"><div><strong>Production templates</strong>{templates.slice(0, 6).map(template => <span key={template.id}>{template.name}<small>{template.id}</small></span>)}{!templates.length && <small className="wb-muted">No templates available in current backend.</small>}</div><div><strong>Studio skills</strong>{tools.slice(0, 6).map(tool => <span key={tool.id}>{tool.id}<small>{tool.kind} · {tool.summary}</small></span>)}{!tools.length && <small className="wb-muted">No skills available in current backend.</small>}</div></div></section>;
}

function QaView({ snapshot }: { snapshot: ProductionGraphSnapshot }) {
  const findings = snapshot.readiness_results.filter(item => !item.passed || item.warnings.length);
  return <div className="wb-view"><div className="wb-view-head"><div><span className="wb-eyebrow">QA / CONTINUITY SUPERVISOR</span><h1>质量总览</h1><p>显示 readiness/continuity backend findings；Workbench 不重算 canonical gate。</p></div><span className={`wb-health-pill ${findings.length ? 'is-warn' : 'is-pass'}`}>{findings.length ? `${findings.length} findings` : 'PASS'}</span></div><div className="wb-qa-grid"><div className="wb-qa-score"><strong>{snapshot.shots.length ? Math.max(0, Math.round(((snapshot.shots.length - findings.length) / snapshot.shots.length) * 100)) : 100}</strong><span>canonical readiness health</span><small>{snapshot.continuity_constraints.length} continuity constraints</small></div><div className="wb-data-card"><h2>Findings</h2>{findings.map(item => <article className="wb-finding" key={`${item.shot_id}-${item.revision_id}`}><span className={item.passed ? 'is-soft' : 'is-hard'}>{item.passed ? 'WARN' : 'FAIL'}</span><div><strong>Shot {shortId(item.shot_id)}</strong><small>{item.blockers.map(blocker => String(blocker.message ?? blocker.code ?? 'blocker')).join(' · ') || item.warnings.map(warning => String(warning.message ?? warning.code ?? 'warning')).join(' · ')}</small></div></article>)}{!findings.length && <p className="wb-empty">没有 readiness findings。</p>}</div></div><section className="wb-data-card wb-qa-executions"><h2>Candidate workflow</h2><p className="wb-muted">候选只来自真实 ExecutionAttempt/Artifact；不会把“最后生成的文件”自动提升为 canonical。</p>{snapshot.execution_attempts.map(attempt => { const candidateState = attempt.artifact_ids.length ? (attempt.status === 'completed' ? 'CANDIDATE / AVAILABLE' : attempt.status.toUpperCase()) : 'GENERATING'; return <article className="wb-finding" key={attempt.id}><span className={attempt.status === 'completed' ? 'is-soft' : 'is-hard'}>{candidateState}</span><div><strong>Attempt {shortId(attempt.id)}</strong><small>Plan {shortId(attempt.execution_plan_id)} · {attempt.artifact_ids.length} artifact(s) · provider job {attempt.provider_job_id ?? 'pending'}</small></div></article>; })}{!snapshot.execution_attempts.length && <p className="wb-empty">尚无 execution candidate；生成后会在此显示真实 Attempt/Artifact。</p>}</section></div>;
}

export function directorPatchForShot(shotId: string, path: string, value: unknown): RevisionPatchOperation[] {
  return [{ op: 'replace', path: `/shots/${shotId}/${path}`, value }];
}
