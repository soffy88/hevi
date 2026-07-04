/**
 * AccountCenter — 用户中心(2.3)
 * 我的视频 / 我的画布 / 我的主体库 / 账户设置
 */
'use client';

import { useState, useEffect, useRef } from 'react';
import { OTaskProgress } from '@helios/oui';
import { MOCK_TASKS, MOCK_CANVASES, MOCK_SUBJECTS } from '@/lib/mock-data';
import { taskApi, canvasApi, subjectApi, creditsApi, USE_MOCK } from '@/lib/api-client';
import type { TaskInfo, CanvasGraph, Subject } from '@/types/api';

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

  // 主体库上传态
  const [subjectBusy, setSubjectBusy] = useState(false);
  const [subjectError, setSubjectError] = useState<string | null>(null);
  const createSubjectRef = useRef<HTMLInputElement>(null);

  const refreshSubjects = () => subjectApi.list().then(setSubjects).catch(() => {});

  // 上传照片建新角色
  const onCreateSubject = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setSubjectError(null);
    setSubjectBusy(true);
    try { await subjectApi.fromPhoto(file); await refreshSubjects(); }
    catch { setSubjectError('上传失败,请重试'); }
    finally { setSubjectBusy(false); }
  };

  // 给已有角色添加参考图
  const onAddReference = async (subjectId: string, e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setSubjectError(null);
    setSubjectBusy(true);
    try { await subjectApi.uploadReference(subjectId, file); await refreshSubjects(); }
    catch { setSubjectError('添加参考图失败,请重试'); }
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
                        controls
                        playsInline
                        preload="metadata"
                        style={{ width: '100%', maxHeight: '60vh', borderRadius: 8, background: '#000' }}
                      />
                      <a className="oui-btn" href={taskApi.videoUrl(t.task_id)} download
                        style={{ alignSelf: 'flex-start' }}>下载</a>
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
            {/* 上传照片建角色 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
              <button type="button" className="oui-btn-primary" disabled={subjectBusy}
                onClick={() => createSubjectRef.current?.click()}>
                {subjectBusy ? '处理中…' : '上传照片建角色'}
              </button>
              {subjectError && <span style={{ color: '#e5484d', fontSize: 13 }}>{subjectError}</span>}
              <input ref={createSubjectRef} type="file" accept="image/*" hidden onChange={onCreateSubject} />
            </div>
            <div className="hevi-account__grid">
              {subjects.map(s => (
                <div key={s.subject_id} className="hevi-account__subject">
                  {s.reference_images && s.reference_images.length > 0 ? (
                    <img src={subjectApi.imageUrl(s.subject_id)} alt={s.name}
                      onError={e => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                      style={{ width: 72, height: 72, objectFit: 'cover', borderRadius: '50%', background: '#f0f0f4' }} />
                  ) : (
                    <div className="hevi-account__subject-avatar">{s.name[0]}</div>
                  )}
                  <span className="hevi-account__canvas-name">{s.name}</span>
                  <span className="hevi-account__card-date">{s.kind}</span>
                  {/* 添加参考图 */}
                  <label className="oui-btn" style={{ marginTop: 6, fontSize: 12, cursor: 'pointer' }}>
                    添加参考图
                    <input type="file" accept="image/*" hidden disabled={subjectBusy}
                      onChange={e => onAddReference(s.subject_id, e)} />
                  </label>
                </div>
              ))}
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
