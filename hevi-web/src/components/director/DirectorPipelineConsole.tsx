/**
 * DirectorPipelineConsole — SPEC-003 主线导演流水线(需登录)
 * 素材 → ①立意 → ②剧本(白话) → ③设计清单(锁资产) → ④分镜(带对白台词) → 产集。
 * 每级 AI 生成草稿,人编辑后锁定才放行下一级(见 docs/specs/SPEC-003-mainline-director-pipeline.md)。
 * 布局仿 ShortdramaCreatePanel(表单/审阅/确认),复用同一套 .tj-* 样式。
 * 跟现有 DirectorConsole(一句话直接产集)并行存在,这是新增的另一个入口,不替换它。
 */
'use client';

import { useEffect, useState } from 'react';
import { directorPipelineApi, taskApi } from '@/lib/api-client';
import ShotPreparationPanel from './ShotPreparationPanel';
import type {
  DpConcept, DpScreenplay, DpScreenplayScene, DpDesignList, DpDesignCharacter, DpDesignScene,
  DpDesignProp, DpShotList, DpShotListItem, DpWork, TaskInfo,
} from '@/types/api';

const TASK_STATUS_LABEL: Record<string, string> = {
  pending: '排队中…', running: '生成中…', paused: '已暂停', failed: '✗ 生成失败', completed: '✓ 已完成',
};

const STAGE_LABELS = ['①立意', '②剧本', '③设计清单', '④分镜'] as const;

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
  { value: 'short', label: '极短 ~10s' }, { value: '1-5min', label: '1-5 分钟' },
  { value: '5-15min', label: '5-15 分钟' }, { value: '15-45min', label: '15-45 分钟' },
  { value: '45min+', label: '45 分钟+' },
];

