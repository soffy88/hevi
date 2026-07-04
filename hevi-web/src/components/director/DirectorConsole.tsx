/**
 * DirectorConsole — 导演控制台(§3 L4,专业片表单)
 * 一句话剧情 + 8 层结构化片表单 →「预览可行性」(不建任务)或「直接产集」(建任务+后台出片,含 L3 返工)。
 * 已接后端的字段做实控件;缺素材/模型/独立工程的标「规划中」禁用;当前 provider 架构性
 * 不支持的(如额外风格参考图条件化)标「不支持」并写明原因 —— 两者都不作假。
 */
'use client';

import { useState, useEffect, type FormEvent } from 'react';
import { directorApi, subjectApi } from '@/lib/api-client';
import type { DirectorPlanResult, DirectorEpisodeResult, DirectorEpisodePayload, DirectorRenderResult, Subject } from '@/types/api';

const PRESETS = [
  '科普', '严肃', '搞笑', '电影感', '赛博朋克', '国风水墨', '治愈系', '商务专业', '美食', '旅行Vlog',
  '产品广告', '新闻播报', '悬疑', '史诗', '复古胶片', '动漫', '极简', '自然纪录片', '时尚', '运动',
];
const MOODS = ['', '温暖', '悲伤', '紧张', '浪漫', '幽默', '励志', '平静', '惊悚', '怀旧', '梦幻'];
const GENRES = ['', '剧情', '科普', '广告', 'Vlog', '新闻', '纪录片', '教学', '宣传片'];
const DURATIONS = [
  { v: 'short', l: '极短 ~10s' }, { v: '1-5min', l: '1–5 分钟' }, { v: '5-15min', l: '5–15 分钟' },
  { v: '15-45min', l: '15–45 分钟' }, { v: '45min+', l: '45 分钟+' },
];
const ASPECTS = [{ v: '9:16', l: '竖 9:16' }, { v: '16:9', l: '横 16:9' }, { v: '1:1', l: '方 1:1' }];
const QUALITIES = [{ v: 'standard', l: '标清 720p' }, { v: 'high', l: '高清 1080p' }, { v: 'ultra', l: '超清 4K' }];
const TRANSITIONS = ['fade', 'cut', 'wipeleft', 'slideup', 'dissolve'];
const LANGUAGES = [{ v: 'zh', l: '中文' }, { v: 'en', l: 'English' }, { v: 'ja', l: '日本語' }];
const BILINGUAL_TARGETS = [{ v: 'en', l: 'English' }, { v: 'ja', l: '日本語' }, { v: 'ko', l: '한국어' }, { v: 'es', l: 'Español' }];
const AUDIO = [{ v: 'vibevoice', l: 'VibeVoice(本地多说话人)' }, { v: 'edge_tts', l: 'Edge TTS(多语云)' },
  { v: 'ltx2_native', l: 'LTX-2 原生音' }, { v: 'duix', l: 'DUIX 数字人口型' }];
const VIDEO = [{ v: 'auto', l: '自动路由(最省)' }, { v: 'wan_local', l: 'Wan 本地(零成本)' },
  { v: 'ltx2_cloud', l: 'LTX-2 云' }, { v: 'veo3', l: 'Veo3(写实+原生音)' }, { v: 'kling_v2', l: 'Kling v2' },
  { v: 'hailuo', l: '海螺 02' }, { v: 'wan_cloud', l: 'Wan 云' }];
const EXEC = [{ v: '', l: '不用预设' }, { v: 'economy', l: '经济(本地零成本)' },
  { v: 'balanced', l: '均衡(默认)' }, { v: 'fast', l: '极速(云高清)' }];
const BGM_MOODS = [{ v: '', l: '无配乐' }, { v: 'warm', l: '温暖' }, { v: 'upbeat', l: '轻快' },
  { v: 'tense', l: '紧张' }, { v: 'epic', l: '史诗' }, { v: 'mystery', l: '悬疑' }];
