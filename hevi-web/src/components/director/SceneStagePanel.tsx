'use client';

/**
 * SPEC-004 ③.5 场面调度人审面板(DP2)。
 *
 * Construction-First:AI 出完整 SceneStage 草案,人在这里"攻击"落位/注意力/机位后锁定,才放行④分镜。
 * 布局/样式复用导演台既有 .tj-* / .dp-card / .sd-* 类。俯视图从 zones 确定性派生(§7 单一真相源,
 * 不让 AI 自由画图)——纯前端 SVG,零依赖。
 */

import type {
  DpSceneStage, DpSceneStageSet, DpInitialPosition, DpAttentionBeat, DpSceneAxis,
} from '@/types/api';

const INTENSITY = ['exclusive', 'primary', 'shared'] as const;
const INTENSITY_ZH: Record<string, string> = {
  exclusive: '独占(虚化他人)', primary: '主焦点', shared: '群像',
};
const TRANSITION = ['cut', 'pan', 'push', 'rack_focus', 'follow'] as const;
const TRANSITION_ZH: Record<string, string> = {
  cut: '切', pan: '摇', push: '推', rack_focus: '变焦点', follow: '跟',
};

// rel_position 自由文本 → 3×3 俯视网格坐标(确定性派生俯视图)。命中 左/中/右 × 上/中/下。
function zoneCell(rel: string): { col: number; row: number } {
  const t = rel || '';
  const col = t.includes('左') ? 0 : t.includes('右') ? 2 : 1;
  const row = t.includes('上') ? 0 : t.includes('下') ? 2 : 1;
  return { col, row };
}

/** 俯视示意图:zones 作格子、initial_positions 作格内标点(从场事实确定性派生,不是 AI 画的)。 */
function TopDownSketch({ stage }: { stage: DpSceneStage }) {
  const W = 300, H = 210, cw = W / 3, ch = H / 3;
  const zoneById = Object.fromEntries(stage.space_map.zones.map(z => [z.zone_id, z]));
  // 每个 zone 落到一个格子;同格多 zone 纵向错开
  const perCell: Record<string, string[]> = {};
  stage.space_map.zones.forEach(z => {
    const { col, row } = zoneCell(z.rel_position);
    const key = `${col},${row}`;
    (perCell[key] ??= []).push(z.zone_id);
  });
  const charsByZone: Record<string, string[]> = {};
  stage.blocking.initial_positions.forEach(p => {
    if (p.zone_id) (charsByZone[p.zone_id] ??= []).push(p.char_id);
  });
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="dp-ss-sketch" role="img" aria-label="场景俯视示意图">
      {[1, 2].map(i => (
        <g key={i} stroke="var(--tj-border,#3334)" strokeDasharray="3 3">
          <line x1={i * cw} y1={0} x2={i * cw} y2={H} />
          <line x1={0} y1={i * ch} x2={W} y2={i * ch} />
        </g>
      ))}
      {Object.entries(perCell).flatMap(([key, zids]) => {
        const [col, row] = key.split(',').map(Number);
        return zids.map((zid, k) => {
          const z = zoneById[zid];
          const x = col * cw + 6, y = row * ch + 6 + k * 30;
          const chars = charsByZone[zid] || [];
          return (
            <g key={zid}>
              <rect x={x} y={y} width={cw - 12} height={26} rx={5}
                fill="var(--tj-accent-soft,#5b8def22)" stroke="var(--tj-accent,#5b8def)" />
              <text x={x + 6} y={y + 12} fontSize={9} fill="var(--tj-fg,#ccc)">{z?.name || zid}</text>
              <text x={x + 6} y={y + 22} fontSize={8} fill="var(--tj-accent,#5b8def)">
                {chars.join('、')}
              </text>
            </g>
          );
        });
      })}
    </svg>
  );
}

