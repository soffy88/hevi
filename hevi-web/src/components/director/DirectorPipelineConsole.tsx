'use client';

import { useEffect, useMemo, useState } from 'react';
import { directorPipelineApi, taskApi } from '@/lib/api-client';

import ShotPreparationPanel from './ShotPreparationPanel';
import SceneStagePanel from './SceneStagePanel';
import type {
  DpConcept, DpScreenplay, DpScreenplayScene, DpDesignList, DpDesignCharacter, DpDesignScene,
  DpDesignProp, DpSceneStageSet, DpShotList, DpShotListItem, DpLintFinding,
  DpSeasonEpisode, DpSeasonPlan, DpWork, TaskInfo,
} from '@/types/api';

const TASK_STATUS_LABEL: Record<string, string> = {
  pending: '排队中…', running: '生成中…', paused: '已暂停', failed: '✗ 生成失败', completed: '✓ 已完成',
};

const STAGE_LABELS = ['①立意', '②剧本', '③设计清单', '③.5场面调度', '④分镜'] as const;

function errText(e: unknown): string {
  if (e instanceof Error && e.message === 'NOT_AUTHENTICATED') return '请先登录';
  if (e instanceof Error && e.message.startsWith('402')) return '积分余额不足,请先到「我的」页充值';
  return e instanceof Error ? e.message : '出错了';
}

