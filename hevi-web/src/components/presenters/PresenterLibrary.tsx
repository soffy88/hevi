'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth-store';
import { presenterApi, proStudioApi } from '@/lib/api-client';
import type { Presenter, PresenterInput, PresenterLipsync, PresenterMotion, PresenterPerformance } from '@/types/api';

const EMPTY: PresenterInput = {
  name: '', performance: 'narrator', motion: 'voice_over', lipsync: 'none',
  subject_id: null, voice_profile_id: null, delivery: {}, description: '',
};

export function PresenterLibrary() {
  const router = useRouter();
  const [items, setItems] = useState<Presenter[]>([]);
  const [form, setForm] = useState<PresenterInput>(EMPTY);
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try { setItems(await presenterApi.list()); }
    catch (e) {
      if (e instanceof Error && e.message === 'NOT_AUTHENTICATED') router.push('/login');
      else setError('数字人预设加载失败，请稍后重试');
    }
  };

  useEffect(() => { if (!isAuthenticated()) router.push('/login'); else void load(); }, [router]);

  const set = <K extends keyof PresenterInput>(key: K, value: PresenterInput[K]) =>
    setForm(prev => ({ ...prev, [key]: value }));

  const edit = (item: Presenter) => {
    setSelected(item.id);
    setForm({
      name: item.name, subject_id: item.subject_id ?? null,
      voice_profile_id: item.voice_profile_id ?? null,
      performance: (item.performance || 'narrator') as PresenterPerformance,
      motion: (item.motion || 'voice_over') as PresenterMotion,
      lipsync: (item.lipsync || 'none') as PresenterLipsync,
      delivery: item.delivery ?? {}, description: item.description ?? '',
    });
    setMessage(null); setError(null);
  };

  const save = async () => {
    if (!form.name.trim()) { setError('请填写预设名称'); return; }
    setBusy(true); setError(null); setMessage(null);
    try {
      if (selected) await presenterApi.update(selected, form);
      else await presenterApi.create(form);
      setForm(EMPTY); setSelected(null); await load(); setMessage('数字人预设已保存');
    } catch (e) { setError(e instanceof Error ? e.message : '保存失败'); }
    finally { setBusy(false); }
  };

  const test = async (id: string) => {
    setBusy(true); setError(null); setMessage(null);
    try {
      const result = await presenterApi.test(id);
      setMessage(result.ready ? '✓ 配置就绪，可用于自动出片' : `⚠ ${result.issues.join('；')}`);
    } catch (e) { setError(e instanceof Error ? e.message : '测试失败'); }
    finally { setBusy(false); }
  };

  return (
    <div className="hevi-presenters">
      <div className="hevi-presenters__hero">
        <div>
          <p className="hevi-presenters__eyebrow">Presenter · 数字人一等能力</p>
          <h1>数字人预设</h1>
          <p>把“谁出镜、用谁的声音、怎样运动和口型”保存为可复用配置，导演台、通鉴、短剧、解说共用。</p>
        </div>
        <button className="hevi-presenters__primary" onClick={() => { setSelected(null); setForm(EMPTY); setMessage(null); }}>＋ 新建预设</button>
      </div>

      <div className="hevi-presenters__grid">
        <section className="hevi-presenters__list">
          <h2>我的预设 <span>{items.length}</span></h2>
          {items.length === 0 && <div className="hevi-presenters__empty">还没有数字人预设。先创建一个旁白或出镜主播。</div>}
          {items.map(item => (
            <article key={item.id} className={`hevi-presenter-card${selected === item.id ? ' is-selected' : ''}`}>
              <div>
                <strong>{item.name}</strong>
                <p>{item.description || '未填写描述'}</p>
                <div className="hevi-presenter-card__chips">
                  <span>{item.performance}</span><span>{item.motion}</span><span>口型：{item.lipsync}</span>
                </div>
              </div>
              <div className="hevi-presenter-card__actions">
                <button onClick={() => edit(item)}>编辑</button>
                <button onClick={() => void test(item.id)} disabled={busy}>测试就绪</button>
              </div>
            </article>
          ))}
        </section>

        <section className="hevi-presenters__editor">
          <h2>{selected ? '编辑数字人预设' : '新建数字人预设'}</h2>
          <label>名称<input value={form.name} onChange={e => set('name', e.target.value)} placeholder="历史讲述者 / 新闻主播" /></label>
          <label>说明<textarea value={form.description} onChange={e => set('description', e.target.value)} rows={2} placeholder="这个预设适合什么内容？" /></label>
          <div className="hevi-presenters__fields">
            <label>表现角色<select value={form.performance} onChange={e => set('performance', e.target.value as PresenterPerformance)}><option value="narrator">旁白讲述者</option><option value="presenter">出镜主播</option><option value="character_dialogue">剧情角色对白</option></select></label>
            <label>出镜方式<select value={form.motion} onChange={e => set('motion', e.target.value as PresenterMotion)}><option value="voice_over">纯旁白（不出镜）</option><option value="picture_in_picture">画中画</option><option value="talking_head">半身口播</option><option value="full_body">全身演绎</option></select></label>
            <label>口型策略<select value={form.lipsync} onChange={e => set('lipsync', e.target.value as PresenterLipsync)}><option value="none">无口型</option><option value="native_audio">原生音画</option><option value="dedicated_lipsync">专用口型同步</option><option value="avatar_provider">供应商口型</option></select></label>
            <label>Subject ID（可选）<input value={form.subject_id ?? ''} onChange={e => set('subject_id', e.target.value || null)} placeholder="绑定角色/肖像资产" /></label>
            <label>声音档案 ID（可选）<input value={form.voice_profile_id ?? ''} onChange={e => set('voice_profile_id', e.target.value || null)} placeholder="绑定声音资产" /></label>
          </div>
          <p className="hevi-presenters__hint">出镜方式不是“纯旁白”时需要 Subject ID；启用口型同步时需要声音档案 ID。保存后可点击“测试就绪”。</p>
          <div className="hevi-presenters__editor-actions"><button onClick={() => { setSelected(null); setForm(EMPTY); }}>清空</button><button className="hevi-presenters__primary" onClick={() => void save()} disabled={busy}>{busy ? '保存中…' : '保存预设'}</button></div>
        </section>
      </div>
      {error && <div className="hevi-presenters__notice is-error">{error}</div>}
      {message && <div className="hevi-presenters__notice">{message}</div>}

      {/* ── 应用模式(SPEC v5.0 §2.3,原专业工作室数字人直播归位) ── */}
      <LiveAppPanel presenters={items} />
    </div>
  );
}

