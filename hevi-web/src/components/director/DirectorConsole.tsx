/**
 * DirectorConsole — 导演控制台(§3 L4)
 * 一句话剧情 → 「预览可行性」(不建任务)或「直接产集」(建任务+后台出片,含 L3 体检返工)。
 * 直连 /api/director/plan 与 /api/director/episodes。需登录。
 */
'use client';

import { useState } from 'react';
import { directorApi } from '@/lib/api-client';
import type { DirectorPlanResult, DirectorEpisodeResult } from '@/types/api';

function errText(e: unknown): string {
  if (e instanceof Error && e.message === 'NOT_AUTHENTICATED') return '请先登录';
  if (e instanceof Error && e.message.startsWith('402')) return '预算不足,无法产集';
  return e instanceof Error ? e.message : '出错了';
}

export function DirectorConsole() {
  const [text, setText] = useState('');
  const [budget, setBudget] = useState('');
  const [busy, setBusy] = useState<'plan' | 'episode' | null>(null);
  const [plan, setPlan] = useState<DirectorPlanResult | null>(null);
  const [episode, setEpisode] = useState<DirectorEpisodeResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const budgetNum = budget.trim() ? Number(budget) : undefined;

  async function preview() {
    if (!text.trim()) { setErr('先写一句剧情'); return; }
    setBusy('plan'); setErr(null); setEpisode(null);
    try {
      setPlan(await directorApi.plan(text.trim()));
    } catch (e) { setErr(errText(e)); }
    finally { setBusy(null); }
  }

  async function produce() {
    if (!text.trim()) { setErr('先写一句剧情'); return; }
    setBusy('episode'); setErr(null);
    try {
      setEpisode(await directorApi.createEpisode(text.trim(), budgetNum));
    } catch (e) { setErr(errText(e)); }
    finally { setBusy(null); }
  }

  return (
    <div className="hevi-director">
      <h1 className="hevi-director__title">导演控制台</h1>
      <p className="hevi-director__sub">一句话剧情 → 自动可行性评估 + 分镜 → 一键产出第 N 集。</p>

      <textarea
        className="hevi-director__input"
        rows={3}
        placeholder="例如:拍一个狐狸在雪地里捕猎的 1 分钟短片,电影感"
        value={text}
        onChange={e => setText(e.target.value)}
      />
      <div className="hevi-director__controls">
        <input
          className="hevi-director__budget"
          type="number"
          min={0}
          step="0.5"
          placeholder="预算上限 $(可选)"
          value={budget}
          onChange={e => setBudget(e.target.value)}
        />
        <button className="hevi-director__btn" onClick={preview} disabled={busy !== null}>
          {busy === 'plan' ? '评估中…' : '预览可行性'}
        </button>
        <button
          className="hevi-director__btn hevi-director__btn--primary"
          onClick={produce}
          disabled={busy !== null}
        >
          {busy === 'episode' ? '产集中…' : '直接产集'}
        </button>
      </div>

      {err && <div className="hevi-director__err">{err}</div>}

      {plan && (
        <div className="hevi-director__card">
          <div className="hevi-director__card-head">
            可行性预览 · {plan.plan.feasible ? '✓ 可行' : '✗ 不可行'}
          </div>
          <div className="hevi-director__grid">
            <span>时长档</span><b>{plan.plan.duration_archetype}</b>
            <span>视频 provider</span><b>{plan.plan.video_provider}</b>
            <span>预估成本</span><b>${plan.plan.estimated_usd.toFixed(2)}</b>
            <span>角色数</span><b>{plan.plan.num_characters}</b>
          </div>
          {plan.plan.notes.length > 0 && (
            <ul className="hevi-director__notes">
              {plan.plan.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
          <div className="hevi-director__shots">
            <div className="hevi-director__shots-head">分镜 {plan.shot_prompts.length}</div>
            <ol>{plan.shot_prompts.map((s, i) => <li key={i}>{s}</li>)}</ol>
          </div>
        </div>
      )}

      {episode && (
        <div className="hevi-director__card hevi-director__card--ok">
          <div className="hevi-director__card-head">已产集 · 后台出片中</div>
          <div className="hevi-director__grid">
            <span>任务 ID</span><b className="hevi-director__mono">{episode.task_id}</b>
            <span>状态</span><b>{episode.status}</b>
            <span>provider</span><b>{episode.plan.video_provider}</b>
            <span>预估成本</span><b>${episode.plan.estimated_usd.toFixed(2)}</b>
          </div>
          <p className="hevi-director__hint">出片后如体检不合格会自动定向返工(L3),完成后可在「我的」查看。</p>
        </div>
      )}
    </div>
  );
}
