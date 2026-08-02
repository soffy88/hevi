'use client';

import { useEffect, useMemo, useState } from 'react';
import { directorPipelineApi, taskApi } from '@/lib/api-client';
import type {
  DpConcept,
  DpDesignCharacter,
  DpDesignList,
  DpDesignScene,
  DpSeasonEpisode,
  DpSeasonPlan,
  DpWork,
  TaskInfo,
} from '@/types/api';

const DURATION_OPTIONS = [
  { value: '1-5min', label: '1–5 分钟' },
  { value: '5-15min', label: '5–15 分钟' },
  { value: '15-45min', label: '15–45 分钟' },
];

const PIPELINE_STEPS = [
  ['L0', '原生文本'],
  ['L1', '戏剧弧线 / 分集'],
  ['L2', '逐场剧本 / 资产'],
  ['L3', '分镜 / 生产'],
] as const;

function errorText(error: unknown): string {
  if (error instanceof Error && error.message === 'NOT_AUTHENTICATED') return '请先登录后再启动导演流水线';
  return error instanceof Error ? error.message : '操作失败';
}

function statusLabel(status: string): string {
  return {
    pending: '等待调度', queued: '队列中', running: '生成中', completed: '已完成', failed: '失败',
  }[status] ?? status;
}

export function DirectorPipelineConsole() {
  const [workName, setWorkName] = useState('');
  const [materialText, setMaterialText] = useState('');
  const [episodeCount, setEpisodeCount] = useState(3);
  const [episodeDuration, setEpisodeDuration] = useState('1-5min');
  const [intentHint, setIntentHint] = useState('');

  const [seasonBudget, setSeasonBudget] = useState(150);
  const [videoProvider, setVideoProvider] = useState('happyhorse_1_1_maas_lock');
  const [audioProvider, setAudioProvider] = useState('vibevoice');
  const [qualityProfile, setQualityProfile] = useState('standard');
  const [aspectRatio, setAspectRatio] = useState('16:9');

  const [work, setWork] = useState<DpWork | null>(null);
  const [conceptDraft, setConceptDraft] = useState<DpConcept | null>(null);
  const [designDraft, setDesignDraft] = useState<DpDesignList | null>(null);
  const [seasonPlanDraft, setSeasonPlanDraft] = useState<DpSeasonPlan | null>(null);
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const evolving = work?.status === 'parsing' || work?.status === 'dispatching';
  const inspectionReady = work?.status === 'inspection_ready' || work?.status === 'dispatch_failed';
  const dispatched = work?.status === 'dispatched';

  useEffect(() => {
    if (!work?.work_id || !evolving) return;
    let stopped = false;
    const poll = async () => {
      try {
        const latest = await directorPipelineApi.getWork(work.work_id);
        if (!stopped) setWork(latest);
        if (!stopped && (latest.status === 'parsing' || latest.status === 'dispatching')) {
          timer = setTimeout(poll, 2500);
        }
      } catch (err) {
        if (!stopped) setError(errorText(err));
      }
    };
    let timer = setTimeout(poll, 1500);
    return () => { stopped = true; clearTimeout(timer); };
  }, [work?.work_id, evolving]);

  useEffect(() => {
    if (!work || !inspectionReady) return;
    setConceptDraft(work.concept);
    setDesignDraft(work.design_list);
    setSeasonPlanDraft(work.season_plan ?? null);
    const cfg = work.production_config ?? {};
    if (typeof cfg.season_budget_usd === 'number') setSeasonBudget(cfg.season_budget_usd);
    if (typeof cfg.video_provider === 'string') setVideoProvider(cfg.video_provider);
    if (typeof cfg.audio_provider === 'string') setAudioProvider(cfg.audio_provider);
  }, [work?.work_id, inspectionReady]);

  useEffect(() => {
    const ids = work?.task_ids ?? [];
    if (!ids.length) { setTasks([]); return; }
    let stopped = false;
    const poll = async () => {
      try {
        const latest = await Promise.all(ids.map(id => taskApi.get(id)));
        if (stopped) return;
        setTasks(latest);
        if (latest.some(task => !['completed', 'failed'].includes(task.status))) {
          timer = setTimeout(poll, 4000);
        }
      } catch {
        if (!stopped) timer = setTimeout(poll, 4000);
      }
    };
    let timer = setTimeout(poll, 0);
    return () => { stopped = true; clearTimeout(timer); };
  }, [work?.task_ids?.join(',')]);

  const currentStep = useMemo(() => {
    if (!work) return 0;
    if (work.status === 'parsing') return 1;
    if (inspectionReady) return 2;
    return 3;
  }, [work, inspectionReady]);

  async function startInspection() {
    if (!workName.trim()) { setError('请输入作品名称'); return; }
    if (!materialText.trim()) { setError('请粘贴小说原文、剧本大纲或一句话梗概'); return; }
    setBusy(true); setError(null); setTasks([]);
    try {
      const created = await directorPipelineApi.parseWork({
        work_name: workName.trim(),
        material_text: materialText.trim(),
        target_episodes: episodeCount,
        episode_duration: episodeDuration,
        intent_hint: intentHint.trim(),
        season_budget_usd: seasonBudget,
        video_provider: videoProvider,
        audio_provider: audioProvider,
      });
      setWork(created);
      setConceptDraft(null); setDesignDraft(null); setSeasonPlanDraft(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function dispatchSeason() {
    if (!work || !conceptDraft || !designDraft || !seasonPlanDraft || !work.screenplay) return;
    if (!window.confirm(`将锁定资产并派发 ${seasonPlanDraft.target_episodes} 集真实生成任务，继续吗？`)) return;
    setBusy(true); setError(null);
    try {
      const updated = await directorPipelineApi.dispatchSeason(work.work_id, {
        season_budget_usd: seasonBudget,
        video_provider: videoProvider,
        audio_provider: audioProvider,
        duration_archetype: episodeDuration,
        quality_profile: qualityProfile,
        aspect_ratio: aspectRatio,
        concept: conceptDraft,
        screenplay: work.screenplay,
        design_list: designDraft,
        season_plan: seasonPlanDraft,
      });
      setWork(updated);
    } catch (err) {
      setError(errorText(err));
      try { setWork(await directorPipelineApi.getWork(work.work_id)); } catch { /* 保留现有审查数据 */ }
    } finally {
      setBusy(false);
    }
  }

  function updateEpisode(index: number, patch: Partial<DpSeasonEpisode>) {
    if (!seasonPlanDraft) return;
    setSeasonPlanDraft({
      ...seasonPlanDraft,
      episodes: seasonPlanDraft.episodes.map((episode, i) => i === index ? { ...episode, ...patch } : episode),
    });
  }

  function updateCharacter(index: number, patch: Partial<DpDesignCharacter>) {
    if (!designDraft) return;
    setDesignDraft({
      ...designDraft,
      characters: designDraft.characters.map((character, i) => i === index ? { ...character, ...patch } : character),
    });
  }

  function updateScene(index: number, patch: Partial<DpDesignScene>) {
    if (!designDraft) return;
    setDesignDraft({
      ...designDraft,
      scenes: designDraft.scenes.map((scene, i) => i === index ? { ...scene, ...patch } : scene),
    });
  }

  function reset() {
    setWork(null); setConceptDraft(null); setDesignDraft(null); setSeasonPlanDraft(null);
    setTasks([]); setError(null);
  }

  return (
    <div className="dpi-shell">
      <header className="dpi-hero">
        <div>
          <span className="dpi-eyebrow">DIRECTOR PIPELINE · INDUSTRIAL MODE</span>
          <h1>🎬 导演流水线</h1>
          <p>小说 → 戏剧弧线 → 逐场剧本 → 视觉资产 → 导演分镜 → 整季成片</p>
        </div>
        {work && <button type="button" className="dpi-btn dpi-btn--ghost" onClick={reset}>新建作品</button>}
      </header>

      <nav className="dpi-rail" aria-label="影视工业流水线阶段">
        {PIPELINE_STEPS.map(([code, label], index) => (
          <div key={code} className={index <= currentStep ? 'is-active' : ''}>
            <b>{code}</b><span>{label}</span>
          </div>
        ))}
      </nav>

      {(!work || work.status === 'parse_failed') && (
        <section className="dpi-panel dpi-cold-start">
          <div className="dpi-panel__head">
            <span>01</span><div><h2>冷启动 · 资产解析</h2><p>只建立故事、场次和资产草案，不会直接生成视频或产生渲染费用。</p></div>
          </div>
          <div className="dpi-form-grid">
            <label><span>作品名称</span><input aria-label="作品名称" value={workName} onChange={e => setWorkName(e.target.value)} placeholder="临高启明 · 第一季" /></label>
            <label><span>目标集数</span><input aria-label="目标集数" type="number" min={1} max={12} value={episodeCount} onChange={e => setEpisodeCount(Math.max(1, Math.min(12, Number(e.target.value))))} /></label>
            <label><span>单集时长</span><select aria-label="单集时长" value={episodeDuration} onChange={e => setEpisodeDuration(e.target.value)}>{DURATION_OPTIONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
            <label className="dpi-span-2"><span>创作意图</span><input aria-label="创作意图" value={intentHint} onChange={e => setIntentHint(e.target.value)} placeholder="目标观众、情绪方向、视觉张力与必须保留的表达" /></label>
            <label className="dpi-span-3"><span>文本来源</span><textarea aria-label="文本来源" rows={12} value={materialText} onChange={e => setMaterialText(e.target.value)} placeholder="粘贴小说原文、剧本大纲，或仅输入一句话梗概……" /></label>
          </div>
          {work?.status === 'parse_failed' && <p className="dpi-error">解析失败：{work.error}</p>}
          <button type="button" className="dpi-btn dpi-btn--primary dpi-btn--wide" onClick={startInspection} disabled={busy}>
            {busy ? '正在提交…' : '🤖 启动 Agent 智能解析与资产解构'}
          </button>
        </section>
      )}

      {work?.status === 'parsing' && (
        <section className="dpi-panel dpi-evolving">
          <div className="dpi-orbit" aria-hidden="true"><span /><span /><span /></div>
          <h2>Agent 正在后台推进作品状态</h2>
          <p>正在依次完成意图解析、StoryGraph、分集节拍、逐场剧本和制作设计。</p>
          <Trail items={work.decision_trail ?? []} />
        </section>
      )}

      {inspectionReady && work && conceptDraft && designDraft && seasonPlanDraft && (
        <section className="dpi-review-stream">
          <div className="dpi-review-title">
            <div><span className="dpi-eyebrow">ASSET &amp; PLAN INSPECTION</span><h2>{work.work_name} · 导演审查台</h2></div>
            <GateBadge score={work.gate_report?.score ?? 0} passed={work.gate_report?.passed ?? false} />
          </div>

          <details className="dpi-inspection" open>
            <summary><span>📜</span><b>剧本与分集规划</b><em>{seasonPlanDraft.episodes.length} 集 · {work.screenplay?.scenes.length ?? 0} 个视听场次</em></summary>
            <div className="dpi-inspection__body">
              {seasonPlanDraft.episodes.map((episode, index) => (
                <article className="dpi-episode" key={episode.ep_number}>
                  <div className="dpi-episode__number">EP {String(episode.ep_number).padStart(2, '0')}</div>
                  <label><span>标题</span><input value={episode.title} onChange={e => updateEpisode(index, { title: e.target.value })} /></label>
                  <label><span>戏剧弧线</span><input value={episode.target_emotion_arc} onChange={e => updateEpisode(index, { target_emotion_arc: e.target.value })} /></label>
                  <div className="dpi-chip-row">{episode.beats.map((beat, i) => <span key={`${beat}-${i}`}>{beat}</span>)}</div>
                </article>
              ))}
              <details className="dpi-subdetails"><summary>查看逐场剧本</summary>{work.screenplay?.scenes.map(scene => <div className="dpi-scene-script" key={scene.scene_no}><b>第 {scene.scene_no} 场 · {scene.int_ext || '场景'} · {scene.day_night || scene.time} · {scene.location}</b><div className="dpi-chip-row"><span>复杂度 {scene.production_complexity || 'low'}</span><span>CG {scene.cg_level || 'low'}</span></div><p>{scene.event_summary || scene.narration}</p>{scene.visual_actions?.map((action, i) => <p key={i}>🎥 {action}</p>)}{scene.dialogue.map((line, i) => <blockquote key={i}>{line.character_name}：{line.text}</blockquote>)}</div>)}</details>
            </div>
          </details>

          <details className="dpi-inspection" open>
            <summary><span>👤</span><b>Character Bible · 角色视觉锚点</b><em>{designDraft.characters.length} 人 · 派发后生成身份参考资产</em></summary>
            <div className="dpi-inspection__body dpi-card-grid">
              {designDraft.characters.map((character, index) => (
                <article className="dpi-asset-card" key={`${character.name}-${index}`}>
                  <div className="dpi-avatar-placeholder">{character.name.slice(0, 1) || '?'}</div>
                  <label><span>角色名</span><input value={character.name} onChange={e => updateCharacter(index, { name: e.target.value })} /></label>
                  <label><span>视觉锚点</span><textarea rows={2} value={character.appearance} onChange={e => updateCharacter(index, { appearance: e.target.value })} /></label>
                  <label><span>服装连续性</span><input value={character.wardrobe} onChange={e => updateCharacter(index, { wardrobe: e.target.value })} /></label>
                  <label><span>声线</span><input value={character.voice_hint} onChange={e => updateCharacter(index, { voice_hint: e.target.value })} /></label>
                </article>
              ))}
            </div>
          </details>

          <details className="dpi-inspection" open>
            <summary><span>🏛️</span><b>Production Design · 场景与风格</b><em>{designDraft.scenes.length} 个场景 · {conceptDraft.style || '待设定风格'}</em></summary>
            <div className="dpi-inspection__body">
              <div className="dpi-form-grid dpi-form-grid--compact">
                <label><span>主题</span><input value={conceptDraft.theme} onChange={e => setConceptDraft({ ...conceptDraft, theme: e.target.value })} /></label>
                <label><span>基调</span><input value={conceptDraft.tone} onChange={e => setConceptDraft({ ...conceptDraft, tone: e.target.value })} /></label>
                <label><span>视觉风格</span><input value={conceptDraft.style} onChange={e => setConceptDraft({ ...conceptDraft, style: e.target.value })} /></label>
              </div>
              <div className="dpi-card-grid">
                {designDraft.scenes.map((scene, index) => (
                  <article className="dpi-scene-card" key={`${scene.name}-${index}`}>
                    <label><span>场景</span><input value={scene.name} onChange={e => updateScene(index, { name: e.target.value })} /></label>
                    <label><span>环境</span><textarea rows={2} value={scene.environment} onChange={e => updateScene(index, { environment: e.target.value })} /></label>
                    <label><span>光线</span><input value={scene.lighting} onChange={e => updateScene(index, { lighting: e.target.value })} /></label>
                    <label><span>氛围</span><input value={scene.mood} onChange={e => updateScene(index, { mood: e.target.value })} /></label>
                  </article>
                ))}
              </div>
            </div>
          </details>

          <section className="dpi-gate">
            <div className="dpi-panel__head"><span>G</span><div><h2>导演双环自批判门禁</h2><p>内环检查戏剧完整性，外环检查视觉锚点、场景覆盖和预算可行性。</p></div></div>
            <div className="dpi-gate-grid">{work.gate_report?.checks.map(check => <article key={check.key} className={check.passed ? 'is-pass' : 'is-blocked'}><b>{check.passed ? '✓' : '!'}</b><div><strong>{check.label}</strong><span>{check.detail}</span></div><em>{Math.round(check.score * 100)}%</em></article>)}</div>
            {!!work.gate_report?.warnings.length && <p className="dpi-warning">提示：{work.gate_report.warnings.join('；')}</p>}
          </section>

          <section className="dpi-dispatch">
            <div className="dpi-panel__head"><span>02</span><div><h2>生产与派发配置</h2><p>只有点击确认后才会生成参考资产并创建真实生产任务。</p></div></div>
            <div className="dpi-form-grid">
              <label><span>季预算上限（USD）</span><input aria-label="季预算上限" type="number" min={1} step={1} value={seasonBudget} onChange={e => setSeasonBudget(Number(e.target.value))} /></label>
              <label><span>视频 Provider</span><select aria-label="视频 Provider" value={videoProvider} onChange={e => setVideoProvider(e.target.value)}><option value="happyhorse_1_1_maas_lock">云端锁脸（推荐）</option><option value="wan_local">Wan 本地</option><option value="ltx2_cloud">LTX-2 云端</option></select></label>
              <label><span>配音引擎</span><select aria-label="配音引擎" value={audioProvider} onChange={e => setAudioProvider(e.target.value)}><option value="vibevoice">VibeVoice 本地多说话人</option><option value="edge_tts">Edge TTS</option></select></label>
              <label><span>画质</span><select value={qualityProfile} onChange={e => setQualityProfile(e.target.value)}><option value="standard">720p 标准</option><option value="high">1080p 高清</option></select></label>
              <label><span>画幅</span><select value={aspectRatio} onChange={e => setAspectRatio(e.target.value)}><option value="16:9">16:9 横屏</option><option value="9:16">9:16 竖屏</option></select></label>
              <div className="dpi-cost"><span>当前预计成本</span><b>${(work.estimated_cost_usd ?? 0).toFixed(2)}</b><em>派发时按当前配置重新核算并熔断</em></div>
            </div>
            {work.status === 'dispatch_failed' && <p className="dpi-error">上次派发失败：{work.error}</p>}
            {error && <p className="dpi-error">{error}</p>}
            <button type="button" className="dpi-btn dpi-btn--primary dpi-btn--wide" onClick={dispatchSeason} disabled={busy}>
              {busy ? '正在校验…' : '🚀 确认资产并一键派发整季生成'}
            </button>
          </section>

          <Trail items={work.decision_trail ?? []} />
        </section>
      )}

      {work?.status === 'dispatching' && (
        <section className="dpi-panel dpi-evolving"><div className="dpi-orbit" aria-hidden="true"><span /><span /><span /></div><h2>正在锁定资产并派发整季</h2><p>系统正在建立角色/场景参考资产，随后逐集创建统一 Task。</p><Trail items={work.decision_trail ?? []} /></section>
      )}

      {dispatched && work && (
        <section className="dpi-panel dpi-delivery">
          <div className="dpi-panel__head"><span>✓</span><div><h2>整季已派发</h2><p>Series {work.series_id} · {work.task_ids?.length ?? 0} 个真实任务</p></div></div>
          <div className="dpi-task-list">{(work.task_ids ?? []).map((id, index) => { const task = tasks.find(item => item.task_id === id || String((item as TaskInfo & { id?: string }).id) === id); return <article key={id}><div><b>第 {index + 1} 集</b><code>{id}</code></div><span>{task ? `${statusLabel(task.status)} · ${Math.round(task.percent ?? 0)}%` : '读取状态中…'}</span>{task?.status === 'completed' && <video controls src={taskApi.videoUrl(id)} />}{task?.status === 'failed' && <em>{task.error || '生成失败'}</em>}</article>; })}</div>
          <Trail items={work.decision_trail ?? []} />
        </section>
      )}

      {error && !inspectionReady && <p className="dpi-error">{error}</p>}
    </div>
  );
}

function GateBadge({ score, passed }: { score: number; passed: boolean }) {
  return <div className={`dpi-gate-badge ${passed ? 'is-pass' : 'is-blocked'}`}><span>{passed ? 'GATE PASS' : 'NEEDS REVIEW'}</span><b>{Math.round(score * 100)}%</b></div>;
}

function Trail({ items }: { items: Array<{ at: string; stage: string; status: string; detail: string }> }) {
  if (!items.length) return null;
  return <details className="dpi-trail"><summary>查看 Agent 状态演进轨迹</summary><ol>{items.map((item, index) => <li key={`${item.at}-${index}`}><b>{item.stage}</b><span>{item.detail}</span><em>{item.status}</em></li>)}</ol></details>;
}