const SFX_OPTS = [{ v: '', l: '无音效' }, { v: 'whoosh', l: '呼啸' }, { v: 'ding', l: '叮' },
  { v: 'impact', l: '砰(冲击)' }, { v: 'pop', l: '啵' }, { v: 'chime', l: '叮铃(过场)' }];
// 与 hevi/audio/edge_tts_custom.py CURATED_VOICES 对齐,仅 audio_provider=edge_tts 时生效。
const VOICE_OPTS = [{ v: '', l: '自动(按语言)' }, { v: 'zh_female_standard', l: '中文女声·标准' },
  { v: 'zh_female_warm', l: '中文女声·温暖' }, { v: 'zh_male_standard', l: '中文男声·标准' },
  { v: 'zh_male_deep', l: '中文男声·低沉' }, { v: 'en_female_standard', l: '英文女声·标准' },
  { v: 'en_male_standard', l: '英文男声·标准' }];
const RATE_OPTS = [{ v: '', l: '正常' }, { v: '-20%', l: '慢 -20%' }, { v: '-10%', l: '略慢 -10%' },
  { v: '+10%', l: '略快 +10%' }, { v: '+20%', l: '快 +20%' }, { v: '+30%', l: '很快 +30%' }];
const SUBTITLE_STYLES = [{ v: 'default', l: '默认' }, { v: 'bold_yellow', l: '粗体黄' },
  { v: 'large_white', l: '大号白字' }, { v: 'compact', l: '紧凑' }];

const EMPTY: DirectorEpisodePayload = {
  text: '', duration_archetype: '1-5min', aspect_ratio: '9:16',
  mood: '', genre: '', narrative_hook: '',
  character_subject_ids: [], subject_id: '', avatar_portrait: '',
  num_characters: 1, scene_notes: '', props: '',
  style_preset: '电影感', prompt_style: '', prompt_lighting: '', prompt_camera: '', prompt_color_grade: '',
  transition: 'fade', per_shot_routing: false, language: 'zh',
  audio_provider: 'vibevoice', bgm: '', sfx: '', voice_rate: '', voice_pitch: '', voice_name: '',
  quality_profile: 'standard', subtitle_style: 'default', bilingual_language: '',
  intro_clip: '', outro_clip: '',
  preset: '', video_provider: 'auto',
  budget_usd: undefined, auto_rework_rounds: undefined,
};

function errText(e: unknown): string {
  if (e instanceof Error && e.message === 'NOT_AUTHENTICATED') return '请先登录';
  if (e instanceof Error && e.message.startsWith('402')) return '预算不足或超额,无法产集';
  return e instanceof Error ? e.message : '出错了';
}

// 规划中(未实装,缺素材/模型/独立工程)—— 展示但禁用,不作假
function Soon({ label }: { label: string }) {
  return (
    <div className="dc-field dc-field--soon">
      <span className="dc-field__label">{label}</span>
      <span className="dc-chip dc-chip--soon">规划中</span>
    </div>
  );
}

// 当前 provider 架构性不支持(非"还没做",是"做不了")—— 写明原因,不藏
function NotSupported({ label, reason }: { label: string; reason: string }) {
  return (
    <div className="dc-field dc-field--unsupported" title={reason}>
      <span className="dc-field__label">{label}</span>
      <span className="dc-chip dc-chip--unsupported">不支持</span>
      <span className="dc-field__reason">{reason}</span>
    </div>
  );
}

