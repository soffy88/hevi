'use client';

// INC-001 §L.2 逐镜头准备台:提取资产/对白候选 → 确认 → 把每镜推进到 ready。
// 与生成台(produce)职责分离——这里只做准备,readiness 门在后端拦产集。
// 所有 mutation 接口返回 {action, state} 聚合态,前端直接消费,不自己拼 pending 数。

import { useCallback, useEffect, useState } from 'react';

import { directorPipelineApi } from '@/lib/api-client';
import type {
  DpDesignList, DpPrepOverview, DpPrepState, DpShotList,
} from '@/types/api';

function statusBadge(status: string, skip: boolean): { label: string; cls: string } {
  if (skip) return { label: '已跳过', cls: 'dp-prep-badge--skip' };
  if (status === 'ready') return { label: '就绪', cls: 'dp-prep-badge--ready' };
  return { label: '待准备', cls: 'dp-prep-badge--pending' };
}

// 候选名 → 设计清单里锁定的 subject_id(关联资产候选时回填 linked_entity_id)。
function subjectIdFor(dl: DpDesignList, type: string, name: string): string | null {
  const pool = type === 'character' ? dl.characters : type === 'scene' ? dl.scenes : dl.props;
  return pool.find((e) => e.name === name)?.subject_id ?? null;
}

