/** Explainer Master v8: progressive research, human review, and delivery. */
'use client';

import { useEffect, useMemo, useState } from 'react';
import { explainerApi, presenterApi, taskApi } from '@/lib/api-client';
import { syncAuthToken } from '@/lib/auth-store';
import type {
  ExplainerCue,
  ExplainerResearchResponse,
  ExplainerScriptDraft,
  Presenter,
  TaskInfo,
} from '@/types/api';

type Stage = 'research' | 'review' | 'assemble';

const VISUAL_LABELS: Record<ExplainerCue['visual_type'], string> = {
  heygen_avatar: 'HeyGen 数字人',
  broll_news: '新闻 B-roll',
  browser_broll: '网页 B-roll（Browser Agent）',
  broll_stock: '素材 B-roll',
  data_screenshot: '数据截图',
  remotion_chart: 'Remotion 图表',
  remotion_code: 'Remotion 代码',
  voiceover: '旁白',
};

const EMPTY_CUE: ExplainerCue = {
  time_range: '00:00-00:05',
  visual_type: 'heygen_avatar',
  text: '',
  visual_config: {},
};

function hookText(hook: ExplainerResearchResponse['hooks'][number]): string {
  return typeof hook === 'string' ? hook : hook.text;
}

function hookRecommended(hook: ExplainerResearchResponse['hooks'][number]): boolean {
  return typeof hook !== 'string' && hook.recommended;
}

function hookAngle(hook: ExplainerResearchResponse['hooks'][number]): string {
  return typeof hook === 'string' ? '' : hook.angle;
}

