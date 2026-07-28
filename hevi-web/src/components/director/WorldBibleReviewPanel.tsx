/**
 * WorldBibleReviewPanel — V1→V2 原地升级(2026-07-21)④World Bible 人审页。
 * 四卷:角色卷/世界卷是卡片数组(抄 DirectorPipelineConsole::DesignListStep 的
 * `updateX(i, patch)` 范式),影像卷/声音卷是单卡片多字段编辑(抄 ConceptStep 的
 * `set(k, v)` 范式)。不照抄 SceneStagePanel 的 SVG 平面图逻辑——四卷都是长文本+
 * 结构化小字段,纯表单卡片够用。
 */
'use client';

import type {
  DpWorldBible, DpCharacterVolumeEntry, DpWorldVolumeEntry, DpVisualVolume, DpSoundVolume,
} from '@/types/api';

// string[] 字段(assumed_details/negative_list/photographic_flaw_aesthetics)统一用
// 一行一条的 textarea 编辑,split/join 换行,跟本文件其余 input 编辑范式一致的最简形式。
function linesToArr(text: string): string[] {
  return text.split('\n');
}

function StringListField({ label, value, onChange }: {
  label: string; value: string[]; onChange: (v: string[]) => void;
}) {
  return (
    <label className="tj-field tj-field--tall">
      <span className="tj-field__label">{label}（每行一条）</span>
      <textarea rows={3} value={value.join('\n')} onChange={e => onChange(linesToArr(e.target.value))} />
    </label>
  );
}

