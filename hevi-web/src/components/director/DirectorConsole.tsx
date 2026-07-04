/**
 * DirectorConsole — 导演控制台(§3 L4,专业片表单)
 * 一句话剧情 + 8 层结构化片表单 →「预览可行性」(不建任务)或「直接产集」(建任务+后台出片,含 L3 返工)。
 * 已接后端的字段做实控件;缺素材/模型/独立工程的标「规划中」禁用,不作假。
 */
'use client';

import { useState, useEffect, type FormEvent } from 'react';
import { directorApi, subjectApi } from '@/lib/api-client';
import type { DirectorPlanResult, DirectorEpisodeResult, DirectorEpisodePayload, Subject } from '@/types/api';

const PRESETS = [
  '科普', '严肃', '搞笑', '电影感', '赛博朋克', '国风水墨', '治愈系', '商务专业', '美食', '旅行Vlog',
  '产品广告', '新闻播报', '悬疑', '史诗', '复古胶片', '动漫', '极简', '自然纪录片', '时尚', '运动',
];
const DURATIONS = [
  { v: 'short', l: '极短 ~10s' }, { v: '1-5min', l: '1–5 分钟' }, { v: '5-15min', l: '5–15 分钟' },
  { v: '15-45min', l: '15–45 分钟' }, { v: '45min+', l: '45 分钟+' },
];
const ASPECTS = [{ v: '9:16', l: '竖 9:16' }, { v: '16:9', l: '横 16:9' }, { v: '1:1', l: '方 1:1' }];
const QUALITIES = [{ v: 'standard', l: '标清 720p' }, { v: 'high', l: '高清 1080p' }, { v: 'ultra', l: '超清 4K' }];
const TRANSITIONS = ['fade', 'cut', 'wipeleft', 'slideup', 'dissolve'];
const LANGUAGES = [{ v: 'zh', l: '中文' }, { v: 'en', l: 'English' }, { v: 'ja', l: '日本語' }];
const AUDIO = [{ v: 'vibevoice', l: 'VibeVoice(本地多说话人)' }, { v: 'edge_tts', l: 'Edge TTS(多语云)' },
  { v: 'ltx2_native', l: 'LTX-2 原生音' }, { v: 'duix', l: 'DUIX 数字人口型' }];
const VIDEO = [{ v: 'auto', l: '自动路由(最省)' }, { v: 'wan_local', l: 'Wan 本地(零成本)' },
  { v: 'ltx2_cloud', l: 'LTX-2 云' }, { v: 'veo3', l: 'Veo3(写实+原生音)' }, { v: 'kling_v2', l: 'Kling v2' },
  { v: 'hailuo', l: '海螺 02' }, { v: 'wan_cloud', l: 'Wan 云' }];
const EXEC = [{ v: '', l: '不用预设' }, { v: 'economy', l: '经济(本地零成本)' },
  { v: 'balanced', l: '均衡(默认)' }, { v: 'fast', l: '极速(云高清)' }];

const EMPTY: DirectorEpisodePayload = {
  text: '', duration_archetype: '1-5min', aspect_ratio: '9:16', subject_id: '', avatar_portrait: '',
  num_characters: 1, style_preset: '电影感', prompt_style: '', prompt_lighting: '', prompt_camera: '',
  prompt_color_grade: '', transition: 'fade', per_shot_routing: false, language: 'zh',
  audio_provider: 'vibevoice', quality_profile: 'standard', preset: '', video_provider: 'auto',
  budget_usd: undefined, auto_rework_rounds: undefined,
};

function errText(e: unknown): string {
  if (e instanceof Error && e.message === 'NOT_AUTHENTICATED') return '请先登录';
  if (e instanceof Error && e.message.startsWith('402')) return '预算不足或超额,无法产集';
  return e instanceof Error ? e.message : '出错了';
}

// 规划中(未实装)条目 —— 展示但禁用,不作假
function Soon({ label }: { label: string }) {
  return (
    <div className="dc-field dc-field--soon">
      <span className="dc-field__label">{label}</span>
      <span className="dc-chip dc-chip--soon">规划中</span>
    </div>
  );
}