export function DirectorConsole() {
  const [f, setF] = useState<DirectorEpisodePayload>(EMPTY);
  const [numShots, setNumShots] = useState(4);
  const [chars, setChars] = useState<Subject[]>([]);
  const [bilingual, setBilingual] = useState(false);
  const [busy, setBusy] = useState<'plan' | 'episode' | 'render' | null>(null);
  const [plan, setPlan] = useState<DirectorPlanResult | null>(null);
  const [episode, setEpisode] = useState<DirectorEpisodeResult | null>(null);
  const [shots, setShots] = useState<string[]>([]);
  const [rendered, setRendered] = useState<DirectorRenderResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    subjectApi.list('character').then(setChars).catch(() => setChars([]));
  }, []);

  const set = <K extends keyof DirectorEpisodePayload>(k: K, v: DirectorEpisodePayload[K]) =>
    setF(prev => ({ ...prev, [k]: v }));

  function toggleCharacter(id: string) {
    setF(prev => {
      const cur = prev.character_subject_ids ?? [];
      const next = cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id];
      return { ...prev, character_subject_ids: next };
    });
  }

  function buildPayload(): DirectorEpisodePayload {
    const p: DirectorEpisodePayload = { ...f, bilingual_language: bilingual ? (f.bilingual_language || 'en') : '' };
    // 空串 → 省略,交后端默认/自动
    (['subject_id', 'avatar_portrait', 'prompt_style', 'prompt_lighting', 'prompt_camera',
      'prompt_color_grade', 'preset', 'mood', 'genre', 'narrative_hook', 'scene_notes', 'props',
      'sfx', 'voice_rate', 'voice_pitch', 'voice_name', 'bilingual_language', 'intro_clip',
      'outro_clip'] as (keyof DirectorEpisodePayload)[]).forEach(k => {
      if (!p[k]) delete p[k];
    });
    if (!p.character_subject_ids?.length) delete p.character_subject_ids;
    return p;
  }

  async function preview() {
    if (!f.text.trim()) { setErr('先写一句剧情'); return; }
    setBusy('plan'); setErr(null); setEpisode(null); setRendered(null);
    try {
      const p = await directorApi.plan(f.text.trim(), numShots);
      setPlan(p);
      setShots(p.shot_prompts);  // 逐镜编辑种子
    } catch (e) { setErr(errText(e)); } finally { setBusy(null); }
  }

  // 逐镜编辑回路:用改过的每镜 prompt 覆盖图节点 → 执行 + 装配成片
  async function render() {
    if (!plan) return;
    setBusy('render'); setErr(null);
    try {
      const gnodes = (plan.graph.nodes as Record<string, unknown>[]).map(n => ({ ...n }));
      let si = 0;
      for (const n of gnodes) {
        if (n.node_type === 'video') {
          n.config = { ...(n.config as Record<string, unknown> ?? {}), prompt: shots[si] ?? '' };
          si++;
        }
      }
      setRendered(await directorApi.render({
        name: '导演分镜', topic: f.text.slice(0, 60),
        nodes: gnodes, edges: plan.graph.edges as Record<string, unknown>[],
        quality_profile: f.quality_profile, aspect_ratio: f.aspect_ratio,
        transition: f.transition, bgm: f.bgm || undefined, sfx: f.sfx || undefined,
        intro_clip: f.intro_clip || undefined, outro_clip: f.outro_clip || undefined,
      }));
    } catch (e) { setErr(errText(e)); } finally { setBusy(null); }
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
          <label className="dc-field"><span className="dc-field__label">情绪基调</span>
            <select value={f.mood ?? ''} onChange={e => set('mood', e.target.value)}>
              {MOODS.map(m => <option key={m} value={m}>{m || '不指定'}</option>)}
            </select>
          </label>
          <label className="dc-field"><span className="dc-field__label">题材类型</span>
            <select value={f.genre ?? ''} onChange={e => set('genre', e.target.value)}>
              {GENRES.map(g => <option key={g} value={g}>{g || '不指定'}</option>)}
            </select>
          </label>
          <label className="dc-field dc-field--wide"><span className="dc-field__label">叙事钩子(开场 3 秒抓手)</span>
            <input placeholder="例:一声枪响划破雪原的寂静" value={f.narrative_hook ?? ''}
              onChange={e => set('narrative_hook', e.target.value)} />
          </label>
        </div>
      </section>

      {/* ② 角色 */}
      <section className="dc-sec">
        <div className="dc-sec__head"><span className="dc-sec__num">②</span><h2>角色</h2></div>
        <div className="dc-grid">
          <div className="dc-field dc-field--wide"><span className="dc-field__label">角色(多选;首个跨镜锁脸,其余仅入人设)</span>
            {chars.length === 0 ? (
              <p className="dc-hint">主体库还没有角色 —— 去「主体库」建一个带参考图的角色,这里就能绑定。</p>
            ) : (
              <div className="dc-charlist">
                {chars.map(c => (
                  <label key={c.subject_id} className="dc-char">
                    <input type="checkbox" checked={(f.character_subject_ids ?? []).includes(c.subject_id)}
                      onChange={() => toggleCharacter(c.subject_id)} />
                    <span>{c.name}</span>
                    {f.character_subject_ids?.[0] === c.subject_id && <span className="dc-char__lock">锁脸</span>}
                  </label>
                ))}
              </div>
            )}
          </div>
          <label className="dc-field"><span className="dc-field__label">角色数</span>
            <input type="number" min={1} max={6} value={f.num_characters}
              onChange={e => set('num_characters', Number(e.target.value))} />
          </label>
          <label className="dc-field"><span className="dc-field__label">数字人肖像(图路径/URL)</span>
            <input placeholder="留空=不用数字人" value={f.avatar_portrait ?? ''}
              onChange={e => set('avatar_portrait', e.target.value)} />
          </label>
          <NotSupported label="多身份锁脸" reason="provider 的 i2v 每镜只吃 1 张参考图,仅首个角色的脸能跨镜锁定" />
        </div>
      </section>

      {/* ③ 场景 */}
      <section className="dc-sec">
        <div className="dc-sec__head"><span className="dc-sec__num">③</span><h2>场景</h2></div>
        <div className="dc-grid">
          <label className="dc-field"><span className="dc-field__label">光线 / 时间氛围</span>
            <input placeholder="例:黄昏暖光 / 夜晚霓虹 / 清晨薄雾" value={f.prompt_lighting ?? ''}
              onChange={e => set('prompt_lighting', e.target.value)} />
          </label>
          <label className="dc-field dc-field--wide"><span className="dc-field__label">场景设定(地点/室内外)</span>
            <input placeholder="例:雪山之巅的破旧木屋,室外为主" value={f.scene_notes ?? ''}
              onChange={e => set('scene_notes', e.target.value)} />
          </label>
          <label className="dc-field dc-field--wide"><span className="dc-field__label">关键道具 / 陈设</span>
            <input placeholder="例:一把生锈的猎枪,一盏油灯" value={f.props ?? ''}
              onChange={e => set('props', e.target.value)} />
          </label>
        </div>
        <p className="dc-hint">场景/道具是全片级的 LLM 软指令(影响整体叙事走向),不是逐镜强制约束。</p>
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
          <NotSupported label="风格参考图 mood board" reason="当前 provider(wan/ltx2/veo3/kling)均只支持 1 张身份锁定参考图,不支持额外风格参考图条件化" />
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
          <NotSupported label="首尾帧关键帧" reason="同上:provider 每镜只吃 1 张参考图,无法分别指定首帧/尾帧两张条件图" />
        </div>
        <p className="dc-hint">逐镜编辑(改景别/动作/台词)在下方「预览可行性」后的分镜列表里直接改 prompt 即可。</p>
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
          <label className="dc-field"><span className="dc-field__label">音色(仅 Edge TTS 生效)</span>
            <select value={f.voice_name ?? ''} onChange={e => set('voice_name', e.target.value)}
              disabled={f.audio_provider !== 'edge_tts'}>
              {VOICE_OPTS.map(v => <option key={v.v} value={v.v}>{v.l}</option>)}
            </select>
          </label>
          <label className="dc-field"><span className="dc-field__label">语速(仅 Edge TTS 生效)</span>
            <select value={f.voice_rate ?? ''} onChange={e => set('voice_rate', e.target.value)}
              disabled={f.audio_provider !== 'edge_tts'}>
              {RATE_OPTS.map(r => <option key={r.v} value={r.v}>{r.l}</option>)}
            </select>
          </label>
          <label className="dc-field"><span className="dc-field__label">BGM 配乐(压于旁白下)</span>
            <select value={f.bgm ?? ''} onChange={e => set('bgm', e.target.value)}>
              {BGM_MOODS.map(b => <option key={b.v} value={b.v}>{b.l}</option>)}
            </select>
          </label>
          <label className="dc-field"><span className="dc-field__label">音效</span>
            <select value={f.sfx ?? ''} onChange={e => set('sfx', e.target.value)}>
              {SFX_OPTS.map(s => <option key={s.v} value={s.v}>{s.l}</option>)}
            </select>
          </label>
          <NotSupported label="情绪化配音" reason="当前 TTS(edge-tts / vibevoice)均无情绪参数,无法调节配音情绪" />
        </div>
        {f.audio_provider === 'vibevoice' && (f.character_subject_ids?.length ?? 0) > 1 && (
          <p className="dc-hint">已选多角色 + VibeVoice:脚本里不同角色的台词会自动分配不同音色(无需额外设置)。</p>
        )}
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
          <label className="dc-field"><span className="dc-field__label">字幕样式</span>
            <select value={f.subtitle_style} onChange={e => set('subtitle_style', e.target.value)}>
              {SUBTITLE_STYLES.map(s => <option key={s.v} value={s.v}>{s.l}</option>)}
            </select>
          </label>
          <label className="dc-field dc-field--check">
            <input type="checkbox" checked={bilingual} onChange={e => setBilingual(e.target.checked)} />
            <span>双语字幕</span>
          </label>
          {bilingual && (
            <label className="dc-field"><span className="dc-field__label">译文语种</span>
              <select value={f.bilingual_language || 'en'} onChange={e => set('bilingual_language', e.target.value)}>
                {BILINGUAL_TARGETS.map(l => <option key={l.v} value={l.v}>{l.l}</option>)}
              </select>
            </label>
          )}
          <label className="dc-field"><span className="dc-field__label">片头视频(文件路径,可选)</span>
            <input placeholder="留空=无片头" value={f.intro_clip ?? ''}
              onChange={e => set('intro_clip', e.target.value)} />
          </label>
          <label className="dc-field"><span className="dc-field__label">片尾视频(文件路径,可选)</span>
            <input placeholder="留空=无片尾" value={f.outro_clip ?? ''}
              onChange={e => set('outro_clip', e.target.value)} />
          </label>
        </div>
        <p className="dc-hint">封面(自动抽帧)与导出格式(mp4/mov/webm/gif)在成片完成后可于「我的」页查看/下载 —— 建集这一步还没有成片,不在此填。</p>
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
            <span>分镜</span><b>{shots.length}</b>
          </div>
          <div className="dc-edit">
            <div className="dc-edit__head">逐镜编辑 —— 改哪镜就重出哪镜,其余复用</div>
            {shots.map((s, i) => (
              <div className="dc-edit__row" key={i}>
                <span className="dc-edit__idx">镜 {i + 1}</span>
                <textarea rows={2} value={s}
                  onChange={e => setShots(prev => prev.map((x, j) => (j === i ? e.target.value : x)))} />
              </div>
            ))}
            <button type="button" className="dc-btn dc-btn--primary" onClick={render} disabled={busy !== null}>
              {busy === 'render' ? '出片装配中…' : '按这些镜头生成成片'}
            </button>
          </div>
        </div>
      )}

      {rendered && (
        <div className="dc-card dc-card--ok">
          <div className="dc-card__head">逐镜成片 · 后台装配中</div>
          <div className="dc-kv">
            <span>任务 ID</span><b className="dc-mono">{rendered.task_id}</b>
            <span>镜头数</span><b>{rendered.shot_count}</b>
            <span>状态</span><b>{rendered.status}</b>
          </div>
          <p className="dc-hint">逐镜渲染 + 装配(可混 BGM/音效、拼片头尾);完成后在「我的」查看。</p>
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
          <p className="dc-hint">出片后体检不合格会自动定向返工(L3);完成后在「我的」查看(含封面/多格式导出)。</p>
        </div>
      )}
    </form>
  );
}