function LiveAppPanel({ presenters }: { presenters: Presenter[] }) {
  const router = useRouter();
  const [capability, setCapability] = useState<{ can_start: boolean; provider?: string | null; message: string; setup?: string } | null>(null);
  const [presenterId, setPresenterId] = useState('');
  const [script, setScript] = useState('');
  const [scene, setScene] = useState('');
  const [streamUrl, setStreamUrl] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [loading, setLoading] = useState(false);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [liveStatus, setLiveStatus] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void proStudioApi.livestreamCapabilities()
      .then(ready => { if (active) setCapability(ready); })
      .catch(() => { if (active) setCapability({ can_start: false, message: '无法确认直播能力', setup: undefined, provider: null }); });
    return () => { active = false; };
  }, []);

  async function start() {
    if (!presenterId) { setLiveError('请先选择数字人预设'); return; }
    if (!script.trim()) { setLiveError('请先输入直播互动脚本'); return; }
    setLoading(true); setLiveError(null);
    try {
      const data = await proStudioApi.livestreamStart({ presenter_id: presenterId, scene: scene || undefined, script });
      setSessionId(data.session_id);
      setStreamUrl(data.stream_url ?? '');
      setLiveStatus('已启动');
    } catch (e) { setLiveError(e instanceof Error ? e.message : '直播启动失败'); }
    setLoading(false);
  }

  async function stop() {
    if (!sessionId) return;
    setLoading(true); setLiveError(null);
    try {
      await proStudioApi.livestreamStop({ session_id: sessionId });
      setSessionId(''); setStreamUrl(''); setLiveStatus('已停止');
    } catch (e) { setLiveError(e instanceof Error ? e.message : '直播停止失败'); }
    setLoading(false);
  }

  return (
    <section className="hevi-presenters__apps">
      <h2>应用模式</h2>
      <p className="hevi-presenters__apps-sub">
        数字人预设的两种应用：出镜视频渲染 与 实时数字人直播（推流地址 + 互动脚本 + 直播预检）。
      </p>
      <div className="hevi-presenters__apps-grid">
        {/* 卡片 1:出镜视频渲染 */}
        <article className="hevi-presenters__app">
          <div className="hevi-presenters__app-icon">🎬</div>
          <h3>出镜视频渲染 (Video Render)</h3>
          <p>把该预设用于导演台 / 通鉴 / 解说中心的出镜视频渲染，画中画口播 + 唇形同步。</p>
          <div className="hevi-presenters__app-actions">
            <button onClick={() => router.push('/explainer')}>去解说中心使用 →</button>
            <button onClick={() => router.push('/director')}>去导演台使用 →</button>
          </div>
        </article>

        {/* 卡片 2:实时数字人直播 */}
        <article className="hevi-presenters__app">
          <div className="hevi-presenters__app-icon">📺</div>
          <h3>实时数字人直播 (Livestreaming)</h3>
          <p>配置推流地址、互动脚本与直播预检后，以该数字人形象开播真实直播。</p>

          {capability && !capability.can_start && (
            <div className="hevi-presenters__live-warn">
              <p>⚠ {capability.message}</p>
              {capability.setup && <p className="hevi-presenters__live-warn-sub">{capability.setup}</p>}
            </div>
          )}

          <div className="hevi-presenters__live-fields">
            <label>数字人预设
              <select value={presenterId} onChange={(e) => setPresenterId(e.target.value)}>
                <option value="">请选择数字人预设</option>
                {presenters.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
            <label>推流地址 (stream_url, 可选)
              <input value={streamUrl} onChange={(e) => setStreamUrl(e.target.value)} placeholder="rtmp://… / srt://…" />
            </label>
            <label>互动脚本
              <textarea rows={4} value={script} onChange={(e) => setScript(e.target.value)} placeholder="开场白、互动话术、问答预案……" />
            </label>
            <label>场景 (可选)
              <input value={scene} onChange={(e) => setScene(e.target.value)} placeholder="例如：历史讲解演播室" />
            </label>
          </div>
          <div className="hevi-presenters__app-actions">
            <button disabled={loading || !!sessionId || !presenterId || !script.trim() || !capability?.can_start} onClick={() => void start()}>
              {loading ? '启动中…' : '▶ 直播预检并开播'}
            </button>
            <button disabled={loading || !sessionId} onClick={() => void stop()}>⏹ 停止直播</button>
          </div>
          {sessionId && <p className="hevi-presenters__live-on">● 直播会话已启动: {sessionId}</p>}
          {liveStatus && !sessionId && <p className="hevi-presenters__live-status">{liveStatus}</p>}
          {liveError && <p className="hevi-presenters__live-error">⚠ {liveError}</p>}
        </article>
      </div>
    </section>
  );
}
