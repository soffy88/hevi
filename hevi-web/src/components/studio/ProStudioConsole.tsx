'use client';

import { useState } from 'react';
import { proStudioApi } from '@/lib/api-client';
import { TabBar, type TabItem } from '@/components/shared';

type Tab = 'indextts' | 'stock' | 'livestream' | 'agent' | 'code';

interface AgentPlan {
  plan_id: string;
  steps: Array<Record<string, unknown>>;
}

export function ProStudioConsole() {
  const [tab, setTab] = useState<Tab>('indextts');
  const [ttsEmotions, setTtsEmotions] = useState<Record<string, number> | null>(null);
  const [stockResults, setStockResults] = useState<Array<Record<string, unknown>>>([]);
  const [liveStatus, setLiveStatus] = useState<Record<string, unknown> | null>(null);
  const [agentRoles, setAgentRoles] = useState<Array<{ id: string; name: string; description: string }>>([]);
  const [agentPlan, setAgentPlan] = useState<AgentPlan | null>(null);
  const [codeTask, setCodeTask] = useState<{ task_id: string; status: string } | null>(null);

  const tabs: Array<TabItem<Tab>> = [
    { key: 'indextts', label: '情感TTS', icon: '🎙️' },
    { key: 'stock', label: '素材搜索', icon: '🔍' },
    { key: 'livestream', label: '数字人直播', icon: '📺' },
    { key: 'agent', label: 'Agent编排', icon: '🤖' },
    { key: 'code', label: '代码解说', icon: '💻' },
  ];

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold mb-6">⚡ Pro 工作室</h1>

      <TabBar items={tabs} active={tab} onChange={setTab} variant="pill" />

      {tab === 'indextts' && <IndexTTSTab emotions={ttsEmotions} onEmotions={setTtsEmotions} />}
      {tab === 'stock' && <StockTab results={stockResults} onResults={setStockResults} />}
      {tab === 'livestream' && <LivestreamTab status={liveStatus} onStatus={setLiveStatus} />}
      {tab === 'agent' && (
        <AgentTab roles={agentRoles} onRoles={setAgentRoles} plan={agentPlan} onPlan={setAgentPlan} />
      )}
      {tab === 'code' && <CodeTab task={codeTask} onTask={setCodeTask} />}
    </div>
  );
}

/* ── IndexTTS Tab ─────────────────────────────────────────────────────── */