export function DirectorConsole() {
  const [f, setF] = useState<DirectorEpisodePayload>(EMPTY);
  const [numShots, setNumShots] = useState(4);
  const [chars, setChars] = useState<Subject[]>([]);
  const [busy, setBusy] = useState<'plan' | 'episode' | null>(null);
  const [plan, setPlan] = useState<DirectorPlanResult | null>(null);
  const [episode, setEpisode] = useState<DirectorEpisodeResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    subjectApi.list('character').then(setChars).catch(() => setChars([]));
  }, []);

  const set = <K extends keyof DirectorEpisodePayload>(k: K, v: DirectorEpisodePayload[K]) =>
    setF(prev => ({ ...prev, [k]: v }));

  function buildPayload(): DirectorEpisodePayload {
    const p: DirectorEpisodePayload = { ...f };
    // 空串 → 省略,交后端默认/自动
    (['subject_id', 'avatar_portrait', 'prompt_style', 'prompt_lighting', 'prompt_camera',
      'prompt_color_grade', 'preset'] as (keyof DirectorEpisodePayload)[]).forEach(k => {
      if (!p[k]) delete p[k];
    });
    return p;
  }

  async function preview() {
    if (!f.text.trim()) { setErr('先写一句剧情'); return; }
    setBusy('plan'); setErr(null); setEpisode(null);
    try { setPlan(await directorApi.plan(f.text.trim(), numShots)); }
    catch (e) { setErr(errText(e)); } finally { setBusy(null); }
  }

  async function produce(e: FormEvent) {
    e.preventDefault();
    if (!f.text.trim()) { setErr('先写一句剧情'); return; }
    setBusy('episode'); setErr(null);
    try { setEpisode(await directorApi.createEpisode(buildPayload())); }
    catch (e2) { setErr(errText(e2)); } finally { setBusy(null); }
  }

  return (
    <form className="dc" onSubmit={produce}>
      <h1 className="dc__title">导演控制台</h1>
      <p className="dc__sub">按一部片该控的 8 层要素填 —— 立意 · 角色 · 场景 · 风格 · 分镜 · 音频 · 成片 · 生产。</p>

      {/* ① 立意 */}
      <section className="dc-sec">
        <div className="dc-sec__head"><span className="dc-sec__num">①</span><h2>立意</h2></div>
        <textarea className="dc-text" rows={3} placeholder="一句话剧情,例:一只狐狸在雪地里捕猎,电影感冷色调"
          value={f.text} onChange={e => set('text', e.target.value)} />
        <div className="dc-grid">
          <label className="dc-field"><span className="dc-field__label">时长</span>
            <select value={f.duration_archetype} onChange={e => set('duration_archetype', e.target.value)}>
              {DURATIONS.map(d => <option key={d.v} value={d.v}>{d.l}</option>)}
            </select>
          </label>
          <div className="dc-field"><span className="dc-field__label">画幅</span>
            <div className="dc-seg">
              {ASPECTS.map(a => (
                <button type="button" key={a.v} data-on={f.aspect_ratio === a.v ? 'true' : undefined}
                  onClick={() => set('aspect_ratio', a.v)}>{a.l}</button>
              ))}
            </div>
          </div>
          <Soon label="情绪基调" /><Soon label="题材类型" /><Soon label="叙事结构 / 3 秒钩子" />
        </div>
      </section>

      {/* ② 角色 */}
      <section className="dc-sec">
        <div className="dc-sec__head"><span className="dc-sec__num">②</span><h2>角色</h2></div>
        <div className="dc-grid">
          <label className="dc-field"><span className="dc-field__label">绑定主角(跨镜一致)</span>
            <select value={f.subject_id ?? ''} onChange={e => set('subject_id', e.target.value)}>
              <option value="">不绑定</option>
              {chars.map(c => <option key={c.subject_id} value={c.subject_id}>{c.name}</option>)}
            </select>
          </label>
          <label className="dc-field"><span className="dc-field__label">角色数</span>
            <input type="number" min={1} max={6} value={f.num_characters}
              onChange={e => set('num_characters', Number(e.target.value))} />
          </label>
          <label className="dc-field"><span className="dc-field__label">数字人肖像(图路径/URL)</span>
            <input placeholder="留空=不用数字人" value={f.avatar_portrait ?? ''}
              onChange={e => set('avatar_portrait', e.target.value)} />
          </label>
          <Soon label="多身份锁定" /><Soon label="角色对白" />
        </div>
        {chars.length === 0 && <p className="dc-hint">主体库还没有角色 —— 去「主体库」建一个带参考图的角色,这里就能绑定锁脸。</p>}
      </section>

      {/* ③ 场景 */}
      <section className="dc-sec">
        <div className="dc-sec__head"><span className="dc-sec__num">③</span><h2>场景</h2></div>
        <div className="dc-grid">
          <label className="dc-field dc-field--wide"><span className="dc-field__label">光线 / 时间氛围</span>
            <input placeholder="例:黄昏暖光 / 夜晚霓虹 / 清晨薄雾" value={f.prompt_lighting ?? ''}
              onChange={e => set('prompt_lighting', e.target.value)} />
          </label>
          <Soon label="场景表(地点/室内外)" /><Soon label="道具 / 陈设" />
        </div>
      </section>

      {/* ④ 视觉风格 */}
      <section className="dc-sec">
        <div className="dc-sec__head"><span className="dc-sec__num">④</span><h2>视觉风格</h2></div>
        <div className="dc-grid">
          <label className="dc-field"><span className="dc-field__label">整体风格预设</span>
            <select value={f.style_preset ?? ''} onChange={e => set('style_preset', e.target.value)}>
              {PRESETS.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          </label>
          <label className="dc-field"><span className="dc-field__label">镜头语言</span>
            <input placeholder="例:特写 / 缓慢推近 / 航拍全景" value={f.prompt_camera ?? ''}
              onChange={e => set('prompt_camera', e.target.value)} />
          </label>
          <label className="dc-field"><span className="dc-field__label">调色</span>
            <input placeholder="例:冷青调 / 暖金 / 高对比" value={f.prompt_color_grade ?? ''}
              onChange={e => set('prompt_color_grade', e.target.value)} />
          </label>
          <label className="dc-field"><span className="dc-field__label">额外风格描述</span>
            <input placeholder="可选,追加视觉描述" value={f.prompt_style ?? ''}
              onChange={e => set('prompt_style', e.target.value)} />
          </label>
          <Soon label="风格参考图 mood board" />
        </div>
      </section>

      {/* ⑤ 分镜 */}
      <section className="dc-sec">
        <div className="dc-sec__head"><span className="dc-sec__num">⑤</span><h2>分镜</h2></div>
        <div className="dc-grid">
          <label className="dc-field"><span className="dc-field__label">分镜数(预览用)</span>
            <input type="number" min={1} max={12} value={numShots}
              onChange={e => setNumShots(Number(e.target.value))} />
          </label>
          <label className="dc-field"><span className="dc-field__label">转场</span>
            <select value={f.transition} onChange={e => set('transition', e.target.value)}>
              {TRANSITIONS.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
          <label className="dc-field dc-field--check">
            <input type="checkbox" checked={f.per_shot_routing}
              onChange={e => set('per_shot_routing', e.target.checked)} />
            <span>逐镜路由(主角特写走云,空镜走本地)</span>
          </label>
          <Soon label="逐镜编辑(景别/动作/台词)" /><Soon label="首尾帧" />
        </div>
      </section>

      {/* ⑥ 音频 */}
      <section className="dc-sec">
        <div className="dc-sec__head"><span className="dc-sec__num">⑥</span><h2>音频</h2></div>
        <div className="dc-grid">
          <label className="dc-field"><span className="dc-field__label">语言</span>
            <select value={f.language} onChange={e => set('language', e.target.value)}>
              {LANGUAGES.map(l => <option key={l.v} value={l.v}>{l.l}</option>)}
            </select>
          </label>
          <label className="dc-field"><span className="dc-field__label">配音引擎</span>
            <select value={f.audio_provider ?? ''} onChange={e => set('audio_provider', e.target.value)}>
              {AUDIO.map(a => <option key={a.v} value={a.v}>{a.l}</option>)}
            </select>
          </label>
          <Soon label="音色 / 语速 / 情绪" /><Soon label="BGM 配乐" /><Soon label="音效 / 混音" />
        </div>
      </section>

      {/* ⑦ 成片规格 */}
      <section className="dc-sec">
        <div className="dc-sec__head"><span className="dc-sec__num">⑦</span><h2>成片规格</h2></div>
        <div className="dc-grid">
          <label className="dc-field"><span className="dc-field__label">画质</span>
            <select value={f.quality_profile} onChange={e => set('quality_profile', e.target.value)}>
              {QUALITIES.map(q => <option key={q.v} value={q.v}>{q.l}</option>)}
            </select>
          </label>
          <Soon label="字幕样式 / 双语" /><Soon label="片头 / 片尾" /><Soon label="封面 / 导出格式" />
        </div>
      </section>

      {/* ⑧ 生产 */}
      <section className="dc-sec">
        <div className="dc-sec__head"><span className="dc-sec__num">⑧</span><h2>生产</h2></div>
        <div className="dc-grid">
          <label className="dc-field"><span className="dc-field__label">执行预设</span>
            <select value={f.preset ?? ''} onChange={e => set('preset', e.target.value)}>
              {EXEC.map(x => <option key={x.v} value={x.v}>{x.l}</option>)}
            </select>
          </label>
          <label className="dc-field"><span className="dc-field__label">引擎</span>
            <select value={f.video_provider ?? ''} onChange={e => set('video_provider', e.target.value)}>
              {VIDEO.map(v => <option key={v.v} value={v.v}>{v.l}</option>)}
            </select>
          </label>
          <label className="dc-field"><span className="dc-field__label">预算上限 $</span>
            <input type="number" min={0} step="0.5" placeholder="可选"
              value={f.budget_usd ?? ''} onChange={e => set('budget_usd', e.target.value ? Number(e.target.value) : undefined)} />
          </label>
          <label className="dc-field"><span className="dc-field__label">返工轮数</span>
            <input type="number" min={0} max={3} placeholder="默认 1"
              value={f.auto_rework_rounds ?? ''} onChange={e => set('auto_rework_rounds', e.target.value ? Number(e.target.value) : undefined)} />
          </label>
        </div>
      </section>

      <div className="dc-actions">
        <button type="button" className="dc-btn" onClick={preview} disabled={busy !== null}>
          {busy === 'plan' ? '评估中…' : '预览可行性'}
        </button>
        <button type="submit" className="dc-btn dc-btn--primary" disabled={busy !== null}>
          {busy === 'episode' ? '产集中…' : '直接产集'}
        </button>
      </div>

      {err && <div className="dc-err">{err}</div>}

      {plan && (
        <div className="dc-card">
          <div className="dc-card__head">可行性预览 · {plan.plan.feasible ? '✓ 可行' : '✗ 不可行'}</div>
          <div className="dc-kv">
            <span>时长档</span><b>{plan.plan.duration_archetype}</b>
            <span>视频引擎</span><b>{plan.plan.video_provider}</b>
            <span>预估成本</span><b>${plan.plan.estimated_usd.toFixed(2)}</b>
            <span>分镜</span><b>{plan.shot_prompts.length}</b>
          </div>
          <ol className="dc-shots">{plan.shot_prompts.map((s, i) => <li key={i}>{s}</li>)}</ol>
        </div>
      )}

      {episode && (
        <div className="dc-card dc-card--ok">
          <div className="dc-card__head">已产集 · 后台出片中</div>
          <div className="dc-kv">
            <span>任务 ID</span><b className="dc-mono">{episode.task_id}</b>
            <span>状态</span><b>{episode.status}</b>
            <span>画幅 / 画质</span><b>{episode.spec?.aspect_ratio} · {episode.spec?.quality_profile}</b>
            <span>引擎</span><b>{episode.spec?.video_provider}</b>
            <span>锁脸</span><b>{episode.spec?.subject_locked ? '是' : '否'}</b>
            <span>预估成本</span><b>${episode.plan.estimated_usd.toFixed(2)}</b>
          </div>
          <p className="dc-hint">出片后体检不合格会自动定向返工(L3);完成后在「我的」查看。</p>
        </div>
      )}
    </form>
  );
}
