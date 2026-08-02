/**
 * ExplainerConsole — 解说中心(Frontend SPEC v4.0 §2.3)
 * 纯解说大类,内置两个配方卡片二选一:
 *  - 📋 short_explainer 图文解说:选题 → 文案分镜 → 配音 → Remotion 渲染竖/横屏成片(hevi.explainer E0-E2)
 *  - 🎙️ digital_presenter 数字人口播:选题 + 数字人出镜 → 走主线 /api/pipeline/generate
 *    (adapter_type=explainer + presenter_id,画中画口播)
 */
'use client';

import { useEffect, useRef, useState } from 'react';
import { explainerApi, presenterApi, productionApi, proStudioApi, taskApi } from '@/lib/api-client';
import { syncAuthToken } from '@/lib/auth-store';
import type { ExplainerRunStatus, Presenter, ProductionTask } from '@/types/api';

type Recipe = 'short_explainer' | 'digital_presenter' | 'code_explainer';

const LAYER_LABELS: Record<string, string> = {
  E0: '选题 → 文案分镜',
  E1: '结构校验',
  E2: '配音 + 渲染出片',
};

const STATUS_ICON: Record<string, string> = {
  PENDING: '○',
  RUNNING: '⟳',
  PASSED: '✓',
  FAILED: '✗',
};

const STATUS_CLASS: Record<string, string> = {
  PENDING: 'ex-layer--pending',
  RUNNING: 'ex-layer--running',
  PASSED: 'ex-layer--passed',
  FAILED: 'ex-layer--failed',
};

const DEMO_TOPICS = ['沉没成本', '拖延症', '为什么我们容易冲动消费'];