export default function WorldBibleReviewPanel({ draft, visualStyle, onChange, onRegenerate, onLock, busy }: {
  draft: DpWorldBible; visualStyle: 'realistic' | 'inkwash';
  onChange: (w: DpWorldBible) => void;
  // 不带参 = 用当前画风重新生成;带参 = 切换到该画风并重新生成。
  onRegenerate: (visualStyle?: 'realistic' | 'inkwash') => void;
  onLock: () => void; busy: boolean;
}) {
  function updateChar(i: number, patch: Partial<DpCharacterVolumeEntry>) {
    onChange({ ...draft, characters: draft.characters.map((c, j) => (j === i ? { ...c, ...patch } : c)) });
  }
  function updateWorld(i: number, patch: Partial<DpWorldVolumeEntry>) {
    onChange({ ...draft, world: draft.world.map((w, j) => (j === i ? { ...w, ...patch } : w)) });
  }
  function setVisual<K extends keyof DpVisualVolume>(k: K, v: DpVisualVolume[K]) {
    onChange({ ...draft, visual: { ...draft.visual, [k]: v } });
  }
  function setCameraPersona<K extends keyof DpVisualVolume['camera_persona']>(
    k: K, v: DpVisualVolume['camera_persona'][K],
  ) {
    setVisual('camera_persona', { ...draft.visual.camera_persona, [k]: v });
  }
  function setSound<K extends keyof DpSoundVolume>(k: K, v: DpSoundVolume[K]) {
    onChange({ ...draft, sound: { ...draft.sound, [k]: v } });
  }

  return (
    <div className="tj-progress">
      <div className="sd-review__label">角色卷（{draft.characters.length}）</div>
      {draft.characters.map((c, i) => (
        <div key={i} className="dp-card">
          <div className="dp-card__head">{c.name}</div>
          <label className="tj-field tj-field--tall"><span className="tj-field__label">人物侧写</span>
            <textarea rows={3} value={c.profile_text}
              onChange={e => updateChar(i, { profile_text: e.target.value })} /></label>
          <label className="tj-field"><span className="tj-field__label">身份锁定句</span>
            <input value={c.identity_lock_sentence}
              onChange={e => updateChar(i, { identity_lock_sentence: e.target.value })} /></label>
          <StringListField label="推定细节" value={c.assumed_details}
            onChange={v => updateChar(i, { assumed_details: v })} />
        </div>
      ))}

      <div className="sd-review__label">世界卷（{draft.world.length}）</div>
      {draft.world.map((w, i) => (
        <div key={i} className="dp-card">
          <div className="dp-card__head">{w.name}</div>
          <label className="tj-field tj-field--tall"><span className="tj-field__label">场景侧写</span>
            <textarea rows={3} value={w.profile_text}
              onChange={e => updateWorld(i, { profile_text: e.target.value })} /></label>
          <StringListField label="负面约束" value={w.negative_list}
            onChange={v => updateWorld(i, { negative_list: v })} />
          <StringListField label="推定细节" value={w.assumed_details}
            onChange={v => updateWorld(i, { assumed_details: v })} />
        </div>
      ))}

      <div className="sd-review__label">影像卷</div>
      <div className="dp-card">
        <label className="tj-field tj-field--tall"><span className="tj-field__label">风格宣言</span>
          <textarea rows={3} value={draft.visual.style_manifesto}
            onChange={e => setVisual('style_manifesto', e.target.value)} /></label>
        <div className="tj-grid">
          <label className="tj-field"><span className="tj-field__label">运镜人格</span>
            <input value={draft.visual.camera_persona.persona_id}
              onChange={e => setCameraPersona('persona_id', e.target.value)} /></label>
        </div>
        <label className="tj-field tj-field--tall"><span className="tj-field__label">运镜人格理由</span>
          <textarea rows={2} value={draft.visual.camera_persona.persona_rationale}
            onChange={e => setCameraPersona('persona_rationale', e.target.value)} /></label>
        <label className="tj-field tj-field--tall"><span className="tj-field__label">行为推导</span>
          <textarea rows={2} value={draft.visual.camera_persona.behavior_derivation_text}
            onChange={e => setCameraPersona('behavior_derivation_text', e.target.value)} /></label>
        <StringListField label="摄影瑕疵美学" value={draft.visual.photographic_flaw_aesthetics}
          onChange={v => setVisual('photographic_flaw_aesthetics', v)} />
        <StringListField label="负面约束" value={draft.visual.negative_list}
          onChange={v => setVisual('negative_list', v)} />
        <StringListField label="推定细节" value={draft.visual.assumed_details}
          onChange={v => setVisual('assumed_details', v)} />
      </div>

      <div className="sd-review__label">声音卷</div>
      <div className="dp-card">
        <label className="tj-field tj-field--tall"><span className="tj-field__label">环境声景</span>
          <textarea rows={2} value={draft.sound.ambient_soundscape_text}
            onChange={e => setSound('ambient_soundscape_text', e.target.value)} /></label>
        <label className="tj-field tj-field--tall"><span className="tj-field__label">音乐立场</span>
          <textarea rows={2} value={draft.sound.music_stance_text}
            onChange={e => setSound('music_stance_text', e.target.value)} /></label>
        <StringListField label="负面约束" value={draft.sound.negative_list}
          onChange={v => setSound('negative_list', v)} />
        <StringListField label="推定细节" value={draft.sound.assumed_details}
          onChange={v => setSound('assumed_details', v)} />
      </div>

      <div className="dp-visual-style">
        <span className="tj-field__label">画风预设</span>
        <div className="tj-seg">
          <button type="button"
            className={`tj-btn${visualStyle === 'realistic' ? ' tj-btn--primary' : ''}`}
            onClick={() => visualStyle !== 'realistic' && onRegenerate('realistic')} disabled={busy}>
            真人写实
          </button>
          <button type="button"
            className={`tj-btn${visualStyle === 'inkwash' ? ' tj-btn--primary' : ''}`}
            onClick={() => visualStyle !== 'inkwash' && onRegenerate('inkwash')} disabled={busy}>
            国风水墨
          </button>
        </div>
        <span className="dp-visual-style__hint">切换画风会按新预设重新生成四卷</span>
      </div>

      <div className="tj-actions">
        <button type="button" className="tj-btn" onClick={() => onRegenerate()} disabled={busy}>↻ 重新生成</button>
        <button type="button" className="tj-btn tj-btn--primary" onClick={onLock} disabled={busy}>
          {busy ? '处理中…' : '锁定 World Bible，生成⑤Scene Script 草稿'}
        </button>
      </div>
    </div>
  );
}
