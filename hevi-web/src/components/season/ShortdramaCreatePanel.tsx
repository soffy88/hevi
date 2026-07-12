/**
 * ShortdramaCreatePanel — 短剧创建入口(SPEC-001 §7 阶段1"补上的建季"能力)
 * 手稿 → StoryGraph 抽取 + 剧集规划(后台异步)→ 人工审阅 → 角色绑定 → 确认派发(真实生成)。
 * 布局仿 TongjianConsole(表单/轮询)+ ScriptReviewPanel(审阅/重生成),复用同一套 .tj-* 样式。
 */
'use client';

import { useEffect, useRef, useState } from 'react';
import { shortdramaApi, subjectApi } from '@/lib/api-client';
import { syncAuthToken } from '@/lib/auth-store';
import type { ShortdramaRunStatus, Subject } from '@/types/api';

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
  const [videoProvider, setVideoProvider] = useState(VIDEO_PROVIDER_OPTIONS[0].value);
  const [durationArchetype, setDurationArchetype] = useState(DURATION_OPTIONS[0].value);
  const [seriesBudgetUsd, setSeriesBudgetUsd] = useState(20);

  const [busy, setBusy] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<ShortdramaRunStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [charChoices, setCharChoices] = useState<Record<string, CharChoice>>({});
  const [existingSubjects, setExistingSubjects] = useState<Subject[] | null>(null);
  const [uploadingChar, setUploadingChar] = useState<string | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);

  // 轮询进度(提交后 / 重新规划后)
  useEffect(() => {
    if (!runId) return;
    const poll = async () => {
      try {
        syncAuthToken();
        const s = await shortdramaApi.getStatus(runId);
        setStatus(s);
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
            <span className="tj-run-badge tj-run-badge--running">⟳ 抽取 StoryGraph + 剧集规划中…</span>
          </div>
          <p className="tj-hint">B0 结构化抽取 + 剧集规划器最多重试 5 轮通过自我批判门，请稍候（约 1-2 分钟）。</p>
        </div>
      )}

      {status && (awaitingCharacters || dispatching || failed) && (
        <div className="tj-progress">
          <div className="tj-progress__head">
            <span className={`tj-run-badge tj-run-badge--${dispatching ? 'running' : failed ? 'failed' : 'completed'}`}>
              {dispatching ? '⟳ 派发中…' : failed ? '✗ 失败' : '📝 待审阅 + 角色绑定'}
            </span>
          </div>

          {failed && <p className="tj-hint">{status.error ?? '未知错误'}</p>}

          {status.gate && !status.gate.passed && (
            <div className="sd-gate-warn">
              <div className="sd-gate-warn__head">⚠ 剧集规划自我批判门未完全通过（仍可继续，或重新规划）</div>
              <ul>{status.gate.errors.map((m, i) => <li key={i}>{m}</li>)}</ul>
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

          {awaitingCharacters && status.characters && (
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