export function ExplainerConsole() {
  const [recipe, setRecipe] = useState<Recipe>('short_explainer');
  const [topic, setTopic] = useState('');
  const [presenterId, setPresenterId] = useState('');
  const [presenters, setPresenters] = useState<Presenter[]>([]);
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [durationArchetype, setDurationArchetype] = useState('1-5min');
  const [executionPreset, setExecutionPreset] = useState<'economy' | 'balanced' | 'fast'>('balanced');

  // 代码解说配方(SPEC v5.0 §2.4 Remotion 代码/图表动态渲染)
  const [code, setCode] = useState('');
  const [codeLanguage, setCodeLanguage] = useState('python');
  const [codeStyle, setCodeStyle] = useState('concise');
  const [codeTask, setCodeTask] = useState<{ task_id: string; status: string } | null>(null);

  const [busy, setBusy] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<ExplainerRunStatus | null>(null);
  const [task, setTask] = useState<ProductionTask | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 数字人口播配方需要数字人列表
  useEffect(() => {
    syncAuthToken();
    presenterApi.list()
      .then(ps => setPresenters(ps))
      .catch(() => setPresenters([]));
  }, []);

  // short_explainer:轮询 E0-E2 状态
  useEffect(() => {
    if (!runId) return;
    const poll = async () => {
      try {
        const s = await explainerApi.getStatus(runId);
        setStatus(s);
        if (s.status === 'COMPLETED' || s.status === 'FAILED') {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        // 静默
      }
    };
    poll();
    pollRef.current = setInterval(poll, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [runId]);

  // digital_presenter:轮询主线任务进度
  useEffect(() => {
    const taskId = task?.task_id ?? '';
    if (!taskId) return;
    let cancelled = false;
    async function poll() {
      try {
        const t = await taskApi.get(taskId);
        if (!cancelled) setTask(t as ProductionTask);
        if (!cancelled && (t.status === 'completed' || t.status === 'failed')) return;
        if (!cancelled) timer = setTimeout(poll, 4000);
      } catch {
        if (!cancelled) timer = setTimeout(poll, 4000);
      }
    }
    let timer: ReturnType<typeof setTimeout> = setTimeout(poll, 0);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [task?.task_id]);

  async function startPipeline() {
    if (!topic.trim()) { setErr('请输入选题'); return; }
    if (recipe === 'digital_presenter' && !presenterId) { setErr('请选择数字人'); return; }
    setErr(null);
    setBusy(true);
    setStatus(null);
    setTask(null);
    setRunId(null);
    try {
      if (recipe === 'short_explainer') {
        const r = await explainerApi.startRun({ topic });
        setRunId(r.run_id);
      } else if (recipe === 'code_explainer') {
        if (!code.trim()) { setErr('请输入代码片段'); return; }
        const t = await proStudioApi.codeExplainerGenerate({ code, language: codeLanguage, style: codeStyle });
        setCodeTask(t);
      } else {
        const t = await productionApi.generate({
          source_channel: 'hub_quick',
          adapter_type: 'explainer',
          config: {
            prompt: topic,
            duration_archetype: durationArchetype,
            aspect_ratio: aspectRatio as '16:9' | '9:16' | '1:1',
            execution_preset: executionPreset,
            presenter_id: presenterId,
            emotion_aware_voiceover: true,
            options: { recipe: 'digital_presenter' },
          },
        });
        setTask(t);
      }
    } catch (e) {
      if (e instanceof Error && e.message === 'NOT_AUTHENTICATED') setErr('请先登录');
      else setErr(e instanceof Error ? e.message : '出错了');
    } finally {
      setBusy(false);
    }
  }

  const allDone = status?.status === 'COMPLETED' || status?.status === 'FAILED';
  const completedCount = status?.layers?.filter(l => l.status === 'PASSED').length ?? 0;
  const totalLayers = status?.layers?.length ?? 3;
  const running = busy || (!allDone && !!runId) || (!!task && task.status === 'running') || (!!codeTask && codeTask.status === 'running');

  return (
    <div className="ex">
      <div className="ex__hero">
        <h1 className="ex__title">解说中心</h1>
        <p className="ex__sub">
          纯解说大类 · 图文解说（short_explainer）· 数字人口播（digital_presenter）· 代码解说（Remotion 动态渲染）
        </p>
      </div>

      {/* ── 配方三选一卡片(SPEC v5.0 §2.4) ── */}
      <div className="ex-recipes">
        <button type="button" className="ex-recipe" data-on={recipe === 'short_explainer' ? 'true' : undefined}
          onClick={() => setRecipe('short_explainer')}>
          <span className="ex-recipe__icon">📋</span>
          <span className="ex-recipe__name">图文解说 · short_explainer</span>
          <span className="ex-recipe__desc">文案分镜 + 配音 + 动态图文渲染，输出竖屏/横屏成片（E0-E2 流水线）</span>
        </button>
        <button type="button" className="ex-recipe" data-on={recipe === 'digital_presenter' ? 'true' : undefined}
          onClick={() => setRecipe('digital_presenter')}>
          <span className="ex-recipe__icon">🎙️</span>
          <span className="ex-recipe__name">数字人口播 · digital_presenter</span>
          <span className="ex-recipe__desc">选择数字人出镜口播（画中画），情感化配音 + 唇形同步</span>
        </button>
        <button type="button" className="ex-recipe" data-on={recipe === 'code_explainer' ? 'true' : undefined}
          onClick={() => setRecipe('code_explainer')}>
          <span className="ex-recipe__icon">💻</span>
          <span className="ex-recipe__name">代码解说 · Remotion 动态渲染</span>
          <span className="ex-recipe__desc">输入技术/代码解说材料，代码高亮 + 逐行动画 + 图表/公式，输出专业动态代码视频切片</span>
        </button>
      </div>

      {/* ── 选题 ── */}
      <section className="ex-sec">
        <div className="ex-sec__head">
          <span className="ex-sec__num">①</span>
          <h2>选题</h2>
        </div>
        <div className="ex-demos">
          {DEMO_TOPICS.map(t => (
            <button key={t} type="button" className="ex-demo-btn" onClick={() => setTopic(t)}>
              填入示例:{t}
            </button>
          ))}
        </div>
        <label className="ex-field">
          <span className="ex-field__label">选题（一句话，如"沉没成本"）</span>
          <input value={topic} onChange={e => setTopic(e.target.value)}
            placeholder="沉没成本" />
        </label>
      </section>

      {/* ── 配方参数 ── */}
      <section className="ex-sec">
        <div className="ex-sec__head">
          <span className="ex-sec__num">②</span>
          <h2>配方参数</h2>
        </div>
        {recipe === 'digital_presenter' && (
          <div className="ex-grid">
            <label className="ex-field">
              <span className="ex-field__label">数字人（出镜口播）</span>
              <select value={presenterId} onChange={e => setPresenterId(e.target.value)}>
                <option value="">请选择数字人…</option>
                {presenters.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <label className="ex-field">
              <span className="ex-field__label">单集时长档</span>
              <select value={durationArchetype} onChange={e => setDurationArchetype(e.target.value)}>
                <option value="~30s">极短 ~30s</option>
                <option value="1-5min">1-5 分钟</option>
                <option value="5-15min">5-15 分钟</option>
              </select>
            </label>
            <label className="ex-field">
              <span className="ex-field__label">执行档位</span>
              <select value={executionPreset} onChange={e => setExecutionPreset(e.target.value as 'economy' | 'balanced' | 'fast')}>
                <option value="economy">💰 省钱</option>
                <option value="balanced">⚖️ 均衡</option>
                <option value="fast">⚡ 极速</option>
              </select>
            </label>
            <label className="ex-field">
              <span className="ex-field__label">画幅</span>
              <select value={aspectRatio} onChange={e => setAspectRatio(e.target.value)}>
                <option value="16:9">16:9 横屏</option>
                <option value="9:16">9:16 竖屏</option>
                <option value="1:1">1:1 方形</option>
              </select>
            </label>
          </div>
        )}
        {recipe === 'short_explainer' && (
          <p className="ex-hint">图文解说配方：E0 选题→文案分镜 → E1 结构校验 → E2 配音 + 渲染，自动输出竖屏+横屏成片。</p>
        )}
        {recipe === 'code_explainer' && (
          <div className="ex-grid">
            <label className="ex-field">
              <span className="ex-field__label">语言</span>
              <select value={codeLanguage} onChange={e => setCodeLanguage(e.target.value)}>
                <option value="python">Python</option>
                <option value="javascript">JavaScript</option>
                <option value="typescript">TypeScript</option>
                <option value="go">Go</option>
                <option value="rust">Rust</option>
              </select>
            </label>
            <label className="ex-field">
              <span className="ex-field__label">讲解深度</span>
              <select value={codeStyle} onChange={e => setCodeStyle(e.target.value)}>
                <option value="concise">简洁</option>
                <option value="detailed">详细</option>
                <option value="beginner">初学者友好</option>
              </select>
            </label>
            <label className="ex-field ex-field--full">
              <span className="ex-field__label">代码片段（Remotion 代码高亮 + 逐行动画录制）</span>
              <textarea rows={8} className="ex-code" value={code} onChange={e => setCode(e.target.value)}
                placeholder="def fib(n):
    return n if n < 2 else fib(n-1) + fib(n-2)" />
            </label>
          </div>
        )}
      </section>

      <div className="ex-actions">
        <button type="button" className="ex-btn ex-btn--primary"
          onClick={startPipeline} disabled={busy || running}>
          {busy ? '提交中…' : running ? '制作中…' : recipe === 'digital_presenter'
            ? '▶ 开始数字人口播'
            : recipe === 'code_explainer'
              ? '▶ 生成代码解说视频'
              : '▶ 一键出片'}
        </button>
        {(allDone || (task && (task.status === 'completed' || task.status === 'failed')) || codeTask) && (
          <button type="button" className="ex-btn"
            onClick={() => { setRunId(null); setStatus(null); setTask(null); setCodeTask(null); }}>
            重新开始
          </button>
        )}
      </div>

      {err && <div className="ex-err">{err}</div>}

      {/* ── short_explainer 进度 ── */}
      {status && (
        <div className="ex-progress">
          <div className="ex-progress__head">
            <span className={`ex-run-badge ex-run-badge--${status.status.toLowerCase()}`}>
              {status.status === 'RUNNING' ? '⟳ 运行中' :
               status.status === 'COMPLETED' ? '✓ 已完成' :
               status.status === 'FAILED' ? '✗ 失败' : '待机'}
            </span>
            <span className="ex-progress__count">{completedCount}/{totalLayers} 层完成</span>
            {status.current_layer && status.status === 'RUNNING' && (
              <span className="ex-progress__cur">
                当前:{LAYER_LABELS[status.current_layer] ?? status.current_layer}
              </span>
            )}
          </div>

          <div className="ex-bar">
            <div className="ex-bar__fill"
              style={{ width: `${Math.round(completedCount / totalLayers * 100)}%` }} />
          </div>

          <div className="ex-layers">
            {status.layers.map(l => (
              <div key={l.layer} className={`ex-layer ${STATUS_CLASS[l.status] ?? ''}`}>
                <span className="ex-layer__icon">{STATUS_ICON[l.status] ?? '○'}</span>
                <span className="ex-layer__code">{l.layer}</span>
                <span className="ex-layer__name">{LAYER_LABELS[l.layer] ?? l.layer}</span>
                {l.status === 'RUNNING' && <span className="ex-layer__spin" />}
                {l.error && <span className="ex-layer__err" title={l.error}>!</span>}
              </div>
            ))}
          </div>

          {status.status === 'COMPLETED' && (
            <div className="ex-result">
              <div className="ex-result__head">🎬 成片已完成</div>
              <p className="ex-result__path">竖屏:{status.result_portrait_path}</p>
              <p className="ex-result__path">横屏:{status.result_landscape_path}</p>
              <p className="ex-hint">成片已落盘,可在服务器上直接取用。</p>
            </div>
          )}

          {status.status === 'FAILED' && (
            <div className="ex-result ex-result--fail">
              <div className="ex-result__head">流水线失败</div>
              <p className="ex-hint">{status.error ?? '未知错误'}</p>
            </div>
          )}
        </div>
      )}

      {/* ── digital_presenter 任务进度 ── */}
      {task && (
        <div className="ex-progress">
          <div className="ex-progress__head">
            <span className={`ex-run-badge ex-run-badge--${task.status === 'failed' ? 'failed' : task.status === 'completed' ? 'completed' : 'running'}`}>
              {task.status === 'completed' ? '✓ 已完成' :
               task.status === 'failed' ? '✗ 失败' : `⟳ 任务生成中（${Math.round(task.percent)}%）`}
            </span>
            {task.stage && <span className="ex-progress__cur">阶段:{task.stage}</span>}
            <span className="ex-progress__count">任务 {task.task_id.slice(0, 8)}</span>
          </div>
          <div className="ex-bar">
            <div className="ex-bar__fill" style={{ width: `${Math.round(task.percent)}%` }} />
          </div>
          {task.status === 'completed' && task.result_video_path && (
            <div className="ex-result">
              <div className="ex-result__head">🎬 数字人口播成片已完成</div>
              <a
                className="oui-btn"
                href={`/api/files?path=${encodeURIComponent(task.result_video_path)}`}
                download={`explainer_${task.task_id.slice(0, 8)}.mp4`}
              >
                ⬇ 下载成片
              </a>
              <p className="ex-result__path">{task.result_video_path}</p>
            </div>
          )}
          {task.status === 'failed' && (
            <div className="ex-result ex-result--fail">
              <div className="ex-result__head">任务失败</div>
              <p className="ex-hint">{task.error ?? '未知错误'}</p>
            </div>
          )}
        </div>
      )}

      {/* ── 代码解说任务(SPEC v5.0 §2.4) ── */}
      {codeTask && (
        <div className="ex-progress">
          <div className="ex-progress__head">
            <span className={`ex-run-badge ex-run-badge--${codeTask.status === 'failed' ? 'failed' : 'running'}`}>
              {codeTask.status === 'failed' ? '✗ 失败' : '⟳ 代码渲染中…（Remotion 高亮 + 逐行动画）'}
            </span>
            <span className="ex-progress__count">任务 {codeTask.task_id.slice(0, 8)}</span>
          </div>
          <div className="ex-result">
            <div className="ex-result__head">🎬 动态代码视频切片任务已提交</div>
            <pre className="ex-result__path">{JSON.stringify(codeTask, null, 2)}</pre>
          </div>
        </div>
      )}

      {/* ── Agent 编排底座(SPEC v5.0 §2.4) ── */}
      <AgentBaseStrip />
    </div>
  );
}

function AgentBaseStrip() {
  const [task, setTask] = useState('');
  const [plan, setPlan] = useState<{ plan_id: string; steps: Array<Record<string, unknown>> } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function createPlan() {
    if (!task) return;
    setLoading(true); setError(null);
    try {
      const data = await proStudioApi.orchestrationCreatePlan({ task });
      setPlan(data);
    } catch (e) { setError(e instanceof Error ? e.message : '计划创建失败'); }
    setLoading(false);
  }

  return (
    <section className="ex-sec ex-agent">
      <div className="ex-sec__head">
        <span className="ex-sec__num">🤖</span>
        <h2>Agent 编排底座（文本分析 → Remotion 渲染 → 音视频同步）</h2>
      </div>
      <p className="ex-hint">
        底部统一由 Agent 编排引擎驱动：选题文本分析、Remotion 代码/图表渲染与音视频同步由同一底座调度。
      </p>
      <label className="ex-field">
        <span className="ex-field__label">编排任务描述</span>
        <input value={task} onChange={e => setTask(e.target.value)}
          placeholder="e.g. 将上面选题做成 2 分钟竖屏解说，代码部分用逐行动画" />
      </label>
      <div className="ex-actions">
        <button type="button" className="ex-btn" onClick={createPlan} disabled={loading || !task}>
          📝 生成编排规划
        </button>
      </div>
      {plan && (
        <div className="dp-agent__plan">
          <p className="dp-agent__plan-id">计划 ID: {plan.plan_id}</p>
          <pre>{JSON.stringify(plan.steps, null, 2)}</pre>
        </div>
      )}
      {error && <p className="ex-hint" style={{ color: 'var(--destructive, #d33)' }}>⚠ {error}</p>}
    </section>
  );
}
