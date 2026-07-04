/**
 * AccountCenter — 用户中心(2.3)
 * 我的视频 / 我的画布 / 我的主体库 / 账户设置
 */
'use client';

import { useState, useEffect } from 'react';
import { OTaskProgress } from '@helios/oui';
import { MOCK_TASKS, MOCK_CANVASES, MOCK_SUBJECTS } from '@/lib/mock-data';
import { taskApi, canvasApi, subjectApi, creditsApi, USE_MOCK } from '@/lib/api-client';
import type { TaskInfo, CanvasGraph, Subject, SubjectKind } from '@/types/api';
import { CharacterEditor } from './CharacterEditor';

const KIND_OPTIONS: { v: SubjectKind; l: string }[] = [
  { v: 'character', l: '角色' }, { v: 'portrait', l: '人像' },
  { v: 'product', l: '产品' }, { v: 'scene', l: '场景' },
];

type Tab = 'videos' | 'canvases' | 'subjects' | 'settings';

const STATUS_TEXT: Record<string, string> = {
  completed: '已完成', running: '生成中', failed: '失败', pending: '排队中', paused: '已暂停',
};

export function AccountCenter() {
  const [tab, setTab] = useState<Tab>('videos');

  // USE_MOCK=false 时调真 API(租户隔离,只返回当前用户的)
  const [tasks, setTasks] = useState<TaskInfo[]>(USE_MOCK ? MOCK_TASKS : []);
  const [canvases, setCanvases] = useState<CanvasGraph[]>(USE_MOCK ? MOCK_CANVASES : []);
  const [subjects, setSubjects] = useState<Subject[]>(USE_MOCK ? MOCK_SUBJECTS : []);
  const [balance, setBalance] = useState<number>(USE_MOCK ? 3500 : 0);

  // 主体库:建角色表单态
  const [subjectBusy, setSubjectBusy] = useState(false);
  const [subjectError, setSubjectError] = useState<string | null>(null);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newName, setNewName] = useState('');
  const [newKind, setNewKind] = useState<SubjectKind>('character');
  const [newDescription, setNewDescription] = useState('');
  const [newPhoto, setNewPhoto] = useState<File | null>(null);

  const refreshSubjects = () => subjectApi.list().then(setSubjects).catch(() => {});

  // 真建角色表单(姓名/kind/描述/可选首照)—— 替代此前"上传照片"硬编码"我的角色"、
  // 描述永远空白的一键流程。
  const onCreateSubject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) { setSubjectError('请填角色姓名'); return; }
    setSubjectError(null);
    setSubjectBusy(true);
    try {
      const created = await subjectApi.create({ kind: newKind, name: newName.trim(), description: newDescription });
      if (newPhoto) await subjectApi.uploadReference(created.subject_id, newPhoto);
      setNewName(''); setNewDescription(''); setNewPhoto(null); setShowCreateForm(false);
      await refreshSubjects();
    } catch { setSubjectError('创建失败,请重试'); }
    finally { setSubjectBusy(false); }
  };

  useEffect(() => {
    if (USE_MOCK) return;
    taskApi.list?.().then(setTasks).catch(() => setTasks([]));
    canvasApi.list().then(setCanvases).catch(() => setCanvases([]));
    subjectApi.list().then(setSubjects).catch(() => setSubjects([]));
    creditsApi.balance().then(r => setBalance(r.balance)).catch(() => setBalance(0));
  }, []);

  return (
    <div className="hevi-account">
      <aside className="hevi-account__nav">
        <h1 className="hevi-account__brand">hevi</h1>
        {([
          ['videos', '我的视频'], ['canvases', '我的画布'],
          ['subjects', '我的主体'], ['settings', '账户设置'],
        ] as [Tab, string][]).map(([id, label]) => (
          <button key={id} type="button" className="hevi-account__navitem"
            data-active={tab === id ? 'true' : undefined}
            onClick={() => setTab(id)}>{label}</button>
        ))}
      </aside>

      <main className="hevi-account__main">
        {tab === 'videos' && (
          <section>
            <h2 className="hevi-account__title">我的视频</h2>
            <div className="hevi-account__list">
              {tasks.map(t => (
                <div key={t.task_id} className="hevi-account__card">
                  <div className="hevi-account__card-head">
                    <span className="hevi-account__card-name">任务 {t.task_id}</span>
                    <span className="hevi-account__card-status" data-status={t.status}>{STATUS_TEXT[t.status]}</span>
                  </div>
                  {t.status === 'running' && (
                    <OTaskProgress percent={t.percent} stage={t.stage} status="running" />
                  )}
                  {t.status === 'failed' && (
                    <OTaskProgress percent={t.percent} stage={t.stage} status="failed"
                      errorMessage="配音阶段失败" onResume={() => {}} />
                  )}
                  {t.status === 'completed' && !USE_MOCK && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      <video
                        src={taskApi.videoUrl(t.task_id)}
                        poster={taskApi.coverUrl(t.task_id)}
                        controls
                        playsInline
                        preload="metadata"
                        style={{ width: '100%', maxHeight: '60vh', borderRadius: 8, background: '#000' }}
                      />
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                        <a className="oui-btn" href={taskApi.videoUrl(t.task_id)} download>下载</a>
                        <select
                          className="hevi-account__export-fmt"
                          defaultValue="mp4"
                          onChange={e => {
                            const fmt = e.target.value;
                            window.open(taskApi.exportUrl(t.task_id, fmt), '_blank');
                          }}
                        >
                          <option value="mp4">导出 mp4</option>
                          <option value="mov">导出 mov</option>
                          <option value="webm">导出 webm</option>
                          <option value="gif">导出 gif</option>
                        </select>
                        <select
                          className="hevi-account__export-fmt"
                          defaultValue=""
                          title="翻译配音导出:ASR+翻译+目标语种配音,首次生成较慢"
                          onChange={e => {
                            const lang = e.target.value;
                            if (!lang) return;
                            window.open(taskApi.dubUrl(t.task_id, lang), '_blank');
                            e.target.value = '';
                          }}
                        >
                          <option value="" disabled>导出配音版…</option>
                          <option value="en">English 配音</option>
                          <option value="ja">日本語 配音</option>
                          <option value="ko">한국어 配音</option>
                          <option value="es">Español 配音</option>
                        </select>
                      </div>
                    </div>
                  )}
                  <span className="hevi-account__card-date">{t.created_at}</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {tab === 'canvases' && (
          <section>
            <h2 className="hevi-account__title">我的画布</h2>
            <div className="hevi-account__grid">
              {canvases.map(c => (
                <a key={c.id} href="/" className="hevi-account__canvas">
                  <div className="hevi-account__canvas-thumb">▢</div>
                  <span className="hevi-account__canvas-name">{c.name}</span>
                  <span className="hevi-account__card-date">{c.updated_at}</span>
                </a>
              ))}
            </div>
          </section>
        )}

        {tab === 'subjects' && (
          <section>
            <h2 className="hevi-account__title">我的主体库</h2>

            <div className="hevi-account__subject-create">
              <button type="button" className="oui-btn-primary" onClick={() => setShowCreateForm(v => !v)}>
                {showCreateForm ? '收起' : '+ 新建角色'}
              </button>
              {subjectError && <span className="hevi-account__subject-err">{subjectError}</span>}
            </div>

            {showCreateForm && (
              <form className="hevi-account__subject-form" onSubmit={onCreateSubject}>
                <div className="hevi-account__subject-form-row">
                  <select value={newKind} onChange={e => setNewKind(e.target.value as SubjectKind)}>
                    {KIND_OPTIONS.map(k => <option key={k.v} value={k.v}>{k.l}</option>)}
                  </select>
                  <input placeholder="姓名 *" value={newName} onChange={e => setNewName(e.target.value)} required />
                </div>
                <input placeholder="描述 / 人设(可选)" value={newDescription} onChange={e => setNewDescription(e.target.value)} />
                <label className="hevi-account__subject-photo">
                  {newPhoto ? `已选:${newPhoto.name}` : '+ 首张参考照片(可选,建号后也能加)'}
                  <input type="file" accept="image/*" hidden onChange={e => setNewPhoto(e.target.files?.[0] ?? null)} />
                </label>
                <button type="submit" className="oui-btn-primary" disabled={subjectBusy}>
                  {subjectBusy ? '创建中…' : '创建角色'}
                </button>
              </form>
            )}

            <div className="hevi-account__char-list">
              {subjects.map(s => (
                <CharacterEditor
                  key={s.subject_id}
                  subject={s}
                  onUpdated={updated => setSubjects(prev => prev.map(x => x.subject_id === updated.subject_id ? updated : x))}
                  onDeleted={() => setSubjects(prev => prev.filter(x => x.subject_id !== s.subject_id))}
                />
              ))}
              {subjects.length === 0 && <p className="hevi-account__subject-empty">还没有角色,点上面「+ 新建角色」建一个。</p>}
            </div>
          </section>
        )}

        {tab === 'settings' && (
          <section>
            <h2 className="hevi-account__title">账户设置</h2>
            <div className="hevi-account__settings">
              <label className="hevi-field">
                <span className="hevi-field-label">显示名</span>
                <input className="hevi-field-input" defaultValue="创作者" />
              </label>
              <label className="hevi-field">
                <span className="hevi-field-label">邮箱</span>
                <input className="hevi-field-input" defaultValue="user@hevi.app" />
              </label>
              <div className="hevi-account__credits">
                <span className="hevi-field-label">credits 余额</span>
                <span className="hevi-account__credits-val">{balance.toLocaleString()}</span>
              </div>
              <button type="button" className="oui-btn-primary" style={{ alignSelf: 'flex-start' }}>保存</button>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
