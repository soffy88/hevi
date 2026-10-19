'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { directorPipelineApi } from '@/lib/api-client';
import type {
  DpAssetCandidate,
  DpDialogueCandidate,
  DpDesignList,
  DpPrepOverview,
  DpPrepState,
  DpShotList,
} from '@/types/api';

type AssetTarget = {
  id: string;
  kind: string;
  label: string;
  matchNames: string[];
};

type Props = {
  workId: string;
  shotList: DpShotList;
  designList: DpDesignList;
  onBlockersChange: (blockers: string[]) => void;
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : '逐镜头准备操作失败';
}

function candidateStatusLabel(status: string): string {
  if (status === 'linked') return '已关联';
  if (status === 'accepted') return '已采纳';
  if (status === 'ignored') return '已忽略';
  return '待确认';
}

function normaliseName(value: string): string {
  return value.trim().toLocaleLowerCase();
}

export default function ShotPreparationPanel({
  workId,
  shotList,
  designList,
  onBlockersChange,
}: Props) {
  const [overview, setOverview] = useState<DpPrepOverview | null>(null);
  const [states, setStates] = useState<Record<string, DpPrepState>>({});
  const [selectedTargets, setSelectedTargets] = useState<Record<string, string>>({});
  const [busyShot, setBusyShot] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const shotIdsKey = shotList.shots.map((shot) => shot.shot_id).join('|');

  const assetTargets = useMemo<AssetTarget[]>(() => {
    const targets: AssetTarget[] = [];
    for (const item of designList.characters) {
      if (item.subject_id) {
        targets.push({
          id: item.subject_id,
          kind: 'character',
          label: `角色：${item.name}`,
          matchNames: [item.name, item.wardrobe, item.hairstyle].filter(Boolean),
        });
      }
    }
    for (const item of designList.scenes) {
      if (item.subject_id) {
        targets.push({
          id: item.subject_id,
          kind: 'scene',
          label: `场景：${item.name}`,
          matchNames: [item.name],
        });
      }
    }
    for (const item of designList.props) {
      if (item.subject_id) {
        targets.push({
          id: item.subject_id,
          kind: 'prop',
          label: `道具：${item.name}`,
          matchNames: [item.name],
        });
      }
    }
    return targets;
  }, [designList]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextOverview = await directorPipelineApi.preparationOverview(workId);
      const loaded = await Promise.all(
        shotList.shots.map(async (shot) => {
          try {
            return [shot.shot_id, await directorPipelineApi.preparationState(workId, shot.shot_id)] as const;
          } catch {
            return [shot.shot_id, null] as const;
          }
        }),
      );
      const nextStates: Record<string, DpPrepState> = {};
      const failedShots: string[] = [];
      for (const [shotId, state] of loaded) {
        if (state) nextStates[shotId] = state;
        else failedShots.push(shotId);
      }
      setOverview(nextOverview);
      setStates(nextStates);
      onBlockersChange([
        ...new Set([
          ...nextOverview.blockers,
          ...failedShots.map((shotId) => `分镜 ${shotId} 的准备状态读取失败`),
        ]),
      ]);
      if (failedShots.length > 0) {
        setError(`有 ${failedShots.length} 个分镜未能读取准备状态；产集操作已被阻止。`);
      }
    } catch (cause) {
      const message = errorMessage(cause);
      setError(message);
      onBlockersChange(['无法读取逐镜头准备状态，禁止开始产集']);
    } finally {
      setLoading(false);
    }
  }, [onBlockersChange, shotIdsKey, workId]);

  useEffect(() => {
    void load();
  }, [load]);

  function compatibleTargets(candidate: DpAssetCandidate): AssetTarget[] {
    if (candidate.candidate_type === 'costume') {
      return assetTargets.filter((target) => target.kind === 'character');
    }
    const matches = assetTargets.filter((target) => target.kind === candidate.candidate_type);
    return matches.length > 0 ? matches : assetTargets;
  }

  function defaultTarget(candidate: DpAssetCandidate): string {
    if (candidate.linked_entity_id) return candidate.linked_entity_id;
    const targets = compatibleTargets(candidate);
    const name = normaliseName(candidate.candidate_name);
    return targets.find((target) => target.matchNames.some((item) => normaliseName(item) === name))?.id ?? '';
  }

  async function mutateShot(shotId: string, action: () => Promise<unknown>) {
    setBusyShot(shotId);
    setError(null);
    try {
      await action();
      await load();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusyShot(null);
    }
  }

  function confirmAsset(shotId: string, candidate: DpAssetCandidate) {
    const targetId = selectedTargets[candidate.id] ?? defaultTarget(candidate);
    if (!targetId) {
      setError(`请先为资产候选“${candidate.candidate_name}”选择一个已建立的资产。`);
      return;
    }
    void mutateShot(shotId, () =>
      directorPipelineApi.confirmCandidate(workId, shotId, candidate.id, {
        kind: 'asset',
        status: 'linked',
        linked_entity_id: targetId,
      }),
    );
  }

  function ignoreAsset(shotId: string, candidate: DpAssetCandidate) {
    void mutateShot(shotId, () =>
      directorPipelineApi.confirmCandidate(workId, shotId, candidate.id, {
        kind: 'asset',
        status: 'ignored',
      }),
    );
  }

  function confirmDialogue(shotId: string, candidate: DpDialogueCandidate) {
    // Candidate IDs are stable for the extracted dialogue row and serve as the
    // durable reference until a separate dialogue-line entity is introduced.
    void mutateShot(shotId, () =>
      directorPipelineApi.confirmCandidate(workId, shotId, candidate.id, {
        kind: 'dialogue',
        status: 'accepted',
        linked_dialog_line_id: candidate.linked_dialog_line_id ?? candidate.id,
      }),
    );
  }

  function ignoreDialogue(shotId: string, candidate: DpDialogueCandidate) {
    void mutateShot(shotId, () =>
      directorPipelineApi.confirmCandidate(workId, shotId, candidate.id, {
        kind: 'dialogue',
        status: 'ignored',
      }),
    );
  }

  function renderAssetCandidate(shotId: string, candidate: DpAssetCandidate) {
    const options = compatibleTargets(candidate);
    const selected = selectedTargets[candidate.id] ?? defaultTarget(candidate);
    const existingTargetMissing = candidate.linked_entity_id
      && !options.some((target) => target.id === candidate.linked_entity_id);
    const isBusy = busyShot === shotId;
    return (
      <div className="tj-grid dp-prep-row" key={candidate.id}>
        <div>
          <strong>{candidate.candidate_name}</strong>
          <div className="tj-hint">{candidate.candidate_type} · {candidateStatusLabel(candidate.candidate_status)}</div>
        </div>
        <label className="tj-field">
          <span className="tj-field__label">关联到已建资产</span>
          <select
            aria-label={`关联资产：${candidate.candidate_name}`}
            value={selected}
            onChange={(event) => setSelectedTargets((current) => ({
              ...current,
              [candidate.id]: event.target.value,
            }))}
            disabled={isBusy || candidate.candidate_status === 'ignored'}
          >
            <option value="">选择资产…</option>
            {existingTargetMissing && (
              <option value={candidate.linked_entity_id ?? ''}>{candidate.linked_entity_id}</option>
            )}
            {options.map((target) => (
              <option key={target.id} value={target.id}>{target.label}</option>
            ))}
          </select>
        </label>
        <div className="dp-chips">
          <button type="button" className="tj-btn" disabled={isBusy || !selected || candidate.candidate_status === 'ignored'}
            onClick={() => confirmAsset(shotId, candidate)}>确认关联</button>
          <button type="button" className="tj-btn tj-btn--secondary" disabled={isBusy || candidate.candidate_status === 'ignored'}
            onClick={() => ignoreAsset(shotId, candidate)}>忽略</button>
        </div>
      </div>
    );
  }

  function renderDialogueCandidate(shotId: string, candidate: DpDialogueCandidate) {
    const isBusy = busyShot === shotId;
    return (
      <div className="dp-prep-dialogue" key={candidate.id}>
        <div className="tj-hint">
          第 {candidate.line_index + 1} 句 · {candidate.speaker_name || '旁白'}
          {candidate.target_name ? ` → ${candidate.target_name}` : ''}
          {' · '}{candidateStatusLabel(candidate.candidate_status)}
        </div>
        <p>{candidate.text}</p>
        <div className="dp-chips">
          <button type="button" className="tj-btn" disabled={isBusy || candidate.candidate_status === 'ignored'}
            onClick={() => confirmDialogue(shotId, candidate)}>采纳对白</button>
          <button type="button" className="tj-btn tj-btn--secondary" disabled={isBusy || candidate.candidate_status === 'ignored'}
            onClick={() => ignoreDialogue(shotId, candidate)}>忽略</button>
        </div>
      </div>
    );
  }

  return (
    <section className="dp-card dp-shot-preparation" aria-label="逐镜头准备台">
      <div className="dp-card__head">逐镜头准备台</div>
      <p className="tj-hint">
        每镜提取资产和对白候选，人工确认关联或忽略后才允许产集。跳过提取属于显式人工放行。
      </p>
      {loading && <p role="status">正在读取逐镜头准备状态…</p>}
      {error && <p role="alert" className="dp-prep-error">{error}</p>}
      {overview?.blockers && overview.blockers.length > 0 && (
        <div className="dp-prep-blockers" role="status">
          <strong>当前拦截项（{overview.blockers.length}）</strong>
          <ul>{overview.blockers.map((blocker, index) => <li key={`${blocker}-${index}`}>{blocker}</li>)}</ul>
        </div>
      )}
      <div className="dp-prep-shots">
        {shotList.shots.map((shot, index) => {
          const state = states[shot.shot_id];
          const summary = overview?.shots.find((item) => item.shot_id === shot.shot_id);
          const isBusy = busyShot === shot.shot_id;
          return (
            <article className="dp-prep-shot" key={shot.shot_id}>
              <div className="dp-card__head">
                分镜 {index + 1} · {shot.shot_id} · {shot.scene_name || `第 ${shot.scene_no} 场`}
                <span className="sd-chip">{state?.status ?? summary?.status ?? '状态未知'}</span>
              </div>
              <p className="tj-hint">
                {shot.shot_size} · {shot.duration_s}s · {shot.camera || '机位未填写'}
              </p>
              {!state ? (
                <p className="tj-hint">准备状态不可用；该分镜不会被视为已就绪。</p>
              ) : (
                <>
                  {!state.extracted && !state.skip_extraction && (
                    <button type="button" className="tj-btn" disabled={isBusy || loading}
                      onClick={() => void mutateShot(shot.shot_id, () => directorPipelineApi.extractShot(workId, shot.shot_id))}>
                      提取本镜候选
                    </button>
                  )}
                  {state.extracted && (
                    <>
                      <div className="sd-review__label">资产候选（{state.assets_overview.length}）</div>
                      {state.assets_overview.length === 0
                        ? <p className="tj-hint">没有资产候选。</p>
                        : state.assets_overview.map((candidate) => renderAssetCandidate(shot.shot_id, candidate))}
                      <div className="sd-review__label">对白候选（{state.dialogue_candidates.length}）</div>
                      {state.dialogue_candidates.length === 0
                        ? <p className="tj-hint">没有对白候选。</p>
                        : state.dialogue_candidates.map((candidate) => renderDialogueCandidate(shot.shot_id, candidate))}
                    </>
                  )}
                  <div className="dp-chips">
                    <button type="button" className="tj-btn tj-btn--secondary" disabled={isBusy || loading}
                      onClick={() => void mutateShot(shot.shot_id, () =>
                        directorPipelineApi.setReadiness(workId, shot.shot_id, !state.skip_extraction),
                      )}>
                      {state.skip_extraction ? '恢复逐镜头确认' : '跳过提取并人工放行'}
                    </button>
                    <span className="tj-hint">
                      {state.ready_for_generation
                        ? '已满足本镜准备门禁'
                        : `待确认 ${state.pending_confirm_count} 项`}
                    </span>
                  </div>
                </>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