function StageCard({ stage, onChange }: {
  stage: DpSceneStage; onChange: (patch: Partial<DpSceneStage>) => void;
}) {
  const zoneOpts = stage.space_map.zones;
  function updatePos(i: number, patch: Partial<DpInitialPosition>) {
    onChange({
      blocking: {
        ...stage.blocking,
        initial_positions: stage.blocking.initial_positions.map((p, j) => (j === i ? { ...p, ...patch } : p)),
      },
    });
  }
  function updateAttn(i: number, patch: Partial<DpAttentionBeat>) {
    onChange({ attention_script: stage.attention_script.map((a, j) => (j === i ? { ...a, ...patch } : a)) });
  }
  function updateAxis(patch: Partial<DpSceneAxis>) {
    onChange({ axis: { ...stage.axis, ...patch } });
  }
  const beatLabel = (bid: string) => {
    const b = stage.beats.find(x => x.beat_id === bid);
    return b ? `${b.beat_id}｜${b.dialogue_ref || b.trigger || ''}` : bid;
  };
  return (
    <div className="dp-card">
      <div className="dp-card__head">
        第{stage.scene_ref}场 场面调度{stage.assumed && <span className="sd-chip" title="含 AI 假设,请审核"> ⚠ AI 草案</span>}
      </div>

      <TopDownSketch stage={stage} />

      <div className="sd-review__label">落位与朝向(核心:攻击这里)</div>
      {stage.blocking.initial_positions.map((p, i) => (
        <div key={i} className="tj-grid dp-ss-row">
          <span className="sd-chip">{p.char_id}</span>
          <label className="tj-field"><span className="tj-field__label">位置区域</span>
            <select value={p.zone_id} onChange={e => updatePos(i, { zone_id: e.target.value })}>
              <option value="">(未定)</option>
              {zoneOpts.map(z => <option key={z.zone_id} value={z.zone_id}>{z.name || z.zone_id}</option>)}
            </select></label>
          <label className="tj-field"><span className="tj-field__label">朝向</span>
            <input value={p.facing} onChange={e => updatePos(i, { facing: e.target.value })} /></label>
          <label className="tj-field"><span className="tj-field__label">姿态</span>
            <input value={p.posture} onChange={e => updatePos(i, { posture: e.target.value })} /></label>
        </div>
      ))}

      <div className="sd-review__label">轴线(180°基准)</div>
      <div className="dp-chips">
        {stage.axis.primary_axis.map(n => <span key={n} className="sd-chip">{n}</span>)}
        <span className="tj-hint">主轴</span>
      </div>
      <label className="tj-field"><span className="tj-field__label">画面正方向约定</span>
        <input value={stage.axis.side_convention} placeholder="如:甲恒在画左,乙恒在画右"
          onChange={e => updateAxis({ side_convention: e.target.value })} /></label>

      <div className="sd-review__label">注意力脚本(该看谁:攻击这里)</div>
      {stage.attention_script.map((a, i) => (
        <div key={i} className="tj-grid dp-ss-row">
          <span className="sd-chip" title="节拍">{beatLabel(a.at_beat)}</span>
          <label className="tj-field"><span className="tj-field__label">焦点</span>
            <input value={a.focus_target} onChange={e => updateAttn(i, { focus_target: e.target.value })} /></label>
          <label className="tj-field"><span className="tj-field__label">强度</span>
            <select value={a.intensity} onChange={e => updateAttn(i, { intensity: e.target.value })}>
              {INTENSITY.map(v => <option key={v} value={v}>{INTENSITY_ZH[v]}</option>)}
            </select></label>
          <label className="tj-field"><span className="tj-field__label">转场</span>
            <select value={a.transition} onChange={e => updateAttn(i, { transition: e.target.value })}>
              {TRANSITION.map(v => <option key={v} value={v}>{TRANSITION_ZH[v]}</option>)}
            </select></label>
          {a.reason && <span className="tj-hint" title="原因">{a.reason}</span>}
        </div>
      ))}

      {stage.coverage_plan.setups.length > 0 && (
        <>
          <div className="sd-review__label">机位方案(coverage)</div>
          <div className="dp-chips">
            {stage.coverage_plan.master && (
              <span className="sd-chip" title="master 宽景">🎥 {stage.coverage_plan.master.setup_id}</span>
            )}
            {stage.coverage_plan.setups.map(s => (
              <span key={s.setup_id} className="sd-chip"
                title={`轴侧 ${s.axis_side} · 拍 ${s.subjects.join('、')} · 服务 ${s.serves_beats.join(',')}`}>
                {s.setup_id}｜{s.shot_size}｜{s.axis_side}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export default function SceneStagePanel({ draft, onChange, onRegenerate, onLock, busy }: {
  draft: DpSceneStageSet;
  onChange: (d: DpSceneStageSet) => void;
  onRegenerate: () => void;
  onLock: () => void;
  busy: boolean;
}) {
  function updateStage(i: number, patch: Partial<DpSceneStage>) {
    onChange({ stages: draft.stages.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  }
  return (
    <div className="tj-progress">
      <p className="tj-hint">
        每场先"立起来"(落位/轴线/注意力/机位),该场所有镜头从同一场事实切视角——镜头间天然一致,
        不再各自想象空间。AI 已出草案,请攻击修正后锁定。
      </p>
      {draft.stages.map((stage, i) => (
        <StageCard key={stage.scene_ref} stage={stage} onChange={patch => updateStage(i, patch)} />
      ))}
      <div className="tj-actions">
        <button type="button" className="tj-btn" onClick={onRegenerate} disabled={busy}>↻ 重新生成</button>
        <button type="button" className="tj-btn tj-btn--primary" onClick={onLock} disabled={busy}>
          {busy ? '锁定中…' : '锁定场面调度,生成④分镜草稿'}
        </button>
      </div>
    </div>
  );
}