export function DirectorPipelineConsole() {
  const [materialText, setMaterialText] = useState('');
  const [intentHint, setIntentHint] = useState('');
  const [work, setWork] = useState<DpWork | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [taskInfo, setTaskInfo] = useState<TaskInfo | null>(null);

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
  const [shotListDraft, setShotListDraft] = useState<DpShotList | null>(null);

  // 产集参数
  const [videoProvider, setVideoProvider] = useState('auto');
  const [audioProvider, setAudioProvider] = useState('edge_tts');
  const [qualityProfile, setQualityProfile] = useState('standard');
  const [aspectRatio, setAspectRatio] = useState('9:16');
  const [budgetUsd, setBudgetUsd] = useState<number | ''>('');
  // INC-001 §L.2:准备台报上来的产集拦截项(提取后仍待确认的镜),非空则禁用产集按钮。
  const [prepBlockers, setPrepBlockers] = useState<string[]>([]);

  function syncDrafts(w: DpWork) {
    setConceptDraft(w.concept);
    setScreenplayDraft(w.screenplay);
    setDesignListDraft(w.design_list);
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

  async function regenerate(stage: 'concept' | 'screenplay' | 'design_list' | 'shot_list') {
    if (!work) return;
    setBusy(true); setErr(null);
    try {
      const fn = {
        concept: directorPipelineApi.regenerateConcept,
        screenplay: directorPipelineApi.regenerateScreenplay,
        design_list: directorPipelineApi.regenerateDesignList,
        shot_list: directorPipelineApi.regenerateShotList,
      }[stage];
      let w = await fn(work.work_id);
      setWork(w); syncDrafts(w);
      if (w.status === 'shot_list_generating') {
        w = await pollUntilSettled(work.work_id, 'shot_list_generating');
        setWork(w); syncDrafts(w);
      }
      if (w.status === 'shot_list_regenerate_failed') setErr(w.error || '分镜生成失败');
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }

  async function lockConcept() {
    if (!work || !conceptDraft) return;
    setBusy(true); setErr(null);
    try {
      const w = await directorPipelineApi.lockConcept(work.work_id, conceptDraft);
      setWork(w); syncDrafts(w);
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

  async function lockShotList() {
    if (!work || !shotListDraft) return;
    setBusy(true); setErr(null);
    try {
      const w = await directorPipelineApi.lockShotList(work.work_id, shotListDraft);
      setWork(w); syncDrafts(w);
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

  function reset() {
    setWork(null); setMaterialText(''); setIntentHint(''); setErr(null);
    setConceptDraft(null); setScreenplayDraft(null); setDesignListDraft(null); setShotListDraft(null);
  }

  const lockedThrough = work?.locked_through ?? -1;
  const currentStageIdx = Math.min(lockedThrough + 1, 3);
  const producing = work && work.locked_through >= 3;

  return (
    <div className="tj dp">
      {!work && (
        <>
          <section className="tj-sec">
            <div className="tj-sec__head"><span className="tj-sec__num">·</span><h2>素材</h2></div>
            <label className="tj-field tj-field--tall">
              <span className="tj-field__label">原始素材（小说/大纲/一句话想法，{materialText.length} 字）</span>
              <textarea rows={10} placeholder="粘贴素材，AI 先生成①立意草稿供你审核…"
                value={materialText} onChange={e => setMaterialText(e.target.value)} />
            </label>
            <label className="tj-field">
              <span className="tj-field__label">用户意图提示（可选，如"目标观众/时长/风格倾向"）</span>
              <input value={intentHint} onChange={e => setIntentHint(e.target.value)} />
            </label>
          </section>
          <div className="tj-actions">
            <button type="button" className="tj-btn tj-btn--primary" onClick={start} disabled={busy}>
              {busy ? '生成中…' : '▶ 开始（生成①立意草稿）'}
            </button>
          </div>
        </>
      )}

      {err && <div className="tj-err">{err}</div>}

      {work && (
        <div className="dp-steps">
          {STAGE_LABELS.map((label, i) => (
            <span key={label} className="dp-step" data-state={i <= lockedThrough ? 'locked' : i === currentStageIdx ? 'active' : 'pending'}>
              {i <= lockedThrough ? `✓ ${label}` : label}
            </span>
          ))}
        </div>
      )}

      {work && lockedThrough < 0 && conceptDraft && (
        <ConceptStep
          draft={conceptDraft} onChange={setConceptDraft}
          onRegenerate={() => regenerate('concept')} onLock={lockConcept} busy={busy}
        />
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

      {work && lockedThrough === 2 && shotListDraft && (
        <ShotListStep
          draft={shotListDraft} onChange={setShotListDraft} designList={work.design_list}
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

// ── ①立意 ─────────────────────────────────────────────────────────────────

function ConceptStep({ draft, onChange, onRegenerate, onLock, busy }: {
  draft: DpConcept; onChange: (c: DpConcept) => void;
  onRegenerate: () => void; onLock: () => void; busy: boolean;
}) {
  const set = <K extends keyof DpConcept>(k: K, v: DpConcept[K]) => onChange({ ...draft, [k]: v });
  return (
    <div className="tj-progress">
      <label className="tj-field"><span className="tj-field__label">主题</span>
        <input value={draft.theme} onChange={e => set('theme', e.target.value)} /></label>
      <label className="tj-field"><span className="tj-field__label">基调</span>
        <input value={draft.tone} onChange={e => set('tone', e.target.value)} /></label>
      <label className="tj-field"><span className="tj-field__label">风格</span>
        <input value={draft.style} onChange={e => set('style', e.target.value)} /></label>
      <label className="tj-field"><span className="tj-field__label">目标观众</span>
        <input value={draft.target_audience} onChange={e => set('target_audience', e.target.value)} /></label>
      <label className="tj-field"><span className="tj-field__label">时长档</span>
        <select value={draft.duration_archetype} onChange={e => set('duration_archetype', e.target.value)}>
          {DURATION_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select></label>
      <label className="tj-field"><span className="tj-field__label">品质基准</span>
        <input value={draft.quality_bar} onChange={e => set('quality_bar', e.target.value)} /></label>
      <div className="tj-actions">
        <button type="button" className="tj-btn" onClick={onRegenerate} disabled={busy}>↻ 重新生成</button>
        <button type="button" className="tj-btn tj-btn--primary" onClick={onLock} disabled={busy}>
          {busy ? '处理中…' : '锁定立意，生成②剧本草稿'}
        </button>
      </div>
    </div>
  );
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
          {busy ? '建立资产中…' : '锁定设计清单（建立角色/场景/道具资产），生成④分镜草稿'}
        </button>
      </div>
    </div>
  );
}

// ── ④分镜头剧本 ────────────────────────────────────────────────────────────

function ShotListStep({ draft, onChange, designList, onRegenerate, onLock, busy }: {
  draft: DpShotList; onChange: (s: DpShotList) => void; designList: DpDesignList | null;
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