export default function ShotPreparationPanel({
  workId, shotList, designList, onBlockersChange,
}: {
  workId: string;
  shotList: DpShotList;
  designList: DpDesignList;
  onBlockersChange?: (blockers: string[]) => void;
}) {
  const [overview, setOverview] = useState<DpPrepOverview | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [prep, setPrep] = useState<DpPrepState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const refreshOverview = useCallback(async () => {
    const ov = await directorPipelineApi.preparationOverview(workId);
    setOverview(ov);
    onBlockersChange?.(ov.blockers);
  }, [workId, onBlockersChange]);

  useEffect(() => {
    refreshOverview().catch((e) => setErr(String(e)));
  }, [refreshOverview]);

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(true);
    setErr(null);
    try {
      return await fn();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  async function toggleExpand(shotId: string) {
    if (expanded === shotId) { setExpanded(null); setPrep(null); return; }
    setExpanded(shotId);
    setPrep(null);
    const st = await run(() => directorPipelineApi.preparationState(workId, shotId));
    if (st) setPrep(st);
  }

  // 任一 mutation 后:用返回的聚合态刷新当前镜 + 刷新概览(badge/blockers)。
  async function afterMutation(statePromise: Promise<{ state: DpPrepState }>) {
    const res = await run(() => statePromise);
    if (res) setPrep(res.state);
    await refreshOverview().catch(() => {});
  }

  const shots = shotList.shots;
  const byId = new Map((overview?.shots ?? []).map((s) => [s.shot_id, s]));
  const readyCount = (overview?.shots ?? []).filter((s) => s.status === 'ready').length;
  const blockers = overview?.blockers ?? [];

  return (
    <div className="dp-prep">
      <div className="dp-prep__head">
        <strong>逐镜头准备台</strong>
        <span className="dp-prep__summary">
          {readyCount}/{shots.length} 就绪
          {blockers.length > 0 && ` · ${blockers.length} 镜待确认(拦产集)`}
        </span>
      </div>
      {err && <div className="tj-err">{err}</div>}

      <div className="dp-prep__list">
        {shots.map((shot) => {
          const ov = byId.get(shot.shot_id);
          const badge = statusBadge(ov?.status ?? 'pending', ov?.skip_extraction ?? false);
          const isOpen = expanded === shot.shot_id;
          return (
            <div key={shot.shot_id} className="dp-prep-shot">
              <button
                type="button"
                className="dp-prep-shot__head"
                onClick={() => toggleExpand(shot.shot_id)}
              >
                <span className={`dp-prep-badge ${badge.cls}`}>{badge.label}</span>
                <span className="dp-prep-shot__id">{shot.shot_id}</span>
                <span className="dp-prep-shot__vp">{shot.visual_prompt || '(无画面描述)'}</span>
                <span>{isOpen ? '▾' : '▸'}</span>
              </button>

              {isOpen && (
                <div className="dp-prep-shot__body">
                  {!prep && <div className="dp-prep__muted">加载中…</div>}
                  {prep && prep.shot_id === shot.shot_id && (
                    <>
                      <div className="dp-prep__actions">
                        <button
                          type="button" className="tj-btn" disabled={busy}
                          onClick={() =>
                            afterMutation(directorPipelineApi.extractShot(workId, shot.shot_id))}
                        >
                          {prep.extracted ? '重新提取候选' : '提取候选'}
                        </button>
                        <label className="dp-prep__skip">
                          <input
                            type="checkbox" checked={prep.skip_extraction} disabled={busy}
                            onChange={(e) =>
                              afterMutation(
                                directorPipelineApi.setReadiness(
                                  workId, shot.shot_id, e.target.checked))}
                          />
                          此镜无需提取(空镜/转场)直接就绪
                        </label>
                      </div>

                      {prep.assets_overview.length > 0 && (
                        <div className="dp-prep__group">
                          <div className="dp-prep__group-title">资产候选</div>
                          {prep.assets_overview.map((c) => (
                            <div key={c.id} className="dp-prep-cand">
                              <span className={`dp-prep-cand__st dp-prep-cand__st--${c.candidate_status}`}>
                                {c.candidate_status}
                              </span>
                              <span className="dp-prep-cand__name">
                                [{c.candidate_type}] {c.candidate_name}
                              </span>
                              {c.candidate_status === 'pending' ? (
                                <>
                                  <button
                                    type="button" className="tj-btn" disabled={busy}
                                    onClick={() =>
                                      afterMutation(directorPipelineApi.confirmCandidate(
                                        workId, shot.shot_id, c.id, {
                                          kind: 'asset', status: 'linked',
                                          linked_entity_id: subjectIdFor(
                                            designList, c.candidate_type, c.candidate_name),
                                        }))}
                                  >关联</button>
                                  <button
                                    type="button" className="tj-btn" disabled={busy}
                                    onClick={() =>
                                      afterMutation(directorPipelineApi.confirmCandidate(
                                        workId, shot.shot_id, c.id,
                                        { kind: 'asset', status: 'ignored' }))}
                                  >忽略</button>
                                </>
                              ) : (
                                <button
                                  type="button" className="tj-btn" disabled={busy}
                                  onClick={() =>
                                    afterMutation(directorPipelineApi.confirmCandidate(
                                      workId, shot.shot_id, c.id,
                                      { kind: 'asset', status: 'pending' }))}
                                >撤销</button>
                              )}
                            </div>
                          ))}
                        </div>
                      )}

                      {prep.dialogue_candidates.length > 0 && (
                        <div className="dp-prep__group">
                          <div className="dp-prep__group-title">对白候选</div>
                          {prep.dialogue_candidates.map((d) => (
                            <div key={d.id} className="dp-prep-cand">
                              <span className={`dp-prep-cand__st dp-prep-cand__st--${d.candidate_status}`}>
                                {d.candidate_status}
                              </span>
                              <span className="dp-prep-cand__name">
                                {d.speaker_name || '旁白'}
                                {d.target_name ? ` → ${d.target_name}` : ''}:{d.text}
                              </span>
                              {d.candidate_status === 'pending' ? (
                                <>
                                  <button
                                    type="button" className="tj-btn" disabled={busy}
                                    onClick={() =>
                                      afterMutation(directorPipelineApi.confirmCandidate(
                                        workId, shot.shot_id, d.id,
                                        { kind: 'dialogue', status: 'accepted' }))}
                                  >接受</button>
                                  <button
                                    type="button" className="tj-btn" disabled={busy}
                                    onClick={() =>
                                      afterMutation(directorPipelineApi.confirmCandidate(
                                        workId, shot.shot_id, d.id,
                                        { kind: 'dialogue', status: 'ignored' }))}
                                  >忽略</button>
                                </>
                              ) : (
                                <button
                                  type="button" className="tj-btn" disabled={busy}
                                  onClick={() =>
                                    afterMutation(directorPipelineApi.confirmCandidate(
                                      workId, shot.shot_id, d.id,
                                      { kind: 'dialogue', status: 'pending' }))}
                                >撤销</button>
                              )}
                            </div>
                          ))}
                        </div>
                      )}

                      {prep.extracted
                        && prep.assets_overview.length === 0
                        && prep.dialogue_candidates.length === 0 && (
                        <div className="dp-prep__muted">此镜无候选(空镜)→ 已就绪</div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
