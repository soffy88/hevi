/**
 * SceneScriptReviewPanel — V1→V2 原地升级(2026-07-21)⑤Scene Script 人审页。
 * 按场景(scene_ref)分组的时间轴卡片列表,每场一组,每段(segment)一张子卡片,
 * editable 同 DirectorPipelineConsole 既有的 `updateX(i, patch)` 闭包范式。
 */
'use client';

import type { DpSceneScriptSet, DpSceneScript, DpSceneScriptSegment } from '@/types/api';

function linesToArr(text: string): string[] {
  return text.split('\n');
}

export default function SceneScriptReviewPanel({ draft, onChange, onRegenerate, onLock, busy }: {
  draft: DpSceneScriptSet; onChange: (s: DpSceneScriptSet) => void;
  onRegenerate: () => void; onLock: () => void; busy: boolean;
}) {
  function updateScene(sceneIdx: number, patch: Partial<DpSceneScript>) {
    onChange({ scripts: draft.scripts.map((s, j) => (j === sceneIdx ? { ...s, ...patch } : s)) });
  }
  function updateSegment(sceneIdx: number, segIdx: number, patch: Partial<DpSceneScriptSegment>) {
    const scene = draft.scripts[sceneIdx];
    const segments = scene.segments.map((sg, j) => (j === segIdx ? { ...sg, ...patch } : sg));
    updateScene(sceneIdx, { segments });
  }
  function updateDialogueLine(
    sceneIdx: number, segIdx: number, lineIdx: number, field: 'character_name' | 'text' | 'target_name', value: string,
  ) {
    const segment = draft.scripts[sceneIdx].segments[segIdx];
    const dialogue = segment.dialogue.map((d, j) => (j === lineIdx ? { ...d, [field]: value } : d));
    updateSegment(sceneIdx, segIdx, { dialogue });
  }

  return (
    <div className="tj-progress">
      {draft.scripts.map((scene, sceneIdx) => (
        <div key={sceneIdx} className="dp-card">
          <div className="dp-card__head">
            第{scene.scene_ref}场 · {scene.characters_present.join('、') || '（无出场角色）'} ·
            共 {scene.total_duration_s.toFixed(1)}s
          </div>
          <label className="tj-field tj-field--tall">
            <span className="tj-field__label">不可切至（no_cut_to，每行一条）</span>
            <textarea rows={2} value={scene.no_cut_to.join('\n')}
              onChange={e => updateScene(sceneIdx, { no_cut_to: linesToArr(e.target.value) })} />
          </label>

          {scene.segments.map((seg, segIdx) => (
            <div key={seg.segment_id} className="dp-card dp-card--nested">
              <div className="dp-card__head">
                {seg.segment_id}（第{seg.order}段，{seg.t_start_s.toFixed(1)}s–{seg.t_end_s.toFixed(1)}s）
              </div>
              <label className="tj-field tj-field--tall"><span className="tj-field__label">叙述</span>
                <textarea rows={2} value={seg.narrative_text}
                  onChange={e => updateSegment(sceneIdx, segIdx, { narrative_text: e.target.value })} /></label>
              <div className="tj-grid">
                <label className="tj-field"><span className="tj-field__label">运镜标签</span>
                  <input value={seg.camera_movement}
                    onChange={e => updateSegment(sceneIdx, segIdx, { camera_movement: e.target.value })} /></label>
                <label className="tj-field"><span className="tj-field__label">画外触发</span>
                  <input value={seg.offscreen_trigger}
                    onChange={e => updateSegment(sceneIdx, segIdx, { offscreen_trigger: e.target.value })} /></label>
              </div>
              <label className="tj-field tj-field--tall"><span className="tj-field__label">节拍描述</span>
                <textarea rows={2} value={seg.beat_description}
                  onChange={e => updateSegment(sceneIdx, segIdx, { beat_description: e.target.value })} /></label>
              <div className="tj-grid">
                <label className="tj-field"><span className="tj-field__label">承接自上段</span>
                  <input value={seg.handoff_in}
                    onChange={e => updateSegment(sceneIdx, segIdx, { handoff_in: e.target.value })} /></label>
                <label className="tj-field"><span className="tj-field__label">交给下段</span>
                  <input value={seg.handoff_out}
                    onChange={e => updateSegment(sceneIdx, segIdx, { handoff_out: e.target.value })} /></label>
              </div>
              <div className="tj-field__label">台词（说话人留空 = 旁白）</div>
              {seg.dialogue.map((d, lineIdx) => (
                <div key={lineIdx} className="dp-dialogue-row">
                  <input className="dp-dialogue-row__speaker" placeholder="说话人" value={d.character_name}
                    onChange={e => updateDialogueLine(sceneIdx, segIdx, lineIdx, 'character_name', e.target.value)} />
                  <input className="dp-dialogue-row__text" placeholder="台词" value={d.text}
                    onChange={e => updateDialogueLine(sceneIdx, segIdx, lineIdx, 'text', e.target.value)} />
                  <input className="dp-dialogue-row__speaker" placeholder="对谁说（eyeline）" value={d.target_name}
                    onChange={e => updateDialogueLine(sceneIdx, segIdx, lineIdx, 'target_name', e.target.value)} />
                </div>
              ))}
            </div>
          ))}
        </div>
      ))}
      <div className="tj-actions">
        <button type="button" className="tj-btn" onClick={onRegenerate} disabled={busy}>↻ 重新生成</button>
        <button type="button" className="tj-btn tj-btn--primary" onClick={onLock} disabled={busy}>
          {busy ? '处理中…' : '锁定 Scene Script'}
        </button>
      </div>
    </div>
  );
}
