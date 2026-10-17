/**
 * ShortdramaCreatePanel — 短剧创建入口(SPEC-001 §7 阶段1"补上的建季"能力)
 * 手稿 → StoryGraph 抽取 + 剧集规划(后台异步)→ 人工审阅 → 角色绑定 → 确认派发(真实生成)。
 * 布局仿 TongjianConsole(表单/轮询)+ ScriptReviewPanel(审阅/重生成),复用同一套 .tj-* 样式。
 */
'use client';

import { useEffect, useRef, useState } from 'react';
import { shortdramaApi, subjectApi } from '@/lib/api-client';
import { syncAuthToken } from '@/lib/auth-store';
import type { ShortdramaRunStatus, Subject, ProductionFormVal } from '@/types/api';

const PRODUCTION_FORMS: { value: ProductionFormVal; label: string; desc: string }[] = [
  { value: 'live_action', label: '🎬 真人实拍', desc: '电影级真人短剧，面部识别为主要通道' },
  { value: 'dynamic_comic_2d', label: '📖 2D 动态漫（漫剧）', desc: '漫画/动画风格，剪影+色彩为主要通道' },
  { value: 'stylized_3d', label: '🎮 风格化 3D', desc: '3D 渲染风格，几何形体为主要通道' },
  { value: 'inkwash', label: '🖌️ 水墨动画', desc: '中国传统水墨画风，笔触+留白为主要通道' },
  { value: 'paper_stop_motion', label: '✂️ 纸感定格动画', desc: '手工剪纸/折纸纹理，逐帧动画风格' },
];

const DURATION_OPTIONS: { value: string; label: string }[] = [
  { value: '1-5min', label: '1-5 分钟(推荐)' },
  { value: '5-15min', label: '5-15 分钟' },
  { value: '15-45min', label: '15-45 分钟' },
];

const VIDEO_PROVIDER_OPTIONS: { value: string; label: string }[] = [
  { value: 'happyhorse_1_1_maas_lock', label: '云端锁脸(推荐 · 已验证真实可用)' },
  { value: 'happyhorse_1_1_maas', label: '云端(不锁脸)' },
];

function errText(e: unknown): string {
  if (e instanceof Error && e.message === 'NOT_AUTHENTICATED') return '请先登录';
  return e instanceof Error ? e.message : '出错了';
}

type CharChoice = { mode: 'auto' | 'existing'; subjectId?: string };

