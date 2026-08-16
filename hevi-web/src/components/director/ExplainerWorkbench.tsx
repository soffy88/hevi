/** Explainer Master v8: progressive research, human review, and delivery. */
'use client';

import { useEffect, useMemo, useState } from 'react';
import { explainerApi, presenterApi, taskApi } from '@/lib/api-client';
import { useFaceValidator } from '@/hooks/useFaceValidator';
import { syncAuthToken } from '@/lib/auth-store';
import type {
  ExplainerCue,
  ExplainerHookNode,
  ExplainerResearchResponse,
  ExplainerScriptDraft,
  HookNarrativeFunction,
  Presenter,
  TaskInfo,
} from '@/types/api';

type Stage = 'research' | 'review' | 'assemble';

const VISUAL_LABELS: Record<ExplainerCue['visual_type'], string> = {
  heygen_avatar: '数字人出镜（自动 Provider）',
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

// v9: Hook 策略矩阵 —— 叙事功能档位标签与递进顺序。
const NARRATIVE_LABELS: Record<HookNarrativeFunction, string> = {
  opening_suspense: '开场总悬念',
  mid_conflict: '中段转折/冲突',
  climax_breakthrough: '高潮解答',
};

function formatPlacement(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const mm = String(Math.floor(total / 60)).padStart(2, '0');
  const ss = String(total % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

/** 确稿台快照:刷新/返回页面时从 sessionStorage 瞬时恢复现场,绝不重新跑研究。 */
interface ExplainerSnapshot {
  research: ExplainerResearchResponse;
  selectedHookIds: string[];
  hookMode: 'chain' | 'fusion';
  selectedScriptId: string;
  cues: ExplainerCue[];
  stage: Stage;
  durationMode?: string;
  customMinutes?: string;
}

const STATE_KEY = 'hevi_explainer_state';

export function ExplainerWorkbench() {
  const [stage, setStage] = useState<Stage>('research');
  const [topicOrUrl, setTopicOrUrl] = useState('');
  // 精准目标时长:4 档预设 + 自定义("1-3"/"3-6"/"6-10"/"10-15"/"custom")。
  const [durationMode, setDurationMode] = useState('1-3');
  const [customMinutes, setCustomMinutes] = useState('');
  const [voiceProfile, setVoiceProfile] = useState('cosyvoice_default');
  const [presenterId, setPresenterId] = useState('');
  const [presenters, setPresenters] = useState<Presenter[]>([]);
  const [presenterBusy, setPresenterBusy] = useState(false);
  const [presenterNotice, setPresenterNotice] = useState('');
  const [research, setResearch] = useState<ExplainerResearchResponse | null>(null);
  const [selectedHookIds, setSelectedHookIds] = useState<string[]>([]);
  const [hookMode, setHookMode] = useState<'chain' | 'fusion'>('chain');
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
  // 研究进行中的进度文案(绿色中性态,与红色 error 区分):轮询时的“已用时 Ns”。
  const [researchInfo, setResearchInfo] = useState<string | null>(null);
  // 阶段三装配提交失败标记:驱动错误下方的 [🔄 重新提交装配] 按钮。
  const [assembleFailed, setAssembleFailed] = useState(false);
  // 断点续传恢复提示(独立于数字人 notice,避免被 presenter 加载覆盖)。
  const [restoreNotice, setRestoreNotice] = useState<string | null>(null);
  // v9.1: 数字人母体照片(Dropzone 上传 → 浏览器 AI 预检 → 服务端复核)。
  const [presenterImageFile, setPresenterImageFile] = useState<File | null>(null);
  const [presenterImageUrl, setPresenterImageUrl] = useState('');
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadNotice, setUploadNotice] = useState<string | null>(null);
  // v9.1: 15 秒先导样片 —— 提交前先出一段 15s 样片看质感,不浪费全量渲染。
  const [previewMode, setPreviewMode] = useState(false);
  const faceValidator = useFaceValidator();

  useEffect(() => {
    syncAuthToken();
    let active = true;
    const loadPresenter = async () => {
      setPresenterBusy(true);
      try {
        let items = await presenterApi.list();
        let notice = '';
        if (items.length === 0) {
          const created = await presenterApi.ensureDefault();
          items = [created];
          notice = `已自动创建并选择「${created.name}」`;
        }
        if (!active) return;
        setPresenters(items);
        setPresenterId(items[0]?.id ?? '');
        setPresenterNotice(notice || (items[0] ? `已自动选择「${items[0].name}」` : ''));
      } catch (reason) {
        if (!active) return;
        setPresenters([]);
        setError(reason instanceof Error ? reason.message : '数字人自动配置失败');
      } finally {
        if (active) setPresenterBusy(false);
      }
    };
    void loadPresenter();
    return () => { active = false; };
  }, []);

  // 断点续传:刷新/返回页面时先瞬时恢复本地 sessionStorage 快照(调研结果+3 版
  // 脚本+Hook 链选择+当前 step),再异步向服务端缓存核对——绝对不需要重跑研究。
  useEffect(() => {
    let active = true;
    const applySnapshot = (snapshot: ExplainerSnapshot) => {
      setResearch(snapshot.research);
      setTopicOrUrl(snapshot.research.topic_or_url);
      setDurationMode(snapshot.durationMode ?? '1-3');
      setCustomMinutes(snapshot.customMinutes ?? '');
      setSelectedHookIds(snapshot.selectedHookIds?.length
        ? snapshot.selectedHookIds
        : snapshot.research.hooks.map(hook => hook.hook_id));
      setHookMode(snapshot.hookMode ?? 'chain');
      const script = snapshot.research.scripts.find(item => item.id === snapshot.selectedScriptId)
        ?? snapshot.research.scripts[0];
      if (script) selectScript(script);
      if (snapshot.cues?.length) setCues(snapshot.cues);
      setStage(snapshot.stage === 'assemble' ? 'review' : (snapshot.stage ?? 'review'));
      setError(null);
      setRestoreNotice('已从本地缓存恢复确稿台(无需重跑研究)');
    };
    const raw = window.sessionStorage.getItem(STATE_KEY);
    if (raw) {
      try {
        const snapshot = JSON.parse(raw) as ExplainerSnapshot;
        if (snapshot.research?.hooks?.length) {
          applySnapshot(snapshot);
        } else {
          window.sessionStorage.removeItem(STATE_KEY);
        }
      } catch {
        window.sessionStorage.removeItem(STATE_KEY);
      }
    }
    // 服务端缓存兜底:本地无快照但留有 session_id(旧会话/跨标签页)时恢复。
    const sessionId = window.sessionStorage.getItem('hevi_explainer_session');
    if (sessionId && !raw) {
      const restore = async () => {
        try {
          const cached = await explainerApi.researchCache(sessionId);
          if (!active) return;
          // 只恢复 ready 的研究;processing/failed 留到用户重试。
          if (cached.status !== 'ready' || cached.payload == null) return;
          applySnapshot({
            research: cached.payload,
            selectedHookIds: cached.payload.hooks.map(hook => hook.hook_id),
            hookMode: 'chain',
            selectedScriptId: cached.payload.scripts[0]?.id ?? '',
            cues: [],
            stage: 'review',
          });
        } catch {
          if (!active) return;
          // 缓存失效(404/损坏):清掉本地标记,回到全新研究流程。
          window.sessionStorage.removeItem('hevi_explainer_session');
        }
      };
      void restore();
    }
    return () => { active = false; };
  }, []);

  // 确稿台快照持久化:调研结果/3 版脚本/Hook 选择/当前 step 落 sessionStorage;
  // 装配中(step=assemble)不持久化任务瞬时态,刷新后回到确稿台而非空任务页。
  useEffect(() => {
    if (!research) return;
    const snapshot: ExplainerSnapshot = {
      research,
      selectedHookIds,
      hookMode,
      selectedScriptId,
      cues,
      stage,
      durationMode,
      customMinutes,
    };
    window.sessionStorage.setItem(STATE_KEY, JSON.stringify(snapshot));
  }, [research, selectedHookIds, hookMode, selectedScriptId, cues, stage, durationMode, customMinutes]);

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
  // v9: 选中的 Hook 节点按建议切入时间排序,构成 Hook Chain 导览。
  const selectedHooks = useMemo(() => {
    const byId = new Map(
      (research?.hooks ?? []).map((hook, index) => [hook.hook_id || `H${index + 1}`, hook]),
    );
    return selectedHookIds
      .map(id => byId.get(id))
      .filter((hook): hook is ExplainerHookNode => Boolean(hook))
      .sort((a, b) => a.suggested_placement_s - b.suggested_placement_s);
  }, [research, selectedHookIds]);
  const hasAvatarCue = useMemo(
    () => cues.some(cue => cue.visual_type === 'heygen_avatar'),
    [cues],
  );

  async function ensurePresenter(): Promise<string> {
    if (presenterId) return presenterId;
    setPresenterBusy(true);
    try {
      let items = presenters.length > 0 ? presenters : await presenterApi.list();
      if (items.length === 0) {
        const created = await presenterApi.ensureDefault();
        items = [created];
        setPresenterNotice(`已自动创建并选择「${created.name}」`);
      }
      const selected = items[0];
      if (!selected) throw new Error('数字人自动创建失败');
      setPresenters(items);
      setPresenterId(selected.id);
      if (!presenterNotice) setPresenterNotice(`已自动选择「${selected.name}」`);
      return selected.id;
    } finally {
      setPresenterBusy(false);
    }
  }

  function selectScript(script: ExplainerScriptDraft) {
    setSelectedScriptId(script.id);
    setCues(script.cues.map(cue => ({ ...cue, visual_config: { ...(cue.visual_config ?? {}) } })));
  }

  function toggleHook(hookId: string) {
    setSelectedHookIds(previous =>
      previous.includes(hookId)
        ? previous.filter(id => id !== hookId)
        : [...previous, hookId],
    );
  }

  /** 把 4 档预设 / 自定义时长解析成后端 target_duration 字符串;非法时返回 null。 */
  function resolveTargetDuration(): string | null {
    if (durationMode !== 'custom') return durationMode;
    const value = customMinutes.trim();
    if (!value || Number.isNaN(Number(value)) || Number(value) <= 0) return null;
    return value;
  }

  async function startResearch() {
    if (!topicOrUrl.trim()) {
      setError('请输入选题、参考文章或 URL');
      return;
    }
    const targetDuration = resolveTargetDuration();
    if (!targetDuration) {
      setError('请输入有效的自定义时长(分钟)');
      return;
    }
    setBusy(true);
    setError(null);
    setResearchInfo(null);
    try {
      // 异步研究:POST 立即返 202 + processing 信封,前端轮询 GET 拿结果。
      // 长视频分章生成动辄几百秒,不再让同步 HTTP 撞 Cloudflare 524。
      const job = await explainerApi.research({
        topic_or_url: topicOrUrl,
        voice_profile: voiceProfile,
        heygen_presenter_id: null,
        target_duration: targetDuration,
        session_id: window.sessionStorage.getItem('hevi_explainer_session') ?? undefined,
      });
      window.sessionStorage.setItem('hevi_explainer_session', job.session_id);
      const result = await pollResearchJob(job.session_id);
      if (!result) {  // failed:错误已在 setError 提示
        setBusy(false);
        return;
      }
      setResearch(result);
      setRestoreNotice(null);
      setResearchInfo(null);
      // v9: 默认全选矩阵节点组成 Hook Chain,确稿台可按需增删。
      setSelectedHookIds(result.hooks.map(hook => hook.hook_id));
      if (result.scripts[0]) selectScript(result.scripts[0]);
      setStage('review');
      // 断点续传:响应里带回 session_id,已落 sessionStorage,刷新后从缓存恢复。
    } catch (reason) {
      setResearchInfo(null);
      const msg = reason instanceof Error ? reason.message : '研究服务不可用';
      if (/Failed to fetch|NetworkError|load failed|network/i.test(msg)) {
        // 网络层抖动(代理 reset 等):后台可能已开始,刷新后可从缓存恢复。
        setError('与服务器连接中断(可能是网络抖动)。后台研究可能仍在进行,刷新页面后可从缓存恢复确稿。');
      } else {
        setError(msg);
      }
    } finally {
      setBusy(false);
    }
  }

  // 轮询研究任务信封直到 ready/failed:ready 返回确稿 payload,failed 上报错误返 null。
  // 对网络层抖动(代理 reset / Failed to fetch)容错:后台任务和信封存活不受
  // 前端连接影响,連续若干次拿不到状态才认输,不能一抖就报红。
  async function pollResearchJob(sessionId: string): Promise<ExplainerResearchResponse | null> {
    const started = Date.now();
    // 超时兑底:長视频最多等 25 分钟(分章生成 + 本地慢模型)。
    const deadline = started + 25 * 60 * 1000;
    let consecutiveNetErrors = 0;
    while (Date.now() < deadline) {
      let job;
      try {
        job = await explainerApi.researchCache(sessionId);
        consecutiveNetErrors = 0;
      } catch (reason) {
        // 网络层抖动(Failed to fetch / 代理 reset):后台仍在跑,继续等。
        consecutiveNetErrors += 1;
        const elapsed = Math.floor((Date.now() - started) / 1000);
        setResearchInfo(`研究后台仍在进行(已用时 ${elapsed}s),网络短暂中断中,正在重试……`);
        if (consecutiveNetErrors >= 20) {
          setResearchInfo(null);
          setError(reason instanceof Error ? reason.message : '与服务器连接持续中断,请检查网络后重试');
          return null;
        }
        await new Promise(resolve => setTimeout(resolve, 5000));
        continue;
      }
      if (job.status === 'ready' && job.payload) {
        setError(null);
        setResearchInfo(null);
        return job.payload;
      }
      if (job.status === 'failed') {
        setResearchInfo(null);
        setError(job.error ?? '研究失败,请重试');
        return null;
      }
      // 进度文案(绿色中性态,与红色 error 区分):让用户知道在跑、不是卡死。
      const elapsed = Math.floor((Date.now() - started) / 1000);
      setResearchInfo(`正在深度研究素材并拆解多视角脚本……已用时 ${elapsed}s`);
      await new Promise(resolve => setTimeout(resolve, 3000));
    }
    setResearchInfo(null);
    setError('研究超时(>25 分钟),请重试');
    return null;
  }

  async function startAssembly() {
    if (!research || selectedHooks.length === 0) {
      setError('请至少选择一个 Hook 节点构建叙事链，并补全所有视觉脚手架旁白');
      return;
    }
    if (cues.some(cue => !cue.text.trim())) {
      setError('请补全所有视觉脚手架旁白');
      return;
    }
    let resolvedPresenterId = presenterId;
    if (hasAvatarCue && !resolvedPresenterId) {
      try {
        resolvedPresenterId = await ensurePresenter();
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : '数字人自动创建失败');
        return;
      }
    }
    setBusy(true);
    setError(null);
    setAssembleFailed(false);
    try {
      const accepted = await explainerApi.assemble({
        topic_or_url: topicOrUrl,
        voice_profile: voiceProfile,
        presenter_id: resolvedPresenterId || null,
        heygen_presenter_id: null,
        selected_hook: selectedHooks[0]?.text ?? '',
        selected_hooks: selectedHooks.map(hook => hook.text),
        hook_combination: hookMode,
        final_script_cues: cues,
        enable_remotion_code_render: codeRender,
        enable_circle_avatar_mask: circleAvatar,
        enable_browser_broll: browserBroll,
        aspect_ratio: aspectRatio,
        session_id: research.session_id || (window.sessionStorage.getItem('hevi_explainer_session') ?? undefined),
        presenter_image_url: presenterImageUrl || undefined,
        preview_mode: previewMode,
      });
      setTaskId(accepted.task_id);
      setTask(null);
      setStage('assemble');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '装配任务提交失败');
      setAssembleFailed(true);
    } finally {
      setBusy(false);
    }
  }

  function updateCue(index: number, patch: Partial<ExplainerCue>) {
    setCues(previous => previous.map((cue, cueIndex) => cueIndex === index ? { ...cue, ...patch } : cue));
  }

  // v9.1: Dropzone 选中/拖入文件 → 浏览器 AI 预检(TinyFaceDetector)。
  async function handlePresenterFile(file: File | null) {
    setUploadNotice(null);
    setPresenterImageFile(file);
    if (!file) return;
    const verdict = await faceValidator.validate(file);
    if (!verdict.isValid && verdict.errorMsg) {
      setUploadNotice(verdict.errorMsg);
    }
  }

  // 预览 blob URL 只创建一次(避免每次渲染都新建对象 URL 泄漏内存)。
  const presenterPreviewUrl = useMemo(
    () => (presenterImageFile ? URL.createObjectURL(presenterImageFile) : ''),
    [presenterImageFile],
  );

  // v9.1: 上传并确认 —— 服务端权威复核(与本地预检同规则),通过后锁定底图。
  async function confirmPresenterUpload() {
    if (!presenterImageFile || !faceValidator.result.isValid) return;
    setUploadBusy(true);
    setUploadNotice(null);
    try {
      const uploaded = await explainerApi.uploadPresenterImage(presenterImageFile);
      if (!uploaded.valid) {
        setUploadNotice(uploaded.reason || '底图未通过服务端质检,请换一张');
        return;
      }
      setPresenterImageUrl(uploaded.reason);
      setUploadNotice('✓ 底图已上传并通过质检,将作为全时段解说员母体');
    } catch (reason) {
      setUploadNotice(reason instanceof Error ? reason.message : '底图上传失败,请重试');
    } finally {
      setUploadBusy(false);
    }
  }

  return (
    <div className="ex-v6">
      <header className="ex-v6__hero">
        <p className="ex-v6__eyebrow">HEVI · EXPLAINER MASTER v9.0</p>
        <h1>解说中心 · 深度解说工厂</h1>
        <p>研究事实，人工确稿，再用电视级装配完成一条可核验的解说视频。</p>
      </header>
      {restoreNotice && <div className="ex-v6__restore" role="status">{restoreNotice}</div>}

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
          <div className="ex-v6__panel-title"><span>01</span><div><h2 id="research-title">选题与偏好配置</h2><p>GPT Researcher / LLM 提炼事实，并从主题知识图谱生成递进式 Hook 矩阵与视觉脚手架。</p></div></div>
          <label className="ex-v6__field ex-v6__field--full">
            <span>选题 / 解说材料</span>
            <textarea value={topicOrUrl} onChange={event => setTopicOrUrl(event.target.value)} rows={5}
              placeholder="输入一句话主题，或粘贴参考文章 / URL…" />
          </label>
          <div className="ex-v6__grid">
            <label className="ex-v6__field"><span>语音克隆音色</span><select value={voiceProfile} onChange={event => setVoiceProfile(event.target.value)}>
              <option value="cosyvoice_default">CosyVoice 默认音色</option><option value="cosyvoice_laowang">CosyVoice 老王音色</option><option value="edge_tts_zh">Edge TTS（可观测降级）</option>
            </select></label>
            <label className="ex-v6__field"><span>开闭幕数字人（自动选择）</span><select value={presenterId} onChange={event => { setPresenterId(event.target.value); setPresenterNotice(''); }} disabled={presenterBusy}>
              <option value="">{presenterBusy ? '正在自动配置数字人…' : '自动选择 / 自动创建'}</option>{presenters.map(presenter => <option key={presenter.id} value={presenter.id}>{presenter.name}</option>)}
            </select>{presenterNotice && <small>{presenterNotice}</small>}</label>
          </div>
          <div className="ex-v6__duration">
            <span className="ex-v6__duration-label">目标时长（按约 250 字/分钟动态计算字数与段落数）</span>
            <div className="ex-v6__duration-options">
              {([
                ['1-3', '1-3 分钟 · 深度解析'],
                ['3-6', '3-6 分钟 · 硬核长文'],
                ['6-10', '6-10 分钟 · 学术解说'],
                ['10-15', '10-15 分钟 · 纪录片级'],
              ] as const).map(([value, label]) => (
                <label key={value} className={durationMode === value ? 'is-active' : ''}>
                  <input type="radio" name="explainer-duration" value={value} checked={durationMode === value} onChange={() => setDurationMode(value)} />
                  <span>{label}</span>
                </label>
              ))}
              <label className={durationMode === 'custom' ? 'is-active' : ''}>
                <input type="radio" name="explainer-duration" value="custom" checked={durationMode === 'custom'} onChange={() => setDurationMode('custom')} />
                <span>自填任意时长</span>
              </label>
              {durationMode === 'custom' && (
                <input aria-label="自定义目标时长(分钟)" type="number" min={1} placeholder="分钟数，如 20" value={customMinutes} onChange={event => setCustomMinutes(event.target.value)} />
              )}
            </div>
          </div>
          <div className="ex-v6__toggles"><label><input type="checkbox" checked={browserBroll} onChange={event => setBrowserBroll(event.target.checked)} /> 自动录制网页 B-roll</label><label><input type="checkbox" checked={codeRender} onChange={event => setCodeRender(event.target.checked)} /> 自动渲染代码 / 数据图表</label><label><input type="checkbox" checked={circleAvatar} onChange={event => setCircleAvatar(event.target.checked)} /> 动态圆形头像蒙版</label><label>画幅 <select value={aspectRatio} onChange={event => setAspectRatio(event.target.value as '9:16' | '16:9')}><option value="9:16">9:16 竖屏</option><option value="16:9">16:9 横屏</option></select></label></div>
          <button type="button" className="ex-v6__primary" onClick={startResearch} disabled={busy || presenterBusy}>{busy ? '研究与生成中…' : '🔍 启动联网调研与脚本生成'}</button>
        </section>
      )}

      {stage === 'review' && research && (
        <section className="ex-v6__panel" aria-labelledby="review-title">
          <div className="ex-v6__panel-title"><span>02</span><div><h2 id="review-title">人工确稿与视觉脚手架审查</h2><p>事实来源保留在研究结果中，最终文案和镜头 cue 由你确认。</p></div></div>
          <div className="ex-v6__facts"><h3>研究事实</h3>{research.facts.map((fact, index) => <div key={`${fact.claim}-${index}`}><span>{Math.round(fact.confidence * 100)}%</span><p>{fact.claim}</p><small>{fact.source ?? '未提供来源'}</small></div>)}</div>
          <div className="ex-v6__hooks">
            <div className="ex-v6__hooks-head">
              <div><h3>Hook 组合策略</h3><p>根据主题实际需要选择或组合；每个节点绑定一个叙事功能档位，按时间递进。</p></div>
              <div className="ex-v6__hooks-bulk"><button type="button" onClick={() => setSelectedHookIds(research.hooks.map(hook => hook.hook_id))}>全选</button><button type="button" onClick={() => setSelectedHookIds([])}>清空</button><span>{selectedHooks.length}/{research.hooks.length} 已选</span></div>
            </div>
            {research.hooks.map((hook, index) => {
              const hookId = hook.hook_id;
              const checked = selectedHookIds.includes(hookId);
              return (
                <label key={hookId} className={checked ? 'is-selected' : ''}>
                  <input type="checkbox" name="explainer-hook" checked={checked} onChange={() => toggleHook(hookId)} />
                  <span className="ex-v6__hook-index">Hook {index + 1}</span>
                  <span className="ex-v6__hook-body">
                    <strong>{hook.title || hook.text}</strong>
                    <span className="ex-v6__hook-text">{hook.text}</span>
                    <span className="ex-v6__hook-meta">
                      <em className={`ex-v6__hook-fn is-${hook.narrative_function}`}>{NARRATIVE_LABELS[hook.narrative_function]}</em>
                      <i>切入 {formatPlacement(hook.suggested_placement_s)}</i>
                      {(hook.associated_concepts ?? []).map(concept => <b key={concept}>{concept}</b>)}
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
          <div className="ex-v6__hook-mode">
            <div><h3>组合模式</h3><p>串联贯穿把各档位按时间依次铺进全片；融合则把全部矛盾浓缩为单一开场。</p></div>
            <label className={hookMode === 'chain' ? 'is-active' : ''}>
              <input type="radio" name="explainer-hook-mode" checked={hookMode === 'chain'} onChange={() => setHookMode('chain')} />
              <span><strong>串联贯穿模式</strong><small>Hook Chain —— 悬念 → 冲突 → 解答，三档依次进入</small></span>
            </label>
            <label className={hookMode === 'fusion' ? 'is-active' : ''}>
              <input type="radio" name="explainer-hook-mode" checked={hookMode === 'fusion'} onChange={() => setHookMode('fusion')} />
              <span><strong>融合成单一开场</strong><small>Fusion —— 全部 Hook 浓缩为开场 30 秒的单一悬念段</small></span>
            </label>
          </div>
          <div className="ex-v6__hook-chain">
            <h3>{hookMode === 'chain' ? '串联后的脚本导览 · Hook Chain Preview' : '融合开场预览 · Fusion Preview'}</h3>
            {hookMode === 'chain' ? (
              <ol>
                {selectedHooks.map((hook, index) => {
                  const next = selectedHooks[index + 1];
                  const start = formatPlacement(hook.suggested_placement_s);
                  const end = next
                    ? formatPlacement(next.suggested_placement_s)
                    : formatPlacement(hook.suggested_placement_s + 15);
                  return (
                    <li key={hook.hook_id}>
                      <code>[{start}-{end}]</code>
                      <span>Hook {index + 1} · {NARRATIVE_LABELS[hook.narrative_function]}</span>
                      <p>{hook.text}</p>
                    </li>
                  );
                })}
                {selectedHooks.length === 0 && <li className="ex-v6__hook-chain-empty">还没有选择 Hook —— 勾选上方矩阵节点后，这里会生成串联导览。</li>}
              </ol>
            ) : (
              <p className="ex-v6__hook-chain-fusion">
                {selectedHooks.length === 0
                  ? '还没有选择 Hook。'
                  : `将 ${selectedHooks.map((hook, index) => `${index + 1}.「${hook.text}」`).join(' ')} 浓缩为一段 30 秒的开场悬念，一次性抛出全部核心矛盾。`}
              </p>
            )}
          </div>
          <div className="ex-v6__scripts"><h3>选择脚本视角</h3>{research.scripts.map(script => <button type="button" key={script.id} className={selectedScriptId === script.id ? 'is-selected' : ''} onClick={() => selectScript(script)}><strong>{script.title}</strong><span>{script.viewpoint}</span></button>)}</div>
          {hasAvatarCue && (
            <div className="ex-v6__presenter">
              <div><h3>出镜数字人</h3><p>已自动选择；没有预设时系统会创建本地可渲染数字人。你也可以在这里切换。</p></div>
              <select aria-label="第二步出镜数字人" value={presenterId} onChange={event => { setPresenterId(event.target.value); setPresenterNotice(''); }} disabled={presenterBusy}><option value="">自动选择 / 自动创建</option>{presenters.map(presenter => <option key={presenter.id} value={presenter.id}>{presenter.name}</option>)}</select>
              {presenterNotice && <small>{presenterNotice}</small>}

              {/* v9.1: 母体照片 Dropzone —— 浏览器 AI 预检 + 服务端复核双保险。 */}
              <div className="ex-v6__avatar">
                <div className="ex-v6__avatar-head">
                  <div><h3>数字人母体照片（全时段 Talking Face 底轨）</h3><p>拖入或点击选择一张 JPG/PNG（≤10MB），系统自动做 AI 素材质检。</p></div>
                  {presenterImageUrl && <em className="ex-v6__avatar-locked">✓ 已锁定底图</em>}
                </div>
                <label
                  className={`ex-v6__dropzone${faceValidator.result.isValid ? ' is-valid' : ''}${faceValidator.result.errorMsg ? ' is-invalid' : ''}`}
                  onDragOver={event => event.preventDefault()}
                  onDrop={event => {
                    event.preventDefault();
                    const file = event.dataTransfer.files?.[0] ?? null;
                    void handlePresenterFile(file);
                  }}
                >
                  <input
                    type="file"
                    accept="image/jpeg,image/png"
                    onChange={event => { const file = event.target.files?.[0] ?? null; void handlePresenterFile(file); }}
                  />
                  {presenterImageFile ? (
                    <>
                      <img src={presenterPreviewUrl} alt="预览" className="ex-v6__dropzone-preview" />
                      <span>
                        {faceValidator.result.isLoading
                          ? '正在进行 AI 素材质检…'
                          : faceValidator.result.isValid
                            ? `✅ AI 校验通过（${Math.round((faceValidator.result.faceRatio ?? 0) * 100)}% 人脸占比）`
                            : '⚠ 未通过校验，查看下方提示并换一张照片'}
                      </span>
                    </>
                  ) : (
                    <span className="ex-v6__dropzone-hint">＋ 拖入照片 / 点击选择（JPG·PNG ≤10MB）</span>
                  )}
                </label>
                <div className="ex-v6__avatar-spec">
                  <div className="is-do"><h4>✅ 请这样做</h4><ul><li>正脸直视镜头，面部清晰</li><li>光线明亮均匀，无强阴影</li><li>半身照（人物占画面 50%-70%）</li></ul></div>
                  <div className="is-dont"><h4>❌ 不要这样</h4><ul><li>侧脸 / 低头 / 低头玩手机</li><li>口罩、墨镜等面部遮挡</li><li>全身远景（人脸占比过小）</li><li>昏暗或逆光环境</li></ul></div>
                </div>
                {(faceValidator.result.errorMsg || uploadNotice) && (
                  <div className="ex-v6__avatar-error" role="alert">{uploadNotice ?? faceValidator.result.errorMsg}</div>
                )}
                <div className="ex-v6__avatar-actions">
                  <button
                    type="button"
                    className="ex-v6__primary"
                    onClick={confirmPresenterUpload}
                    disabled={!presenterImageFile || !faceValidator.result.isValid || uploadBusy || Boolean(presenterImageUrl)}
                  >
                    {uploadBusy ? '上传与质检中…' : presenterImageUrl ? '✓ 已上传' : '上传并确认'}
                  </button>
                  {presenterImageFile && !presenterImageUrl && (
                    <button type="button" className="ex-v6__secondary" onClick={() => { faceValidator.reset(); setPresenterImageFile(null); setUploadNotice(null); }}>重新选择</button>
                  )}
                </div>
              </div>
            </div>
          )}
          {selectedScript && <div className="ex-v6__cues"><h3>确稿编辑器 · 视觉脚手架</h3>{cues.map((cue, index) => <div className="ex-v6__cue" key={`${cue.time_range}-${index}`}><input aria-label={`时间 ${index + 1}`} value={cue.time_range} onChange={event => updateCue(index, { time_range: event.target.value })} /><select aria-label={`画面类型 ${index + 1}`} value={cue.visual_type} onChange={event => updateCue(index, { visual_type: event.target.value as ExplainerCue['visual_type'] })}>{Object.entries(VISUAL_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><textarea aria-label={`旁白 ${index + 1}`} value={cue.text} rows={2} onChange={event => updateCue(index, { text: event.target.value })} />{cue.visual_type === 'browser_broll' && <input aria-label={`网页地址 ${index + 1}`} placeholder="https://官方来源…" value={cue.target_url ?? ''} onChange={event => updateCue(index, { target_url: event.target.value })} />}</div>)}<button type="button" className="ex-v6__add" onClick={() => setCues(previous => [...previous, { ...EMPTY_CUE }])}>＋ 添加 cue</button></div>}
          <label className="ex-v6__preview-gate"><input type="checkbox" checked={previewMode} onChange={event => setPreviewMode(event.target.checked)} /> <span><strong>先出 15 秒先导样片</strong><small>只渲染前 15s 的 cue/音频/画面（约 1/10 算力），确稿前先看质感，不合格不浪费全量渲染。</small></span></label>
          <div className="ex-v6__actions"><button type="button" className="ex-v6__secondary" onClick={() => setStage('research')}>返回修改偏好</button><button type="button" className="ex-v6__primary" onClick={startAssembly} disabled={busy || presenterBusy}>{busy ? '提交装配中…' : previewMode ? '⏱ 生成 15 秒先导样片' : '🚀 确认文案与脚手架，启动全自动装配出片'}</button></div>
        </section>
      )}

      {stage === 'assemble' && (
        <section className="ex-v6__panel" aria-labelledby="assemble-title">
          <div className="ex-v6__panel-title"><span>03</span><div><h2 id="assemble-title">全自动渲染与交付</h2><p>Task → oservi → omodul 装配事务；每一步都有可追踪状态和真实产物。</p></div></div>
          <div className="ex-v6__progress"><div className="ex-v6__progress-head"><strong>{task?.status === 'completed' ? '✓ 成片已完成' : task?.status === 'failed' ? '✗ 装配失败' : '⟳ Remotion 正在渲染中…'}</strong><span>任务 {taskId?.slice(0, 8)}</span></div><div className="ex-v6__bar"><i style={{ width: `${Math.max(5, task?.percent ?? 5)}%` }} /></div><p>{task?.stage ?? '已提交，等待生产任务调度'}</p></div>
          {task?.status === 'completed' && <div className="ex-v6__delivery"><h3>🎬 可下载产物</h3><a href={taskApi.videoUrl(task.task_id)} download>⬇ 下载竖屏成片</a><p>产物由 ArtifactManifest 校验后提供，路径：{task.result_video_path}</p></div>}
          {task?.status === 'failed' && <div className="ex-v6__error">{task.error ?? '装配失败，请查看任务详情'}</div>}
          {task?.status === 'failed' && (
            <button type="button" className="ex-v6__retry" onClick={startAssembly} disabled={busy}>
              🔄 重新提交装配
            </button>
          )}
        </section>
      )}
      {researchInfo && (
        <div className="ex-v6__restore" role="status" aria-live="polite">{researchInfo}</div>
      )}
      {error && <div className="ex-v6__error" role="alert">{error}</div>}
      {assembleFailed && (
        <div className="ex-v6__retry-row">
          <button type="button" className="ex-v6__retry" onClick={startAssembly} disabled={busy}>
            🔄 重新提交装配
          </button>
        </div>
      )}
    </div>
  );
}