// ③锁定/④重新生成这两步在后端是 background task 跑(角色/场次一多容易顶到反向代理
// 超时,已经改成"接口立即返回、真正的重活在后台跑",见 director_pipeline.py),
// 这里轮询到状态离开"进行中"为止。
async function pollUntilSettled(workId: string, pendingStatus: string): Promise<DpWork> {
  for (;;) {
    await new Promise(r => setTimeout(r, 2500));
    const w = await directorPipelineApi.getWork(workId);
    if (w.status !== pendingStatus) return w;
  }
}


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
  const [work, setWork] = useState<DpWork | null>(null);
  const [taskInfo, setTaskInfo] = useState<TaskInfo | null>(null);
  const [tasks, setTasks] = useState<TaskInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [budgetUsd, setBudgetUsd] = useState<number | ''>('');
  // INC-001 §L.2:准备台报上来的产集拦截项(提取后仍待确认的镜),非空则禁用产集按钮。
  const [prepBlockers, setPrepBlockers] = useState<string[]>([]);
  const [seasonPlanDraft, setSeasonPlanDraft] = useState<DpSeasonPlan | null>(null);
  const [designDraft, setDesignDraft] = useState<DpDesignList | null>(null);
  const [seasonBudget, setSeasonBudget] = useState(150);

  const evolving = work?.status === 'parsing' || work?.status === 'dispatching';
  const inspectionReady = work?.status === 'inspection_ready' || work?.status === 'dispatch_failed';
  const dispatched = work?.status === 'dispatched';
  const seasonFlow = !!work && ['parsing', 'inspection_ready', 'dispatching', 'dispatched',
    'parse_failed', 'dispatch_failed'].includes(work.status);
  const currentStep = useMemo(() => {
    if (!work) return 0;
    if (work.status === 'parsing') return 1;
    if (inspectionReady) return 2;
    return 3;
  }, [work, inspectionReady]);

  // produce() 只是把生成任务建好排进队列,不代表视频已经生成完——之前这里一看到
  // video_task_id 就显示"✓ 已产集",用户会误以为片子已经出来了。真实状态得轮询
  // /api/tasks/{id}(同 taskApi.get,主线现有能力),直到 completed/failed 才算数。
  useEffect(() => {
    const taskId = work?.video_task_id;
    if (!taskId) { setTaskInfo(null); return; }
    let cancelled = false;
    async function poll() {
      try {
        const t = await taskApi.get(taskId as string);
        if (!cancelled) setTaskInfo(t);
        if (!cancelled && (t.status === 'completed' || t.status === 'failed')) return;
        if (!cancelled) timer = setTimeout(poll, 4000);
      } catch {
        if (!cancelled) timer = setTimeout(poll, 4000);
      }
    }
    let timer: ReturnType<typeof setTimeout> = setTimeout(poll, 0);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [work?.video_task_id]);

  // 每级各自一份编辑态草稿,切到该级时从 work 同步(见 syncDrafts)。
  const [conceptDraft, setConceptDraft] = useState<DpConcept | null>(null);
  const [screenplayDraft, setScreenplayDraft] = useState<DpScreenplay | null>(null);
  const [designListDraft, setDesignListDraft] = useState<DpDesignList | null>(null);
  const [sceneStageDraft, setSceneStageDraft] = useState<DpSceneStageSet | null>(null);
  const [shotListDraft, setShotListDraft] = useState<DpShotList | null>(null);

  // 产集参数
  const [videoProvider, setVideoProvider] = useState('auto');
  const [audioProvider, setAudioProvider] = useState('edge_tts');

  const [qualityProfile, setQualityProfile] = useState('standard');
  const [aspectRatio, setAspectRatio] = useState('16:9');


  function syncDrafts(w: DpWork) {
    setConceptDraft(w.concept);
    setScreenplayDraft(w.screenplay);
    setDesignListDraft(w.design_list);
    setSceneStageDraft(w.scene_stage);
    setShotListDraft(w.shot_list);
  }




  async function start() {
    if (!materialText.trim()) { setErr('请输入素材'); return; }
    setBusy(true); setErr(null);
    try {
      const w = await directorPipelineApi.createWork(materialText, intentHint);
      setWork(w);
      syncDrafts(w);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  async function lockScreenplay() {
    if (!work || !screenplayDraft) return;
    setBusy(true); setErr(null);
    try {
      const w = await directorPipelineApi.lockScreenplay(work.work_id, screenplayDraft);
      setWork(w); syncDrafts(w);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  async function lockDesignList() {
    if (!work || !designListDraft) return;
    if (!confirm('锁定设计清单会为每个角色/场景/道具真实生成参考图并建立资产(真实花钱),确定吗?')) return;
    setBusy(true); setErr(null);
    try {
      let w = await directorPipelineApi.lockDesignList(work.work_id, designListDraft);
      setWork(w); syncDrafts(w);
      if (w.status === 'design_list_locking') {
        w = await pollUntilSettled(work.work_id, 'design_list_locking');
        setWork(w); syncDrafts(w);
      }
      if (w.status === 'design_list_lock_failed') setErr(w.error || '设计清单锁定失败');
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  async function produce() {
    if (!work) return;
    if (!confirm('即将真实生成(触发后由后台队列自动跑,不可撤回),确定开始吗?')) return;
    setBusy(true); setErr(null);
    try {
      const w = await directorPipelineApi.produce(work.work_id, {
        video_provider: videoProvider,
        audio_provider: audioProvider,
        quality_profile: qualityProfile,
        aspect_ratio: aspectRatio,
        budget_usd: budgetUsd === '' ? null : budgetUsd,
      });
      setWork(w);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  async function regenerate(stage: 'concept' | 'screenplay' | 'design_list' | 'scene_stage' | 'shot_list') {
    if (!work) return;
    setBusy(true); setErr(null);
    try {
      const fn = {
        concept: directorPipelineApi.regenerateConcept,
        screenplay: directorPipelineApi.regenerateScreenplay,
        design_list: directorPipelineApi.regenerateDesignList,
        scene_stage: directorPipelineApi.regenerateSceneStage,
        shot_list: directorPipelineApi.regenerateShotList,
      }[stage];
      let w = await fn(work.work_id);
      setWork(w); syncDrafts(w);
      // screenplay(含自审)/ scene_stage / shot_list 重生成都是后台任务,轮询到落地。
      for (const pending of ['screenplay_generating', 'scene_stage_generating', 'shot_list_generating'] as const) {
        if (w.status === pending) { w = await pollUntilSettled(work.work_id, pending); setWork(w); syncDrafts(w); }
      }
      if (w.status === 'screenplay_generate_failed') setErr(w.error || '剧本生成失败');
      if (w.status === 'scene_stage_regenerate_failed') setErr(w.error || '场面调度生成失败');
      if (w.status === 'shot_list_regenerate_failed') setErr(w.error || '分镜生成失败');
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  async function lockConcept() {
    if (!work || !conceptDraft) return;
    setBusy(true); setErr(null);
    try {
      let w = await directorPipelineApi.lockConcept(work.work_id, conceptDraft);
      setWork(w); syncDrafts(w);
      // ②剧本草案含 LLM 自审二遍(~106s),后台跑,轮询到落地。
      if (w.status === 'screenplay_generating') {
        w = await pollUntilSettled(work.work_id, 'screenplay_generating');
        setWork(w); syncDrafts(w);
      }
      if (w.status === 'screenplay_generate_failed') setErr(w.error || '剧本生成失败');
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }


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


  async function lockSceneStage() {
    if (!work || !sceneStageDraft) return;
    setBusy(true); setErr(null);
    try {
      let w = await directorPipelineApi.lockSceneStage(work.work_id, sceneStageDraft);
      setWork(w); syncDrafts(w);
      if (w.status === 'scene_stage_locking') {
        w = await pollUntilSettled(work.work_id, 'scene_stage_locking');
        setWork(w); syncDrafts(w);
      }
      if (w.status === 'scene_stage_lock_failed') setErr(w.error || '场面调度锁定失败');
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  async function lockShotList() {
    if (!work || !shotListDraft) return;
    setBusy(true); setErr(null);
    try {
      const w = await directorPipelineApi.lockShotList(work.work_id, shotListDraft);
      setWork(w); syncDrafts(w);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }


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
      // 整季派发流:解析完成后把审查台草稿同步进来(分集/角色/场景可改后派发)。
      setConceptDraft(created.concept ?? null);
      setDesignDraft(created.design_list ?? null);
      setSeasonPlanDraft(created.season_plan ?? null);
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

    setWork(null); setMaterialText(''); setIntentHint(''); setErr(null);
    setConceptDraft(null); setScreenplayDraft(null); setDesignListDraft(null);
    setSceneStageDraft(null); setShotListDraft(null);
  }

  const lockedThrough = work?.locked_through ?? -1;
  const currentStageIdx = Math.min(lockedThrough + 1, 4);
  const producing = work && work.locked_through >= 4; // shot_list 是 index 4(SPEC-004 插 scene_stage 后)


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


      {work && lockedThrough === 0 && screenplayDraft && (
        <ScreenplayStep
          draft={screenplayDraft} onChange={setScreenplayDraft}
          onRegenerate={() => regenerate('screenplay')} onLock={lockScreenplay} busy={busy}
        />
      )}

      {work && lockedThrough === 1 && designListDraft && (
        <DesignListStep
          draft={designListDraft} onChange={setDesignListDraft}
          onRegenerate={() => regenerate('design_list')} onLock={lockDesignList} busy={busy}
        />
      )}

      {work && lockedThrough === 2 && sceneStageDraft && (
        <SceneStagePanel
          draft={sceneStageDraft} onChange={setSceneStageDraft}
          onRegenerate={() => regenerate('scene_stage')} onLock={lockSceneStage} busy={busy}
        />
      )}

      {work && lockedThrough === 3 && shotListDraft && (
        <ShotListStep
          draft={shotListDraft} onChange={setShotListDraft} designList={work.design_list}
          lint={work.scene_stage_lint}
          onRegenerate={() => regenerate('shot_list')} onLock={lockShotList} busy={busy}
        />
      )}

      {work && producing && (
        <div className="tj-progress">
          <div className="tj-progress__head">
            <span
              className={`tj-run-badge ${taskInfo?.status === 'failed' ? 'tj-run-badge--failed' : taskInfo?.status === 'completed' ? 'tj-run-badge--completed' : 'tj-run-badge--running'}`}
            >
              {!work.video_task_id
                ? '📝 分镜已锁定，可以产集'
                : taskInfo
                  ? `${TASK_STATUS_LABEL[taskInfo.status] ?? taskInfo.status}${taskInfo.status === 'running' ? `（${Math.round(taskInfo.percent)}%）` : ''}`
                  : '查询进度中…'}
            </span>
          </div>
          {!work.video_task_id && (
            <>
              {work.shot_list && work.design_list && (
                <ShotPreparationPanel
                  workId={work.work_id}
                  shotList={work.shot_list}
                  designList={work.design_list}
                  onBlockersChange={setPrepBlockers}
                />
              )}
              <div className="tj-grid">
                <label className="tj-field">
                  <span className="tj-field__label">视频引擎</span>
                  <select value={videoProvider} onChange={e => setVideoProvider(e.target.value)}>
                    <option value="auto">自动路由（最省）</option>
                    <option value="wan_local">Wan 本地（零成本）</option>
                    <option value="ltx2_cloud">LTX-2 云</option>
                    <option value="happyhorse_1_1_maas_lock">云端锁脸</option>
                  </select>
                </label>
                <label className="tj-field">
                  <span className="tj-field__label">配音引擎</span>
                  <select value={audioProvider} onChange={e => setAudioProvider(e.target.value)}>
                    <option value="edge_tts">Edge TTS（多语云）</option>
                    <option value="vibevoice">VibeVoice（本地多说话人）</option>
                  </select>
                </label>
                <label className="tj-field">
                  <span className="tj-field__label">画质</span>
                  <select value={qualityProfile} onChange={e => setQualityProfile(e.target.value)}>
                    <option value="standard">标清 720p</option>
                    <option value="high">高清 1080p</option>
                  </select>
                </label>
                <label className="tj-field">
                  <span className="tj-field__label">画幅</span>
                  <select value={aspectRatio} onChange={e => setAspectRatio(e.target.value)}>
                    <option value="9:16">竖 9:16</option>
                    <option value="16:9">横 16:9</option>
                  </select>
                </label>
                <label className="tj-field">
                  <span className="tj-field__label">预算上限（美元，可选）</span>
                  <input type="number" min={0} step={0.5} value={budgetUsd}
                    onChange={e => setBudgetUsd(e.target.value ? Number(e.target.value) : '')} />
                </label>
              </div>
              <div className="tj-actions">
                <button
                  type="button" className="tj-btn tj-btn--primary" onClick={produce}
                  disabled={busy || prepBlockers.length > 0}
                >
                  {busy ? '提交中…' : '⚠ 确认无误，开始真实生成'}
                </button>
                {prepBlockers.length > 0 && (
                  <span className="tj-err">
                    还有 {prepBlockers.length} 个镜头提取后未完成确认，先在准备台处理
                  </span>
                )}
              </div>
            </>
          )}
          {work.video_task_id && taskInfo?.status === 'failed' && (
            <p className="tj-err">生成失败：{taskInfo.error || '未知错误'}</p>
          )}
          {work.video_task_id && taskInfo?.status === 'completed' && (
            <video className="dp-result-video" controls src={taskApi.videoUrl(work.video_task_id)} />
          )}
          {work.video_task_id && taskInfo?.status !== 'completed' && (
            <p className="tj-hint">任务 ID: {work.video_task_id}，也可在「我的」页查看生成进度。</p>
          )}
          <div className="tj-actions">
            <button type="button" className="tj-btn" onClick={reset}>+ 再建一部</button>
          </div>
        </div>
      )}

    </div>
  );
}

function GateBadge({ score, passed }: { score: number; passed: boolean }) {
  return <div className={`dpi-gate-badge ${passed ? 'is-pass' : 'is-blocked'}`}><span>{passed ? 'GATE PASS' : 'NEEDS REVIEW'}</span><b>{Math.round(score * 100)}%</b></div>;
}


// ── ②剧本 ─────────────────────────────────────────────────────────────────

function ScreenplayStep({ draft, onChange, onRegenerate, onLock, busy }: {
  draft: DpScreenplay; onChange: (s: DpScreenplay) => void;
  onRegenerate: () => void; onLock: () => void; busy: boolean;
}) {
  function updateScene(i: number, patch: Partial<DpScreenplayScene>) {
    const scenes = draft.scenes.map((s, j) => (j === i ? { ...s, ...patch } : s));
    onChange({ scenes });
  }
  function updateDialogueLine(sceneIdx: number, lineIdx: number, field: 'character_name' | 'text', value: string) {
    const scene = draft.scenes[sceneIdx];
    const dialogue = scene.dialogue.map((d, j) => (j === lineIdx ? { ...d, [field]: value } : d));
    updateScene(sceneIdx, { dialogue });
  }
  return (
    <div className="tj-progress">
      {draft.scenes.map((scene, i) => (
        <div key={i} className="dp-card">
          <div className="dp-card__head">第{scene.scene_no}场</div>
          <div className="tj-grid">
            <label className="tj-field"><span className="tj-field__label">时间</span>
              <input value={scene.time} onChange={e => updateScene(i, { time: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-field__label">地点</span>
              <input value={scene.location} onChange={e => updateScene(i, { location: e.target.value })} /></label>
          </div>
          <label className="tj-field"><span className="tj-field__label">叙述（白话）</span>
            <textarea rows={2} value={scene.narration}
              onChange={e => updateScene(i, { narration: e.target.value })} /></label>
          <div className="tj-field__label">对白</div>
          {scene.dialogue.map((d, j) => (
            <div key={j} className="dp-dialogue-row">
              <input className="dp-dialogue-row__speaker" placeholder="说话人" value={d.character_name}
                onChange={e => updateDialogueLine(i, j, 'character_name', e.target.value)} />
              <input className="dp-dialogue-row__text" placeholder="台词（白话）" value={d.text}
                onChange={e => updateDialogueLine(i, j, 'text', e.target.value)} />
            </div>
          ))}
        </div>
      ))}
      <div className="tj-actions">
        <button type="button" className="tj-btn" onClick={onRegenerate} disabled={busy}>↻ 重新生成</button>
        <button type="button" className="tj-btn tj-btn--primary" onClick={onLock} disabled={busy}>
          {busy ? '处理中…' : '锁定剧本，生成③设计清单草稿'}
        </button>
      </div>
    </div>
  );
}

// ── ③设计清单 ─────────────────────────────────────────────────────────────

function DesignListStep({ draft, onChange, onRegenerate, onLock, busy }: {
  draft: DpDesignList; onChange: (d: DpDesignList) => void;
  onRegenerate: () => void; onLock: () => void; busy: boolean;
}) {
  function updateChar(i: number, patch: Partial<DpDesignCharacter>) {
    onChange({ ...draft, characters: draft.characters.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  }
  function updateScene(i: number, patch: Partial<DpDesignScene>) {
    onChange({ ...draft, scenes: draft.scenes.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  }
  function updateProp(i: number, patch: Partial<DpDesignProp>) {
    onChange({ ...draft, props: draft.props.map((p, j) => (j === i ? { ...p, ...patch } : p)) });
  }
  return (
    <div className="tj-progress">
      <div className="sd-review__label">角色（{draft.characters.length}）</div>
      {draft.characters.map((c, i) => (
        <div key={i} className="dp-card">
          <div className="tj-grid">
            <label className="tj-field"><span className="tj-field__label">姓名</span>
              <input value={c.name} onChange={e => updateChar(i, { name: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-field__label">外貌</span>
              <input value={c.appearance} onChange={e => updateChar(i, { appearance: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-field__label">衣着</span>
              <input value={c.wardrobe} onChange={e => updateChar(i, { wardrobe: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-field__label">发型</span>
              <input value={c.hairstyle} onChange={e => updateChar(i, { hairstyle: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-field__label">性格</span>
              <input value={c.personality} onChange={e => updateChar(i, { personality: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-field__label">声线倾向</span>
              <input value={c.voice_hint} onChange={e => updateChar(i, { voice_hint: e.target.value })} /></label>
            <label className="tj-field tj-field--check">
              <input type="checkbox" checked={c.is_lead}
                onChange={e => updateChar(i, { is_lead: e.target.checked })} />
              <span>主角</span>
            </label>
          </div>
        </div>
      ))}
      <div className="sd-review__label">场景（{draft.scenes.length}）</div>
      {draft.scenes.map((s, i) => (
        <div key={i} className="dp-card">
          <div className="tj-grid">
            <label className="tj-field"><span className="tj-field__label">名称</span>
              <input value={s.name} onChange={e => updateScene(i, { name: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-field__label">环境</span>
              <input value={s.environment} onChange={e => updateScene(i, { environment: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-field__label">光照</span>
              <input value={s.lighting} onChange={e => updateScene(i, { lighting: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-field__label">氛围</span>
              <input value={s.mood} onChange={e => updateScene(i, { mood: e.target.value })} /></label>
          </div>
        </div>
      ))}
      {draft.props.length > 0 && (
        <>
          <div className="sd-review__label">道具（{draft.props.length}）</div>
          {draft.props.map((p, i) => (
            <div key={i} className="dp-card">
              <div className="tj-grid">
                <label className="tj-field"><span className="tj-field__label">名称</span>
                  <input value={p.name} onChange={e => updateProp(i, { name: e.target.value })} /></label>
                <label className="tj-field"><span className="tj-field__label">外观</span>
                  <input value={p.appearance} onChange={e => updateProp(i, { appearance: e.target.value })} /></label>
              </div>
            </div>
          ))}
        </>
      )}
      <div className="tj-actions">
        <button type="button" className="tj-btn" onClick={onRegenerate} disabled={busy}>↻ 重新生成</button>
        <button type="button" className="tj-btn tj-btn--primary" onClick={onLock} disabled={busy}>
          {busy ? '建立资产中…' : '锁定设计清单（建立角色/场景/道具资产），生成③.5场面调度草稿'}
        </button>
      </div>
    </div>
  );
}

// ── ④分镜头剧本 ────────────────────────────────────────────────────────────

const LINT_LABEL: Record<string, string> = {
  L1: '跳轴', L2: '反打差异', L3: 'eyeline', L4: '剪辑冗余',
};

function ShotListStep({ draft, onChange, designList, lint, onRegenerate, onLock, busy }: {
  draft: DpShotList; onChange: (s: DpShotList) => void; designList: DpDesignList | null;
  lint?: DpLintFinding[];
  onRegenerate: () => void; onLock: () => void; busy: boolean;
}) {
  function updateShot(i: number, patch: Partial<DpShotListItem>) {
    onChange({ shots: draft.shots.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  }
  function updateDialogueLine(shotIdx: number, lineIdx: number, field: 'character_name' | 'text', value: string) {
    const shot = draft.shots[shotIdx];
    const dialogue_lines = shot.dialogue_lines.map((d, j) => (j === lineIdx ? { ...d, [field]: value } : d));
    updateShot(shotIdx, { dialogue_lines });
  }
  const characterNames = designList?.characters.map(c => c.name) ?? [];
  return (
    <div className="tj-progress">
      {lint && lint.length > 0 && (
        <div className="dp-ss-lint">
          <div className="sd-review__label">⚠ 场面调度守护(SPEC-004 §4,{lint.length} 项确定性告警)</div>
          {lint.map((f, i) => (
            <div key={i} className="dp-ss-lint__item">
              <span className="sd-chip" title={f.rule}>{LINT_LABEL[f.rule] ?? f.rule}</span>
              <span>{f.message}</span>
            </div>
          ))}
          <p className="tj-hint">跳轴/反打/eyeline/剪辑冗余是零成本规则检查——可回退③.5场面调度或④分镜修正。</p>
        </div>
      )}
      {draft.shots.map((shot, i) => (
        <div key={i} className="dp-card">
          <div className="dp-card__head">{shot.shot_id}（第{shot.scene_no}场）</div>
          <div className="tj-grid">
            <label className="tj-field"><span className="tj-field__label">景别</span>
              <input value={shot.shot_size} onChange={e => updateShot(i, { shot_size: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-field__label">机位</span>
              <input value={shot.camera} onChange={e => updateShot(i, { camera: e.target.value })} /></label>
            <label className="tj-field"><span className="tj-field__label">时长（秒）</span>
              <input type="number" min={1} step={0.5} value={shot.duration_s}
                onChange={e => updateShot(i, { duration_s: Number(e.target.value) })} /></label>
          </div>
          <label className="tj-field"><span className="tj-field__label">画面内容</span>
            <textarea rows={2} value={shot.visual_prompt}
              onChange={e => updateShot(i, { visual_prompt: e.target.value })} /></label>
          <div className="tj-field__label">台词（说话人留空 = 旁白）</div>
          {shot.dialogue_lines.map((d, j) => (
            <div key={j} className="dp-dialogue-row">
              <input className="dp-dialogue-row__speaker" placeholder="旁白（留空）" value={d.character_name}
                onChange={e => updateDialogueLine(i, j, 'character_name', e.target.value)} />
              <input className="dp-dialogue-row__text" placeholder="台词/旁白文字" value={d.text}
                onChange={e => updateDialogueLine(i, j, 'text', e.target.value)} />
            </div>
          ))}
          <div className="dp-chips">
            {shot.character_names.map(n => <span key={n} className="sd-chip">{n}</span>)}
            {shot.scene_name && <span className="sd-chip" title="场景">📍{shot.scene_name}</span>}
          </div>
        </div>
      ))}
      {characterNames.length > 0 && (
        <p className="tj-hint">已锁定角色:{characterNames.join('、')} —— 台词说话人请填这里面的名字,才能匹配到对应声线/参考图。</p>
      )}
      <div className="tj-actions">
        <button type="button" className="tj-btn" onClick={onRegenerate} disabled={busy}>↻ 重新生成</button>
        <button type="button" className="tj-btn tj-btn--primary" onClick={onLock} disabled={busy}>
          {busy ? '处理中…' : '锁定分镜'}
        </button>
      </div>
    </div>
  );

}


function Trail({ items }: { items: Array<{ at: string; stage: string; status: string; detail: string }> }) {
  if (!items.length) return null;
  return (
    <details className="dpi-trail">
      <summary>查看 Agent 状态演进轨迹</summary>
      <ol>
        {items.map((item, index) => (
          <li key={`${item.at}-${index}`}><b>{item.stage}</b><span>{item.detail}</span><em>{item.status}</em></li>
        ))}
      </ol>
    </details>
  );
}

