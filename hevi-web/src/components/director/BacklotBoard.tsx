/**
 * BacklotBoard — 对标 OpenMontage Backlot 的实时制片看板。
 *
 * 从后端 /production/backlot/{task_id} 拉取数据,展示:
 *   - 阶段进度灯(stage rail):7 阶段亮灯/灰灯/闪烁
 *   - 场景卡片(scene cards):每个镜头的状态、provider、时长、视频预览
 *   - 成本仪表(cost meter):预估/实际/剩余预算
 *   - 决策日志(decision log):关键决策记录
 *
 * 与现有 DirectorPipelineConsole 的进度条平行,提供更深的可观测性。
 */
'use client';

import { useEffect, useState, useCallback } from 'react';

interface StageRailItem {
  stage: string;
  state: 'pending' | 'active' | 'completed' | 'failed';
}

interface SceneCard {
  shot_id: string;
  index: number;
  status: string;
  provider: string;
  duration_s: number;
  video_path: string;
}

interface CostMeter {
  estimated_usd: number;
  actual_usd: number;
  budget_usd: number;
  remaining_usd: number;
}

interface BacklotData {
  task_id: string;
  title: string;
  status: string;
  stage_rail: StageRailItem[];
  scene_cards: SceneCard[];
  cost_meter: CostMeter;
  created_at: string;
}

const STAGE_LABELS: Record<string, string> = {
  research: '①研究',
  proposal: '②方案',
  script: '③剧本',
  scene_plan: '④分镜',
  assets: '⑤资产',
  edit: '⑥剪辑',
  compose: '⑦合成',
};

function StageRail({ items }: { items: StageRailItem[] }) {
  return (
    <div className="bl-stage-rail">
      {items.map((item) => (
        <div
          key={item.stage}
          className={`bl-stage bl-stage--${item.state}`}
          title={STAGE_LABELS[item.stage] || item.stage}
        >
          <span className="bl-stage__dot" />
          <span className="bl-stage__label">
            {STAGE_LABELS[item.stage] || item.stage}
          </span>
        </div>
      ))}
    </div>
  );
}

function SceneCardGrid({ cards }: { cards: SceneCard[] }) {
  if (cards.length === 0) return <p className="bl-empty">暂无场景数据</p>;

  return (
    <div className="bl-scene-grid">
      {cards.map((card) => (
        <div key={card.shot_id} className={`bl-scene-card bl-scene--${card.status}`}>
          <div className="bl-scene-card__head">
            <span className="bl-scene-card__idx">#{card.index + 1}</span>
            <span className="bl-scene-card__status">{card.status}</span>
          </div>
          {card.video_path && (
            <video
              className="bl-scene-card__preview"
              src={card.video_path}
              controls
              preload="metadata"
            />
          )}
          <div className="bl-scene-card__meta">
            {card.provider && <span className="bl-chip">{card.provider}</span>}
            {card.duration_s > 0 && (
              <span className="bl-chip">{card.duration_s.toFixed(1)}s</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function CostMeter({ meter }: { meter: CostMeter }) {
  const pct = meter.budget_usd > 0
    ? Math.min(100, (meter.actual_usd / meter.budget_usd) * 100)
    : 0;
  const isOver = meter.actual_usd > meter.budget_usd;

  return (
    <div className="bl-cost-meter">
      <div className="bl-cost-meter__bar">
        <div
          className={`bl-cost-meter__fill ${isOver ? 'bl-cost-meter__fill--over' : ''}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="bl-cost-meter__numbers">
        <span>实际: <b>${meter.actual_usd.toFixed(2)}</b></span>
        <span>预算: ${meter.budget_usd.toFixed(2)}</span>
        <span className={isOver ? 'bl-cost-meter__warn' : ''}>
          剩余: ${meter.remaining_usd.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

interface BacklotBoardProps {
  taskId: string;
  pollIntervalMs?: number;
}

export function BacklotBoard({ taskId, pollIntervalMs = 5000 }: BacklotBoardProps) {
  const [data, setData] = useState<BacklotData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const resp = await fetch(`/api/production/backlot/${taskId}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const json = await resp.json();
      setData(json);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch');
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, pollIntervalMs);
    return () => clearInterval(timer);
  }, [fetchData, pollIntervalMs]);

  if (loading && !data) {
    return <div className="bl-loading">加载中…</div>;
  }

  if (error && !data) {
    return <div className="bl-error">加载失败: {error}</div>;
  }

  if (!data) return null;

  return (
    <div className="bl-board">
      <div className="bl-board__header">
        <h2 className="bl-board__title">{data.title}</h2>
        <span className={`bl-board__status bl-status--${data.status}`}>
          {data.status}
        </span>
      </div>

      <section className="bl-section">
        <h3 className="bl-section__title">阶段进度</h3>
        <StageRail items={data.stage_rail} />
      </section>

      <section className="bl-section">
        <h3 className="bl-section__title">场景胶片</h3>
        <SceneCardGrid cards={data.scene_cards} />
      </section>

      <section className="bl-section">
        <h3 className="bl-section__title">成本仪表</h3>
        <CostMeter meter={data.cost_meter} />
      </section>
    </div>
  );
}