export function ExplainerWorkbench() {
  const [stage, setStage] = useState<Stage>('research');
  const [topicOrUrl, setTopicOrUrl] = useState('');
  const [voiceProfile, setVoiceProfile] = useState('cosyvoice_default');
  const [presenterId, setPresenterId] = useState('');
  const [presenters, setPresenters] = useState<Presenter[]>([]);
  const [research, setResearch] = useState<ExplainerResearchResponse | null>(null);
  const [selectedHook, setSelectedHook] = useState('');
  const [selectedScriptId, setSelectedScriptId] = useState('');
  const [cues, setCues] = useState<ExplainerCue[]>([]);
  const [codeRender, setCodeRender] = useState(true);
  const [circleAvatar, setCircleAvatar] = useState(true);
  const [browserBroll, setBrowserBroll] = useState(true);
  const [aspectRatio, setAspectRatio] = useState<'9:16' | '16:9'>('9:16');
  const [taskId, setTaskId] = useState<string | null>(null);
  const [task, setTask] = useState<TaskInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    syncAuthToken();
    presenterApi.list().then(setPresenters).catch(() => setPresenters([]));
  }, []);

  useEffect(() => {
    if (!taskId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const current = await taskApi.get(taskId);
        if (cancelled) return;
        setTask(current);
        if (current.status !== 'completed' && current.status !== 'failed') {
          timer = setTimeout(poll, 3000);
        }
      } catch {
        if (!cancelled) timer = setTimeout(poll, 5000);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [taskId]);

  const selectedScript = useMemo(
    () => research?.scripts.find(script => script.id === selectedScriptId) ?? null,
    [research, selectedScriptId],
  );

  function selectScript(script: ExplainerScriptDraft) {
    setSelectedScriptId(script.id);
    setCues(script.cues.map(cue => ({ ...cue, visual_config: { ...(cue.visual_config ?? {}) } })));
  }

  async function startResearch() {
    if (!topicOrUrl.trim()) {
      setError('请输入选题、参考文章或 URL');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await explainerApi.research({
        topic_or_url: topicOrUrl,
        voice_profile: voiceProfile,
        heygen_presenter_id: presenterId || null,
      });
      setResearch(result);
      const recommendedHook = result.hooks.find(hookRecommended);
      setSelectedHook(recommendedHook ? hookText(recommendedHook) : result.hooks[0] ? hookText(result.hooks[0]) : '');
      if (result.scripts[0]) selectScript(result.scripts[0]);
      setStage('review');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '研究服务不可用');
    } finally {
      setBusy(false);
    }
  }

  async function startAssembly() {
    if (!research || !selectedHook || cues.some(cue => !cue.text.trim())) {
      setError('请先选择 Hook，并补全所有视觉脚手架旁白');
      return;
    }
    if (cues.some(cue => cue.visual_type === 'heygen_avatar') && !presenterId) {
      setError('当前脚本包含 HeyGen 数字人，请先选择数字人');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const accepted = await explainerApi.assemble({
        topic_or_url: topicOrUrl,
        voice_profile: voiceProfile,
        heygen_presenter_id: presenterId || null,
        selected_hook: selectedHook,
        final_script_cues: cues,
        enable_remotion_code_render: codeRender,
        enable_circle_avatar_mask: circleAvatar,
        enable_browser_broll: browserBroll,
        aspect_ratio: aspectRatio,
      });
      setTaskId(accepted.task_id);
      setTask(null);
      setStage('assemble');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '装配任务提交失败');
    } finally {
      setBusy(false);
    }
  }

  function updateCue(index: number, patch: Partial<ExplainerCue>) {
    setCues(previous => previous.map((cue, cueIndex) => cueIndex === index ? { ...cue, ...patch } : cue));
  }

  return (
    <div className="ex-v6">
      <header className="ex-v6__hero">
        <p className="ex-v6__eyebrow">HEVI · EXPLAINER MASTER v8.0</p>
        <h1>解说中心 · 深度解说工厂</h1>
        <p>研究事实，人工确稿，再用电视级装配完成一条可核验的解说视频。</p>
      </header>

      <nav className="ex-v6__steps" aria-label="解说生产阶段">
        {([
          ['research', '01', '选题与偏好'],
          ['review', '02', '人工确稿'],
          ['assemble', '03', '渲染与交付'],
        ] as const).map(([id, number, label]) => (
          <button key={id} type="button" className={stage === id ? 'is-active' : ''}
            onClick={() => id !== 'assemble' && setStage(id)} disabled={id === 'review' && !research}>
            <span>{number}</span>{label}
          </button>
        ))}
      </nav>

      {stage === 'research' && (
        <section className="ex-v6__panel" aria-labelledby="research-title">
          <div className="ex-v6__panel-title"><span>01</span><div><h2 id="research-title">选题与偏好配置</h2><p>GPT Researcher / LLM 提炼事实，并生成 5 个 Hook、3 版视觉脚手架。</p></div></div>
          <label className="ex-v6__field ex-v6__field--full">
            <span>选题 / 解说材料</span>
            <textarea value={topicOrUrl} onChange={event => setTopicOrUrl(event.target.value)} rows={5}
              placeholder="输入一句话主题，或粘贴参考文章 / URL…" />
          </label>
          <div className="ex-v6__grid">
            <label className="ex-v6__field"><span>语音克隆音色</span><select value={voiceProfile} onChange={event => setVoiceProfile(event.target.value)}>
              <option value="cosyvoice_default">CosyVoice 默认音色</option><option value="cosyvoice_laowang">CosyVoice 老王音色</option><option value="edge_tts_zh">Edge TTS（可观测降级）</option>
            </select></label>
            <label className="ex-v6__field"><span>开闭幕数字人</span><select value={presenterId} onChange={event => setPresenterId(event.target.value)}>
              <option value="">不使用 / 由脚本决定</option>{presenters.map(presenter => <option key={presenter.id} value={presenter.id}>{presenter.name}</option>)}
            </select></label>
          </div>
          <div className="ex-v6__toggles"><label><input type="checkbox" checked={browserBroll} onChange={event => setBrowserBroll(event.target.checked)} /> 自动录制网页 B-roll</label><label><input type="checkbox" checked={codeRender} onChange={event => setCodeRender(event.target.checked)} /> 自动渲染代码 / 数据图表</label><label><input type="checkbox" checked={circleAvatar} onChange={event => setCircleAvatar(event.target.checked)} /> 动态圆形头像蒙版</label><label>画幅 <select value={aspectRatio} onChange={event => setAspectRatio(event.target.value as '9:16' | '16:9')}><option value="9:16">9:16 竖屏</option><option value="16:9">16:9 横屏</option></select></label></div>
          <button type="button" className="ex-v6__primary" onClick={startResearch} disabled={busy}>{busy ? '研究与生成中…' : '🔍 启动联网调研与 3 版脚本生成'}</button>
        </section>
      )}

      {stage === 'review' && research && (
        <section className="ex-v6__panel" aria-labelledby="review-title">
          <div className="ex-v6__panel-title"><span>02</span><div><h2 id="review-title">人工确稿与视觉脚手架审查</h2><p>事实来源保留在研究结果中，最终文案和镜头 cue 由你确认。</p></div></div>
          <div className="ex-v6__facts"><h3>研究事实</h3>{research.facts.map((fact, index) => <div key={`${fact.claim}-${index}`}><span>{Math.round(fact.confidence * 100)}%</span><p>{fact.claim}</p><small>{fact.source ?? '未提供来源'}</small></div>)}</div>
          <div className="ex-v6__hooks"><h3>选择 Hook 抓手</h3>{research.hooks.map((hook, index) => <label key={`${hookText(hook)}-${index}`}><input type="radio" name="explainer-hook" checked={selectedHook === hookText(hook)} onChange={() => setSelectedHook(hookText(hook))} /> <strong>Hook {index + 1}</strong> {hookText(hook)}<small>{hookAngle(hook)}{hookRecommended(hook) ? ' · 推荐' : ''}</small></label>)}</div>
          <div className="ex-v6__scripts"><h3>选择脚本视角</h3>{research.scripts.map(script => <button type="button" key={script.id} className={selectedScriptId === script.id ? 'is-selected' : ''} onClick={() => selectScript(script)}><strong>{script.title}</strong><span>{script.viewpoint}</span></button>)}</div>
          {selectedScript && <div className="ex-v6__cues"><h3>确稿编辑器 · 视觉脚手架</h3>{cues.map((cue, index) => <div className="ex-v6__cue" key={`${cue.time_range}-${index}`}><input aria-label={`时间 ${index + 1}`} value={cue.time_range} onChange={event => updateCue(index, { time_range: event.target.value })} /><select aria-label={`画面类型 ${index + 1}`} value={cue.visual_type} onChange={event => updateCue(index, { visual_type: event.target.value as ExplainerCue['visual_type'] })}>{Object.entries(VISUAL_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><textarea aria-label={`旁白 ${index + 1}`} value={cue.text} rows={2} onChange={event => updateCue(index, { text: event.target.value })} />{cue.visual_type === 'browser_broll' && <input aria-label={`网页地址 ${index + 1}`} placeholder="https://官方来源…" value={cue.target_url ?? ''} onChange={event => updateCue(index, { target_url: event.target.value })} />}</div>)}<button type="button" className="ex-v6__add" onClick={() => setCues(previous => [...previous, { ...EMPTY_CUE }])}>＋ 添加 cue</button></div>}
          <div className="ex-v6__actions"><button type="button" className="ex-v6__secondary" onClick={() => setStage('research')}>返回修改偏好</button><button type="button" className="ex-v6__primary" onClick={startAssembly} disabled={busy}>{busy ? '提交装配中…' : '🚀 确认文案与脚手架，启动全自动装配出片'}</button></div>
        </section>
      )}

      {stage === 'assemble' && (
        <section className="ex-v6__panel" aria-labelledby="assemble-title">
          <div className="ex-v6__panel-title"><span>03</span><div><h2 id="assemble-title">全自动渲染与交付</h2><p>Task → oservi → omodul 装配事务；每一步都有可追踪状态和真实产物。</p></div></div>
          <div className="ex-v6__progress"><div className="ex-v6__progress-head"><strong>{task?.status === 'completed' ? '✓ 成片已完成' : task?.status === 'failed' ? '✗ 装配失败' : '⟳ Remotion 正在渲染中…'}</strong><span>任务 {taskId?.slice(0, 8)}</span></div><div className="ex-v6__bar"><i style={{ width: `${Math.max(5, task?.percent ?? 5)}%` }} /></div><p>{task?.stage ?? '已提交，等待生产任务调度'}</p></div>
          {task?.status === 'completed' && <div className="ex-v6__delivery"><h3>🎬 可下载产物</h3><a href={taskApi.videoUrl(task.task_id)} download>⬇ 下载竖屏成片</a><p>产物由 ArtifactManifest 校验后提供，路径：{task.result_video_path}</p></div>}
          {task?.status === 'failed' && <div className="ex-v6__error">{task.error ?? '装配失败，请查看任务详情'}</div>}
        </section>
      )}
      {error && <div className="ex-v6__error" role="alert">{error}</div>}
    </div>
  );
}