export function ShortdramaCreatePanel({ onDispatched }: { onDispatched?: (seriesId: string) => void }) {
  const [sourceName, setSourceName] = useState('');
  const [rawText, setRawText] = useState('');
  const [targetEpisodes, setTargetEpisodes] = useState(3);
  const [productionForm, setProductionForm] = useState<ProductionFormVal>('live_action');
  const [genre, setGenre] = useState('');
  const [videoProvider, setVideoProvider] = useState(VIDEO_PROVIDER_OPTIONS[0].value);
  const [durationArchetype, setDurationArchetype] = useState(DURATION_OPTIONS[0].value);
  // 默认 $20 是错的实测教训(2026-07-12):happyhorse_1_1_maas_lock + 1-5min 档,
  // 单集默认时长下单集就约 $25(还没算返工重生成——G1 真实跑发现返工几乎必然触发,
  // 实际常翻倍),3 集默认目标下 $20 连第一集都不够,一定会被 check_series_budget
  // 秒拒。改成按目标集数估的更现实的默认值,并在下面加一行提示说明怎么估的。
  const [seriesBudgetUsd, setSeriesBudgetUsd] = useState(3 * 50);

  const [busy, setBusy] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<ShortdramaRunStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // 每次轮询成功都自增——单纯给"派发中"这类长时间不变的状态提供肉眼可见的心跳,
  // 不然用户看着同一句"派发中…"半小时不动,分不清是卡住了还是后台真的在跑。
  const [pollCount, setPollCount] = useState(0);

  const [charChoices, setCharChoices] = useState<Record<string, CharChoice>>({});
  const [existingSubjects, setExistingSubjects] = useState<Subject[] | null>(null);
  const [uploadingChar, setUploadingChar] = useState<string | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  // run 状态存在后端(内存),切走页面再回来这个组件会重新挂载、丢光 state——挂载时
  // 找回仍未完结的 run,否则用户会以为任务凭空消失了(其实后端还在跑)。同
  // TongjianConsole 的惯例。
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        syncAuthToken();
        const runs = await shortdramaApi.listRuns(); // 已按 created_at 倒序
        // 只看最近一条:FAILED 也算"找回"——之前漏了这个状态,导致派发阶段失败
        // (角色/分集数据都还在,本可以直接重试)的 run 一旦页面刷新/重挂载就再也
        // 找不回来,只能眼睁睁看着变回空表单(2026-07-12 真实撞见)。只看最近一条
        // 而不是找"第一个非 DISPATCHED"——否则如果最近一次其实已经派发成功,会
        // 误把更早的一条旧失败记录翻出来。
        const mostRecent = runs[0];
        const active = mostRecent && mostRecent.status !== 'DISPATCHED' ? mostRecent : undefined;
        if (active && !cancelled) {
          setStatus(active);
          setRunId(active.run_id);
        }
      } catch {
        // 静默:找回失败不影响正常"新建一次"流程
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // 轮询进度(提交后 / 重新规划后)
  useEffect(() => {
    if (!runId) return;
    const poll = async () => {
      try {
        syncAuthToken();
        const s = await shortdramaApi.getStatus(runId);
        setStatus(s);
        setPollCount(c => c + 1);
        if (s.status === 'DISPATCHED' || s.status === 'FAILED') {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
          if (s.status === 'DISPATCHED' && s.series_id) onDispatched?.(s.series_id);
        }
      } catch {
        // 静默:网络偶发失败不清状态
      }
    };
    poll();
    pollRef.current = setInterval(poll, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // 到达角色绑定台:拉一次已有角色列表(供"选择已有角色"下拉用)
  useEffect(() => {
    if (status?.status !== 'AWAITING_CHARACTERS' || existingSubjects !== null) return;
    (async () => {
      try {
        setExistingSubjects(await subjectApi.list('character'));
      } catch {
        setExistingSubjects([]);
      }
    })();
  }, [status?.status, existingSubjects]);

  async function startRun() {
    if (!rawText.trim()) { setErr('请输入手稿原文'); return; }
    if (!sourceName.trim()) { setErr('请输入作品名'); return; }
    setErr(null);
    setBusy(true);
    setStatus(null);
    setCharChoices({});
    setExistingSubjects(null);
    try {
      const r = await shortdramaApi.startRun({
        source_name: sourceName,
        raw_text: rawText,
        target_episodes: targetEpisodes,
        production_form: productionForm,
        genre: genre || undefined,
      });
      setRunId(r.run_id);
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
    }
  }

  async function replan() {
    if (!runId) return;
    setErr(null);
    setCharChoices({});
    setExistingSubjects(null);
    try {
      await shortdramaApi.replan(runId);
      setStatus(s => (s ? { ...s, status: 'RUNNING' } : s));
    } catch (e) {
      setErr(errText(e));
    }
  }

  function setChoice(charId: string, choice: CharChoice) {
    setCharChoices(prev => ({ ...prev, [charId]: choice }));
  }

  async function uploadReference(charId: string, file: File) {
    if (!runId) return;
    setUploadingChar(charId);
    setErr(null);
    try {
      await shortdramaApi.uploadCharacterReference(runId, charId, file);
      // 上传即绑定,后端记进 run.bindings——重新拉一次状态刷新 bound 标记
      setStatus(await shortdramaApi.getStatus(runId));
    } catch (e) {
      setErr(errText(e));
    } finally {
      setUploadingChar(null);
    }
  }

  async function confirmDispatch() {
    if (!runId || !status?.characters) return;
    if (!confirm(
      `即将真实生成:共 ${status.season_plan?.episodes.length ?? 0} 集,季预算上限 $${seriesBudgetUsd}` +
      '(触发后由后台队列自动跑,不可撤回),确定开始吗?'
    )) return;
    setConfirmBusy(true);
    setErr(null);
    try {
      const bindings: Record<string, { mode: 'auto' | 'existing'; subject_id?: string | null }> = {};
      for (const c of status.characters) {
        if (c.bound) continue; // 已通过上传绑定,后端优先用它,不必再传
        const choice = charChoices[c.char_id];
        if (choice?.mode === 'existing' && choice.subjectId) {
          bindings[c.char_id] = { mode: 'existing', subject_id: choice.subjectId };
        }
      }
      await shortdramaApi.confirm(runId, {
        bindings,
        video_provider: videoProvider,
        duration_archetype: durationArchetype,
        series_budget_usd: seriesBudgetUsd,
      });
      setStatus(s => (s ? { ...s, status: 'DISPATCHING' } : s));
    } catch (e) {
      setErr(errText(e));
    } finally {
      setConfirmBusy(false);
    }
  }

  function reset() {
    setRunId(null);
    setStatus(null);
    setCharChoices({});
    setExistingSubjects(null);
    setErr(null);
  }

  const planning = runId && (!status || status.status === 'PENDING' || status.status === 'RUNNING');
  const awaitingCharacters = status?.status === 'AWAITING_CHARACTERS';
  const dispatching = status?.status === 'DISPATCHING';
  const dispatched = status?.status === 'DISPATCHED';
  const failed = status?.status === 'FAILED';
  // 失败但角色/分集数据还在(=规划阶段其实成功了,是派发阶段——建角色参考图或
  // dispatch_season——失败),不该逼用户重新规划、白白丢掉已经生成好的 StoryGraph/
  // SeasonPlan,应该让他直接重试(后端 confirm 现在也接受从 FAILED 状态重试)。
  const canBindCharacters = (awaitingCharacters || failed) && !!status?.characters;

  return (
    <div className="tj sd">
      {!runId && (
        <>
          <section className="tj-sec">
            <div className="tj-sec__head">
              <span className="tj-sec__num">①</span>
              <h2>手稿 + 基础配置</h2>
            </div>
            <label className="tj-field">
              <span className="tj-field__label">作品名</span>
              <input value={sourceName} onChange={e => setSourceName(e.target.value)} placeholder="崂山道士" />
            </label>
            <div className="tj-field">
              <span className="tj-field__label">生产形态（决定视觉风格和渲染管线）</span>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '8px' }}>
                {PRODUCTION_FORMS.map(f => (
                  <button
                    type="button"
                    key={f.value}
                    onClick={() => setProductionForm(f.value)}
                    style={{
                      padding: '12px',
                      borderRadius: '8px',
                      border: productionForm === f.value ? '2px solid var(--primary, #3b82f6)' : '1px solid var(--border, #e2e8f0)',
                      background: productionForm === f.value ? 'var(--primary-bg, #eff6ff)' : 'transparent',
                      cursor: 'pointer',
                      textAlign: 'left',
                      transition: 'all 0.15s',
                    }}
                  >
                    <div style={{ fontWeight: 500, fontSize: '14px' }}>{f.label}</div>
                    <div style={{ fontSize: '12px', color: 'var(--muted-foreground)', marginTop: '4px' }}>{f.desc}</div>
                  </button>
                ))}
              </div>
            </div>
            <label className="tj-field">
              <span className="tj-field__label">题材标签（可选，影响故事开发和钩子取向）</span>
              <input value={genre} onChange={e => setGenre(e.target.value)} placeholder="都市打脸 / 甜宠 / 悬疑 / 修仙…" />
            </label>
            <label className="tj-field tj-field--tall">
              <span className="tj-field__label">手稿原文（小说/故事，{rawText.length} 字）</span>
              <textarea rows={10}
                placeholder="粘贴小说手稿，B0 自动抽取人物/事件/对白/关系，供剧集规划器切集…"
                value={rawText} onChange={e => setRawText(e.target.value)} />
            </label>
            <div className="tj-grid">
              <label className="tj-field">
                <span className="tj-field__label">目标集数</span>
                <input type="number" min={1} max={50} step={1}
                  value={targetEpisodes} onChange={e => setTargetEpisodes(Number(e.target.value))} />
              </label>
              <label className="tj-field">
                <span className="tj-field__label">季预算上限（美元 · 派发后由后台队列自动真实生成，超线熔断）</span>
                <input type="number" min={1} step={1}
                  value={seriesBudgetUsd} onChange={e => setSeriesBudgetUsd(Number(e.target.value))} />
                <span className="tj-hint">
                  参考:默认档单集约 $25(不含返工;返工几乎必然触发,实际常翻倍),
                  {targetEpisodes} 集建议至少 ${targetEpisodes * 50}——设太低会在派发时被
                  预算熔断直接拒绝(不是卡住,是秒拒,报错里会写清楚超了多少)
                </span>
              </label>
            </div>
            <div className="tj-field">
              <span className="tj-field__label">视频生成 provider</span>
              <div className="tj-seg">
                {VIDEO_PROVIDER_OPTIONS.map(o => (
                  <button type="button" key={o.value} data-on={videoProvider === o.value ? 'true' : undefined}
                    onClick={() => setVideoProvider(o.value)}>{o.label}</button>
                ))}
              </div>
            </div>
            <div className="tj-field">
              <span className="tj-field__label">单集时长档</span>
              <div className="tj-seg">
                {DURATION_OPTIONS.map(o => (
                  <button type="button" key={o.value} data-on={durationArchetype === o.value ? 'true' : undefined}
                    onClick={() => setDurationArchetype(o.value)}>{o.label}</button>
                ))}
              </div>
            </div>
          </section>
          <div className="tj-actions">
            <button type="button" className="tj-btn tj-btn--primary" onClick={startRun} disabled={busy}>
              {busy ? '提交中…' : '▶ 开始抽取 + 规划'}
            </button>
          </div>
        </>
      )}

      {err && <div className="tj-err">{err}</div>}

      {planning && (
        <div className="tj-progress">
          <div className="tj-progress__head">
            <span className="tj-run-badge tj-run-badge--running">
              ⟳ {status?.progress || '故事开发 + 抽取 + 规划中…'}
            </span>
          </div>
          <p className="tj-hint">
            故事开发（冲突引擎/分集地图/导演阐述）→ 结构化抽取 → 剧集规划（最多 5 轮自我批判），
            请稍候（约 2-3 分钟）。
          </p>
        </div>
      )}

      {status && (awaitingCharacters || dispatching || failed) && (
        <div className="tj-progress">
          <div className="tj-progress__head">
            <span className={`tj-run-badge tj-run-badge--${dispatching ? 'running' : failed ? 'failed' : 'completed'}`}>
              {dispatching ? '⟳ 派发中…' : failed ? '✗ 失败' : '📝 待审阅 + 角色绑定'}
            </span>
            {dispatching && (
              <span className="tj-progress__count">已轮询 {pollCount} 次 · 每 3 秒刷新一次,页面没卡住</span>
            )}
          </div>

          {dispatching && (
            <p className="tj-hint">
              {status.progress ?? '正在补齐角色绑定…'}
              {' '}
              (角色参考图 + 派发通常几分钟内完成;若长时间无变化请联系客服)
            </p>
          )}

          {failed && (
            <p className="tj-hint">
              {status.error ?? '未知错误'}
              {canBindCharacters && '（规划本身没问题，是派发/建角色这一步失败了，可以直接点下面按钮重试，不必重新规划）'}
            </p>
          )}

          {status.gate && !status.gate.passed && (
            <div className="sd-gate-warn">
              <div className="sd-gate-warn__head">
                ⚠ 剧集规划自我批判门未完全通过——不会阻止派发，可以往下滑到角色绑定，
                直接点底部"确认无误，开始真实生成"按钮继续；或点下面"重新规划"换一版
              </div>
              <ul>{status.gate.errors.map((m, i) => <li key={i}>{m}</li>)}</ul>
            </div>
          )}

          {/* 故事开发输出(对标 drama-skills develop) */}
          {status.story_brief && (
            <div className="sd-review" style={{ marginBottom: '16px', borderLeft: '3px solid var(--primary, #3b82f6)' }}>
              <div className="sd-review__block">
                <div className="sd-review__label">🎬 创作简报</div>
                <dl style={{ fontSize: '13px', margin: 0 }}>
                  {status.story_brief.theme && (
                    <><dt style={{ fontWeight: 500, color: 'var(--muted-foreground)' }}>主题</dt>
                    <dd style={{ margin: '0 0 8px' }}>{status.story_brief.theme}</dd></>
                  )}
                  {status.story_brief.conflict_engine && (
                    <><dt style={{ fontWeight: 500, color: 'var(--muted-foreground)' }}>冲突引擎</dt>
                    <dd style={{ margin: '0 0 8px' }}>{status.story_brief.conflict_engine}</dd></>
                  )}
                  {status.story_brief.escalation_mechanism && (
                    <><dt style={{ fontWeight: 500, color: 'var(--muted-foreground)' }}>升级机制</dt>
                    <dd style={{ margin: '0 0 8px' }}>{status.story_brief.escalation_mechanism}</dd></>
                  )}
                  {status.story_brief.audience_payoff && (
                    <><dt style={{ fontWeight: 500, color: 'var(--muted-foreground)' }}>观众回报</dt>
                    <dd style={{ margin: 0 }}>{status.story_brief.audience_payoff}</dd></>
                  )}
                </dl>
              </div>
            </div>
          )}

          {status.episode_map && status.episode_map.length > 0 && (
            <div className="sd-review" style={{ marginBottom: '16px' }}>
              <div className="sd-review__block">
                <div className="sd-review__label">📋 分集地图（{status.episode_map.length}）</div>
                <div style={{ display: 'grid', gap: '8px' }}>
                  {status.episode_map.map(ep => (
                    <div key={ep.ep_number} style={{
                      padding: '8px 12px', borderRadius: '6px',
                      background: 'var(--muted, #f7fafc)', fontSize: '13px',
                    }}>
                      <strong>第{ep.ep_number}集</strong>
                      {ep.goal && <> · 目标: {ep.goal}</>}
                      {ep.hook && <div style={{ color: 'var(--muted-foreground)', marginTop: '2px' }}>🪝 {ep.hook}</div>}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {status.director_brief && (
            <div className="sd-review" style={{ marginBottom: '16px' }}>
              <div className="sd-review__block">
                <div className="sd-review__label">🎥 导演阐述</div>
                <dl style={{ fontSize: '13px', margin: 0 }}>
                  {status.director_brief.visual_direction && (
                    <><dt style={{ fontWeight: 500, color: 'var(--muted-foreground)' }}>视觉方向</dt>
                    <dd style={{ margin: '0 0 4px' }}>{status.director_brief.visual_direction}</dd></>
                  )}
                  {status.director_brief.tone && (
                    <><dt style={{ fontWeight: 500, color: 'var(--muted-foreground)' }}>基调</dt>
                    <dd style={{ margin: '0 0 4px' }}>{status.director_brief.tone}</dd></>
                  )}
                  {status.director_brief.visual_constraints.length > 0 && (
                    <><dt style={{ fontWeight: 500, color: 'var(--muted-foreground)' }}>视觉约束</dt>
                    <dd style={{ margin: 0 }}>{status.director_brief.visual_constraints.join('、')}</dd></>
                  )}
                </dl>
              </div>
            </div>
          )}

          {status.story_graph && (
            <div className="sd-review">
              <div className="sd-review__block">
                <div className="sd-review__label">人物（{status.story_graph.characters.length}）</div>
                <div className="sd-chips">
                  {status.story_graph.characters.map(c => (
                    <span key={c.char_id} className="sd-chip" title={c.description}>
                      {c.name}{c.role ? `·${c.role}` : ''}
                    </span>
                  ))}
                </div>
              </div>
              {status.story_graph.relationships.length > 0 && (
                <div className="sd-review__block">
                  <div className="sd-review__label">关系</div>
                  <ul className="sd-list">
                    {status.story_graph.relationships.map((r, i) => {
                      const name = (cid: string) => status.story_graph!.characters.find(c => c.char_id === cid)?.name ?? cid;
                      return <li key={i}>{name(r.from_char)} → {name(r.to_char)}：{r.relation_type}</li>;
                    })}
                  </ul>
                </div>
              )}
              {status.season_plan && (
                <div className="sd-review__block">
                  <div className="sd-review__label">分集（{status.season_plan.episodes.length}）</div>
                  <ul className="sd-list">
                    {status.season_plan.episodes.map(ep => (
                      <li key={ep.ep_number}>
                        第{ep.ep_number}集 · {ep.title || '(未命名)'}
                        {ep.target_emotion_arc ? ` — ${ep.target_emotion_arc}` : ''}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {(awaitingCharacters || failed) && runId && (
            <div className="tj-actions">
              <button type="button" className="tj-btn" onClick={replan}>↻ 重新规划</button>
            </div>
          )}

          {canBindCharacters && status.characters && (
            <>
              <div className="sd-review__label" style={{ marginTop: 16 }}>②角色绑定</div>
              <div className="sd-chars">
                {status.characters.map(c => {
                  const choice = charChoices[c.char_id] ?? { mode: 'auto' as const };
                  return (
                    <div key={c.char_id} className="sd-char-row">
                      <span className="sd-char-row__name">{c.name}</span>
                      {c.bound ? (
                        <span className="sd-char-row__bound">✓ 已绑定（{c.subject_id?.slice(0, 8)}）</span>
                      ) : (
                        <div className="sd-char-row__opts">
                          <label className="sd-char-row__opt">
                            <input type="radio" name={`mode-${c.char_id}`}
                              checked={choice.mode === 'auto'}
                              onChange={() => setChoice(c.char_id, { mode: 'auto' })} />
                            自动生成参考图
                          </label>
                          <label className="sd-char-row__opt">
                            <input type="radio" name={`mode-${c.char_id}`}
                              checked={choice.mode === 'existing' && !choice.subjectId}
                              onChange={() => setChoice(c.char_id, { mode: 'existing' })} />
                            选择已有角色
                            {choice.mode === 'existing' && (
                              <select
                                value={choice.subjectId ?? ''}
                                onChange={e => setChoice(c.char_id, { mode: 'existing', subjectId: e.target.value })}
                              >
                                <option value="">（选一个）</option>
                                {(existingSubjects ?? []).map(s => (
                                  <option key={s.subject_id} value={s.subject_id}>{s.name}</option>
                                ))}
                              </select>
                            )}
                          </label>
                          <label className="sd-char-row__opt sd-char-row__opt--upload">
                            上传参考图
                            <input type="file" accept="image/*" disabled={uploadingChar === c.char_id}
                              onChange={e => { const f = e.target.files?.[0]; if (f) uploadReference(c.char_id, f); }} />
                            {uploadingChar === c.char_id && <span> 上传中…</span>}
                          </label>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              <div className="tj-actions">
                <button type="button" className="tj-btn tj-btn--primary sd-confirm-btn"
                  onClick={confirmDispatch} disabled={confirmBusy}>
                  {confirmBusy ? '提交中…' : `⚠ 确认无误，开始真实生成（季预算 $${seriesBudgetUsd}）`}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {dispatched && status?.series_id && (
        <div className="tj-result">
          <div className="tj-result__head">✓ 已派发，正在真实生成</div>
          <p className="tj-hint">series_id: {status.series_id}，请在左侧短剧列表查看生成进度。</p>
          <div className="tj-actions">
            <button type="button" className="tj-btn" onClick={reset}>+ 再建一部</button>
          </div>
        </div>
      )}
    </div>
  );
}
