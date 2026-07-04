/**
 * CharacterEditor — 角色卡编辑面板(§ 角色配置规格,Phase 1-3)
 * 折叠态:头像+名字+戏份分级。展开态:姓名/描述/标签、参考图管理(批量传/设封面/删除)、
 * 人设字段(年龄/性别/体型/人设/语言风格/关系/专属负向)、声音参考、造型参考图。
 */
'use client';

import { useState } from 'react';
import { subjectApi } from '@/lib/api-client';
import type { Subject, CastingTier } from '@/types/api';

const CASTING_TIERS: { v: CastingTier | ''; l: string }[] = [
  { v: '', l: '未分级' }, { v: 'protagonist', l: '主角' },
  { v: 'supporting', l: '配角' }, { v: 'extra', l: '龙套' },
];

function errText(e: unknown): string {
  return e instanceof Error ? e.message : '操作失败,请重试';
}

export function CharacterEditor({
  subject, onUpdated, onDeleted,
}: {
  subject: Subject;
  onUpdated: (s: Subject) => void;
  onDeleted: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [name, setName] = useState(subject.name);
  const [description, setDescription] = useState(subject.description ?? '');
  const [tagsText, setTagsText] = useState((subject.tags ?? []).join(', '));
  const meta = subject.metadata ?? {};
  const [age, setAge] = useState(meta.age ?? '');
  const [gender, setGender] = useState(meta.gender ?? '');
  const [build, setBuild] = useState(meta.build ?? '');
  const [castingTier, setCastingTier] = useState<CastingTier | ''>(meta.casting_tier ?? '');
  const [persona, setPersona] = useState(meta.persona ?? '');
  const [speechStyle, setSpeechStyle] = useState(meta.speech_style ?? '');
  const [relationships, setRelationships] = useState(meta.relationships ?? '');
  const [negativeNotes, setNegativeNotes] = useState(meta.negative_notes ?? '');

  function resetDraft(s: Subject) {
    setName(s.name); setDescription(s.description ?? ''); setTagsText((s.tags ?? []).join(', '));
    const m = s.metadata ?? {};
    setAge(m.age ?? ''); setGender(m.gender ?? ''); setBuild(m.build ?? '');
    setCastingTier(m.casting_tier ?? ''); setPersona(m.persona ?? '');
    setSpeechStyle(m.speech_style ?? ''); setRelationships(m.relationships ?? '');
    setNegativeNotes(m.negative_notes ?? '');
  }

  async function saveFields(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const updated = await subjectApi.update(subject.subject_id, {
        name, description,
        tags: tagsText.split(',').map(t => t.trim()).filter(Boolean),
        metadata: {
          age, gender, build, persona, speech_style: speechStyle,
          relationships, negative_notes: negativeNotes,
          casting_tier: castingTier || undefined,
        },
      });
      onUpdated(updated); resetDraft(updated);
    } catch (e2) { setErr(errText(e2)); } finally { setBusy(false); }
  }

  async function onBatchUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    e.target.value = '';
    if (!files.length) return;
    setBusy(true); setErr(null);
    try { onUpdated(await subjectApi.uploadReferences(subject.subject_id, files)); }
    catch (e2) { setErr(errText(e2)); } finally { setBusy(false); }
  }

  async function setCover(idx: number) {
    const refs = subject.reference_images ?? [];
    if (idx === 0 || idx >= refs.length) return;
    const reordered = [refs[idx], ...refs.filter((_, i) => i !== idx)];
    setBusy(true); setErr(null);
    try { onUpdated(await subjectApi.reorderReferences(subject.subject_id, reordered)); }
    catch (e2) { setErr(errText(e2)); } finally { setBusy(false); }
  }

  async function deleteReference(idx: number) {
    const refs = (subject.reference_images ?? []).filter((_, i) => i !== idx);
    setBusy(true); setErr(null);
    try { onUpdated(await subjectApi.reorderReferences(subject.subject_id, refs)); }
    catch (e2) { setErr(errText(e2)); } finally { setBusy(false); }
  }

  async function onVoiceUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setBusy(true); setErr(null);
    try { onUpdated(await subjectApi.uploadVoice(subject.subject_id, file)); }
    catch (e2) { setErr(errText(e2)); } finally { setBusy(false); }
  }

  async function onWardrobeUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setBusy(true); setErr(null);
    try { onUpdated(await subjectApi.uploadWardrobe(subject.subject_id, file)); }
    catch (e2) { setErr(errText(e2)); } finally { setBusy(false); }
  }

  async function onDelete() {
    if (!confirm(`删除角色「${subject.name}」?此操作不可撤销。`)) return;
    setBusy(true); setErr(null);
    try { await subjectApi.remove(subject.subject_id); onDeleted(); }
    catch (e2) { setErr(errText(e2)); setBusy(false); }
  }

  const refs = subject.reference_images ?? [];
  const wardrobe = meta.wardrobe_images ?? [];

  return (
    <div className="hevi-char" data-expanded={expanded ? 'true' : undefined}>
      <button type="button" className="hevi-char__head" onClick={() => { setExpanded(v => !v); resetDraft(subject); }}>
        {refs.length > 0 ? (
          <img src={subjectApi.imageUrl(subject.subject_id)} alt={subject.name} className="hevi-char__avatar" />
        ) : (
          <div className="hevi-char__avatar hevi-char__avatar--placeholder">{subject.name[0]}</div>
        )}
        <span className="hevi-char__name">{subject.name}</span>
        {meta.casting_tier && (
          <span className="hevi-char__tier" data-tier={meta.casting_tier}>
            {CASTING_TIERS.find(t => t.v === meta.casting_tier)?.l}
          </span>
        )}
        <span className="hevi-char__chevron">{expanded ? '收起 ▲' : '编辑 ▼'}</span>
      </button>

      {expanded && (
        <form className="hevi-char__body" onSubmit={saveFields}>
          {err && <div className="hevi-char__err">{err}</div>}

          <div className="hevi-char__section">
            <div className="hevi-char__section-head">身份基础</div>
            <div className="hevi-char__grid">
              <label className="hevi-char__field hevi-char__field--wide">
                <span>姓名</span>
                <input value={name} onChange={e => setName(e.target.value)} required />
              </label>
              <label className="hevi-char__field">
                <span>年龄段</span>
                <input placeholder="如 20多岁" value={age} onChange={e => setAge(e.target.value)} />
              </label>
              <label className="hevi-char__field">
                <span>性别</span>
                <input value={gender} onChange={e => setGender(e.target.value)} />
              </label>
              <label className="hevi-char__field">
                <span>体型</span>
                <input value={build} onChange={e => setBuild(e.target.value)} />
              </label>
              <label className="hevi-char__field">
                <span>戏份分级</span>
                <select value={castingTier} onChange={e => setCastingTier(e.target.value as CastingTier | '')}>
                  {CASTING_TIERS.map(t => <option key={t.v} value={t.v}>{t.l}</option>)}
                </select>
              </label>
              <label className="hevi-char__field hevi-char__field--wide">
                <span>描述</span>
                <input value={description} onChange={e => setDescription(e.target.value)} />
              </label>
              <label className="hevi-char__field hevi-char__field--wide">
                <span>标签(逗号分隔)</span>
                <input value={tagsText} onChange={e => setTagsText(e.target.value)} />
              </label>
            </div>
          </div>

          <div className="hevi-char__section">
            <div className="hevi-char__section-head">人设 · 声音 · 关系</div>
            <div className="hevi-char__grid">
              <label className="hevi-char__field hevi-char__field--wide">
                <span>人设 / 性格(注入分镜写作)</span>
                <input placeholder="如:毒舌但重情义" value={persona} onChange={e => setPersona(e.target.value)} />
              </label>
              <label className="hevi-char__field">
                <span>语言风格 / 口头禅</span>
                <input value={speechStyle} onChange={e => setSpeechStyle(e.target.value)} />
              </label>
              <label className="hevi-char__field">
                <span>人物关系</span>
                <input placeholder="如:与阿熊是竞争对手" value={relationships} onChange={e => setRelationships(e.target.value)} />
              </label>
              <label className="hevi-char__field hevi-char__field--wide">
                <span>专属负向提示</span>
                <input placeholder="如:避免多指" value={negativeNotes} onChange={e => setNegativeNotes(e.target.value)} />
              </label>
            </div>
            <div className="hevi-char__voice-row">
              <span className="hevi-char__voice-status">
                声音参考:{meta.voice_ref ? '已设置(VibeVoice 生效)' : '未设置'}
              </span>
              <label className="oui-btn hevi-char__upload-btn">
                {meta.voice_ref ? '替换声音片段' : '上传声音片段'}
                <input type="file" accept="audio/*" hidden disabled={busy} onChange={onVoiceUpload} />
              </label>
            </div>
          </div>

          <div className="hevi-char__section">
            <div className="hevi-char__section-head">参考图(身份锁定,第 1 张为封面)</div>
            <div className="hevi-char__refs">
              {refs.map((_, idx) => (
                <div key={idx} className="hevi-char__ref">
                  <img src={subjectApi.imageUrl(subject.subject_id, idx)} alt="" />
                  {idx === 0 && <span className="hevi-char__ref-cover">封面</span>}
                  <div className="hevi-char__ref-actions">
                    {idx !== 0 && (
                      <button type="button" disabled={busy} onClick={() => setCover(idx)}>设为封面</button>
                    )}
                    <button type="button" disabled={busy} onClick={() => deleteReference(idx)}>删除</button>
                  </div>
                </div>
              ))}
              <label className="hevi-char__ref hevi-char__ref--add">
                + 批量添加
                <input type="file" accept="image/*" multiple hidden disabled={busy} onChange={onBatchUpload} />
              </label>
            </div>
          </div>

          <div className="hevi-char__section">
            <div className="hevi-char__section-head">造型 / 服装参考图(与身份参考图分开管理)</div>
            <div className="hevi-char__refs">
              {wardrobe.map((_, idx) => (
                <div key={idx} className="hevi-char__ref hevi-char__ref--wardrobe">
                  <img src={subjectApi.imageUrl(subject.subject_id, idx, 'wardrobe')} alt="" />
                </div>
              ))}
              <label className="hevi-char__ref hevi-char__ref--add">
                + 添加造型图
                <input type="file" accept="image/*" hidden disabled={busy} onChange={onWardrobeUpload} />
              </label>
            </div>
          </div>

          <div className="hevi-char__footer">
            <button type="submit" className="oui-btn-primary" disabled={busy}>{busy ? '保存中…' : '保存'}</button>
            <button type="button" className="hevi-char__delete" disabled={busy} onClick={onDelete}>删除角色</button>
          </div>
        </form>
      )}
    </div>
  );
}