function IndexTTSTab({
  emotions,
  onEmotions,
}: {
  emotions: Record<string, number> | null;
  onEmotions: (v: Record<string, number> | null) => void;
}) {
  const [text, setText] = useState('');
  const [speaker, setSpeaker] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  async function detectEmotion() {
    if (!text) return;
    setLoading(true);
    try {
      const data = await proStudioApi.indexttsEmotionFromText({ text });
      onEmotions(data.emo_vector);
    } catch { /* ignore */ }
    setLoading(false);
  }

  async function synthesize() {
    if (!speaker || !text) return;
    setLoading(true);
    try {
      const data = await proStudioApi.indexttsSynthesize({
        speaker,
        text,
        emo_vector: emotions ?? undefined,
      });
      setResult(data);
    } catch { /* ignore */ }
    setLoading(false);
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="block text-sm text-zinc-400 mb-1">说话人 (speaker path)</label>
        <input
          value={speaker}
          onChange={(e) => setSpeaker(e.target.value)}
          className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm"
          placeholder="/path/to/speaker.wav"
        />
      </div>
      <div>
        <label className="block text-sm text-zinc-400 mb-1">合成文本</label>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm"
        />
      </div>
      <div className="flex gap-2">
        <button
          onClick={detectEmotion}
          disabled={loading || !text}
          className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded text-sm disabled:opacity-50"
        >
          🎭 从文本推断情感
        </button>
        <button
          onClick={synthesize}
          disabled={loading || !speaker || !text}
          className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded text-sm disabled:opacity-50"
        >
          🔊 合成语音
        </button>
      </div>
      {emotions && (
        <div className="bg-zinc-900 rounded p-3 text-sm">
          <p className="text-zinc-400 mb-1">情感向量:</p>
          <div className="flex flex-wrap gap-2">
            {Object.entries(emotions).map(([k, v]) => (
              <span key={k} className="px-2 py-1 bg-zinc-800 rounded text-xs">
                {k}: {v.toFixed(2)}
              </span>
            ))}
          </div>
        </div>
      )}
      {result && (
        <div className="bg-zinc-900 rounded p-3 text-sm">
          <p className="text-green-400">✅ 合成任务已提交</p>
          <pre className="text-xs text-zinc-400 mt-1">{JSON.stringify(result, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

/* ── Stock Tab ────────────────────────────────────────────────────────── */

function StockTab({
  results,
  onResults,
}: {
  results: Array<Record<string, unknown>>;
  onResults: (v: Array<Record<string, unknown>>) => void;
}) {
  const [query, setQuery] = useState('');
  const [provider, setProvider] = useState('pexels');
  const [loading, setLoading] = useState(false);

  async function search() {
    if (!query) return;
    setLoading(true);
    try {
      const data = await proStudioApi.stockSearch({ query, provider });
      onResults(data.clips ?? []);
    } catch { /* ignore */ }
    setLoading(false);
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="flex-1 bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm"
          placeholder="搜索素材: sunset, city night..."
        />
        <select
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
          className="bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm"
        >
          <option value="pexels">Pexels</option>
          <option value="pixabay">Pixabay</option>
          <option value="videvo">Videvo</option>
        </select>
        <button
          onClick={search}
          disabled={loading || !query}
          className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded text-sm disabled:opacity-50"
        >
          🔍 搜索
        </button>
      </div>
      {results.length > 0 && (
        <div className="grid grid-cols-2 gap-3">
          {results.map((clip, i) => (
            <div key={i} className="bg-zinc-900 rounded p-3 text-sm">
              <pre className="text-xs text-zinc-400 overflow-auto max-h-40">
                {JSON.stringify(clip, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Livestream Tab ───────────────────────────────────────────────────── */

function LivestreamTab({
  status,
  onStatus,
}: {
  status: Record<string, unknown> | null;
  onStatus: (v: Record<string, unknown> | null) => void;
}) {
  const [sessionId, setSessionId] = useState('');
  const [script, setScript] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    if (!script.trim()) {
      setError('请先填写直播脚本，再启动直播。');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await proStudioApi.livestreamStart({ script: script.trim() });
      setSessionId(data.session_id);
      onStatus(data);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '直播启动失败');
    } finally {
      setLoading(false);
    }
  }

  async function stop() {
    if (!sessionId) return;
    setLoading(true);
    try {
      const data = await proStudioApi.livestreamStop({ session_id: sessionId });
      onStatus(data);
      setSessionId('');
    } catch { /* ignore */ }
    setLoading(false);
  }

  return (
    <div className="space-y-4">
      <label className="block space-y-1 text-sm">
        <span className="text-zinc-300">直播脚本（必填）</span>
        <textarea
          value={script}
          onChange={(event) => setScript(event.target.value)}
          rows={4}
          placeholder="输入本场直播要讲述的内容…"
          disabled={loading || !!sessionId}
          className="w-full rounded border border-zinc-700 bg-zinc-900 p-3 text-zinc-100"
        />
      </label>
      {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
      <div className="flex gap-2">
        <button
          onClick={start}
          disabled={loading || !!sessionId || !script.trim()}
          className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded text-sm disabled:opacity-50"
        >
          ▶️ 开始直播
        </button>
        <button
          onClick={stop}
          disabled={loading || !sessionId}
          className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded text-sm disabled:opacity-50"
        >
          ⏹ 停止直播
        </button>
      </div>
      {sessionId && (
        <p className="text-sm text-zinc-400">
          Session: <code className="text-zinc-300">{sessionId}</code>
        </p>
      )}
      {status && (
        <div className="bg-zinc-900 rounded p-3 text-sm">
          <pre className="text-xs text-zinc-400">{JSON.stringify(status, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

/* ── Agent Tab ────────────────────────────────────────────────────────── */

function AgentTab({
  roles,
  onRoles,
  plan,
  onPlan,
}: {
  roles: Array<{ id: string; name: string; description: string }>;
  onRoles: (v: Array<{ id: string; name: string; description: string }>) => void;
  plan: AgentPlan | null;
  onPlan: (v: AgentPlan | null) => void;
}) {
  const [task, setTask] = useState('');
  const [agents, setAgents] = useState('');
  const [loading, setLoading] = useState(false);
  const [executeResult, setExecuteResult] = useState<Record<string, unknown> | null>(null);

  async function loadRoles() {
    try {
      const data = await proStudioApi.orchestrationRoles();
      onRoles(data.roles ?? []);
    } catch { /* ignore */ }
  }

  async function createPlan() {
    if (!task) return;
    setLoading(true);
    try {
      const agentList = agents ? agents.split(',').map((a) => a.trim()) : undefined;
      const data = await proStudioApi.orchestrationCreatePlan({ task, agents: agentList });
      onPlan(data);
    } catch { /* ignore */ }
    setLoading(false);
  }

  async function executePlan() {
    if (!plan?.plan_id) return;
    setLoading(true);
    try {
      const data = await proStudioApi.orchestrationExecute({ plan_id: plan.plan_id });
      setExecuteResult(data);
    } catch { /* ignore */ }
    setLoading(false);
  }

  return (
    <div className="space-y-4">
      <button
        onClick={loadRoles}
        className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 rounded text-sm"
      >
        📋 加载可用角色
      </button>
      {roles.length > 0 && (
        <div className="bg-zinc-900 rounded p-3 text-sm">
          <p className="text-zinc-400 mb-2">可用角色:</p>
          <div className="space-y-1">
            {roles.map((r) => (
              <div key={r.id} className="text-xs text-zinc-300">
                <strong>{r.name}</strong> — {r.description}
              </div>
            ))}
          </div>
        </div>
      )}
      <div>
        <label className="block text-sm text-zinc-400 mb-1">任务描述</label>
        <textarea
          value={task}
          onChange={(e) => setTask(e.target.value)}
          rows={3}
          className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm"
          placeholder="e.g. 生成一段30秒产品宣传视频"
        />
      </div>
      <div>
        <label className="block text-sm text-zinc-400 mb-1">
          Agent 列表 (逗号分隔, 留空自动选择)
        </label>
        <input
          value={agents}
          onChange={(e) => setAgents(e.target.value)}
          className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm"
        />
      </div>
      <div className="flex gap-2">
        <button
          onClick={createPlan}
          disabled={loading || !task}
          className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded text-sm disabled:opacity-50"
        >
          📝 生成计划
        </button>
        <button
          onClick={executePlan}
          disabled={loading || !plan?.plan_id}
          className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded text-sm disabled:opacity-50"
        >
          🚀 执行计划
        </button>
      </div>
      {plan && (
        <div className="bg-zinc-900 rounded p-3 text-sm">
          <p className="text-zinc-400 mb-1">计划 ID: {plan.plan_id}</p>
          <p className="text-zinc-400 mb-1">步骤:</p>
          <pre className="text-xs text-zinc-400 overflow-auto max-h-40">
            {JSON.stringify(plan.steps, null, 2)}
          </pre>
        </div>
      )}
      {executeResult && (
        <div className="bg-zinc-900 rounded p-3 text-sm">
          <p className="text-green-400">✅ 执行已启动</p>
          <pre className="text-xs text-zinc-400 mt-1">{JSON.stringify(executeResult, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

/* ── Code Tab ─────────────────────────────────────────────────────────── */

function CodeTab({
  task,
  onTask,
}: {
  task: { task_id: string; status: string } | null;
  onTask: (v: { task_id: string; status: string } | null) => void;
}) {
  const [code, setCode] = useState('');
  const [language, setLanguage] = useState('python');
  const [style, setStyle] = useState('concise');
  const [loading, setLoading] = useState(false);

  async function generate() {
    if (!code) return;
    setLoading(true);
    try {
      const data = await proStudioApi.codeExplainerGenerate({ code, language, style });
      onTask(data);
    } catch { /* ignore */ }
    setLoading(false);
  }

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className="bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm"
        >
          <option value="python">Python</option>
          <option value="javascript">JavaScript</option>
          <option value="typescript">TypeScript</option>
          <option value="go">Go</option>
          <option value="rust">Rust</option>
        </select>
        <select
          value={style}
          onChange={(e) => setStyle(e.target.value)}
          className="bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm"
        >
          <option value="concise">简洁</option>
          <option value="detailed">详细</option>
          <option value="beginner">初学者友好</option>
        </select>
      </div>
      <textarea
        value={code}
        onChange={(e) => setCode(e.target.value)}
        rows={10}
        className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-2 text-sm font-mono"
        placeholder="粘贴代码..."
      />
      <button
        onClick={generate}
        disabled={loading || !code}
        className="px-4 py-2 bg-red-600 hover:bg-red-500 rounded text-sm disabled:opacity-50"
      >
        💡 生成解说视频
      </button>
      {task && (
        <div className="bg-zinc-900 rounded p-3 text-sm">
          <p className="text-green-400">✅ 任务已提交</p>
          <pre className="text-xs text-zinc-400 mt-1">{JSON.stringify(task, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
