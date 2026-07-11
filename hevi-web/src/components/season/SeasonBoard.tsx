/**
 * SeasonBoard — 剧集看板(SPEC-001 §4,短剧通道第四入口)
 * 只读:季(Series)→ 角色组 / StylePack / 集列表 → 每集卡片(状态/实时进度/封面/成片)。
 * 纯复用现有能力:seriesApi 拉季与集、taskApi 的 SSE 进度 / 封面 / 成片端点。
 * 镜头级(幕/镜)视图待 shot-list API 接入,当前展开到"本集剧情简报"。
 */
'use client';

import { useEffect, useState } from 'react';
import { useSSEProgress } from '@helios/oui';
import { seriesApi, taskApi, USE_MOCK } from '@/lib/api-client';
import type { Series, Episode, TaskShot } from '@/types/api';

const STATUS_LABEL: Record<string, string> = {
  pending: '待生成',
  running: '生成中',
  completed: '已出片',
  failed: '需返工',
  paused: '待审',
};

function errText(e: unknown): string {
  if (e instanceof Error && e.message === 'NOT_AUTHENTICATED') return '请先登录';
  return e instanceof Error ? e.message : '出错了';
}

export function SeasonBoard() {
  const [list, setList] = useState<Series[]>([]);
  const [selected, setSelected] = useState<Series | null>(null);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        setList(await seriesApi.list());
      } catch (e) {
        setErr(errText(e));
      }
    })();
  }, []);

  async function selectSeries(s: Series) {
    setSelected(s);
    setEpisodes([]);
    setErr(null);
    try {
      setEpisodes(await seriesApi.episodes(s.id));
    } catch (e) {
      setErr(errText(e));
    }
  }

  const doneCount = episodes.filter((e) => e.status === 'completed').length;

  return (
    <div className="hevi-sb">
      <h1 className="hevi-sb__title">剧集看板</h1>
      <p className="hevi-sb__sub">一部短剧 = 一个系列。逐集查看结构、生成进度与成片,角色/风格全季锁定。</p>
      {err && <div className="hevi-sb__err">{err}</div>}

      <div className="hevi-sb__cols">
        {/* 左:季列表 */}
        <div className="hevi-sb__side">
          <div className="hevi-sb__side-head">短剧({list.length})</div>
          {list.length === 0 ? (
            <div className="hevi-sb__empty">还没有短剧</div>
          ) : (
            list.map((s) => (
              <button
                key={s.id}
                className="hevi-sb__season"
                data-active={selected?.id === s.id ? 'true' : undefined}
                onClick={() => selectSeries(s)}
              >
                <span className="hevi-sb__season-name">{s.name}</span>
                <span className="hevi-sb__season-meta">{s.episode_count ?? 0} 集</span>
              </button>
            ))
          )}
        </div>

        {/* 右:选中季的看板 */}
        <div className="hevi-sb__main">
          {!selected ? (
            <div className="hevi-sb__empty hevi-sb__empty--big">选左侧一部短剧查看季/集看板</div>
          ) : (
            <>
              <div className="hevi-sb__season-head">{selected.name}</div>

              {/* 角色组 + StylePack 面板 */}
              <div className="hevi-sb__panels">
                <div className="hevi-sb__panel">
                  <div className="hevi-sb__panel-label">角色组(全季锁定)</div>
                  {selected.subject_ids && selected.subject_ids.length > 0 ? (
                    <div className="hevi-sb__chips">
                      {selected.subject_ids.map((sid) => (
                        <span key={sid} className="hevi-sb__chip" title={sid}>
                          {sid.slice(0, 8)}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="hevi-sb__panel-none">未绑定角色组(走 t2v)</div>
                  )}
                </div>
                <div className="hevi-sb__panel">
                  <div className="hevi-sb__panel-label">视觉基调(StylePack)</div>
                  <div className="hevi-sb__panel-val">
                    {selected.style_pack_id
                      ? `风格包 v${selected.style_pack_version ?? 1}`
                      : selected.style_preset || '—'}
                  </div>
                </div>
                <div className="hevi-sb__panel">
                  <div className="hevi-sb__panel-label">进度</div>
                  <div className="hevi-sb__panel-val">
                    {doneCount}/{episodes.length} 集已出片
                  </div>
                </div>
              </div>

              {/* 集列表 */}
              <div className="hevi-sb__eps">
                {episodes.length === 0 ? (
                  <div className="hevi-sb__empty">这一季还没有分集</div>
                ) : (
                  episodes.map((ep) => <EpisodeCard key={ep.id} ep={ep} />)
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function EpisodeCard({ ep }: { ep: Episode }) {
  const [open, setOpen] = useState(false);
  const [shots, setShots] = useState<TaskShot[] | null>(null);
  // 分集 endpoint 直接返 video_tasks 行,故任务 id = ep.id(ep.task_id 通常为空)。
  const taskId = ep.task_id ?? ep.id;
  const running = ep.status === 'running';
  // 每集一个 SSE 订阅(仅在生成中且非 mock 时开);hook 必须无条件调用,靠 url=null 关闭。
  const progress = useSSEProgress(
    running && !USE_MOCK && taskId ? taskApi.progressUrl(taskId) : null
  );

  const status = ep.status || 'pending';
  const percent = running ? progress?.percent ?? 0 : status === 'completed' ? 100 : 0;
  const firstLine = (ep.topic || '').split('\n')[0] || '(未命名)';
  const completed = status === 'completed';
  const plan = ep.config_json?.episode_plan;

  // 展开时拉镜头级卡片(仅非 mock);拉一次即缓存。
  useEffect(() => {
    if (!open || USE_MOCK || !taskId || shots !== null) return;
    (async () => {
      try {
        setShots(await taskApi.shots(taskId));
      } catch {
        setShots([]);
      }
    })();
  }, [open, taskId, shots]);

  return (
    <div className="hevi-sb__ep" data-status={status}>
      <button className="hevi-sb__ep-head" onClick={() => setOpen((v) => !v)}>
        <span className="hevi-sb__ep-idx">第 {(ep.episode_index ?? 0) + 1} 集</span>
        <span className="hevi-sb__ep-title">{firstLine}</span>
        <span className="hevi-sb__ep-status" data-status={status}>
          {STATUS_LABEL[status] ?? status}
        </span>
        <span className="hevi-sb__ep-toggle">{open ? '收起' : '展开'}</span>
      </button>

      {running && (
        <div className="hevi-sb__bar">
          <div className="hevi-sb__bar-fill" style={{ width: `${percent}%` }} />
          <span className="hevi-sb__bar-text">
            {percent}% {progress?.stage ? `· ${progress.stage}` : ''}
          </span>
        </div>
      )}

      {open && (
        <div className="hevi-sb__ep-body">
          {completed && (
            <video
              className="hevi-sb__ep-video"
              src={taskApi.videoUrl(taskId)}
              poster={taskApi.coverUrl(taskId)}
              controls
              playsInline
            />
          )}

          {/* 幕:本集节拍序列(来自 config_json.episode_plan) */}
          {plan?.beats && plan.beats.length > 0 && (
            <div className="hevi-sb__row">
              <span className="hevi-sb__row-label">幕 · 节拍</span>
              <div className="hevi-sb__beats">
                {plan.beats.map((b, i) => (
                  <span key={i} className="hevi-sb__beat">
                    {b}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* 镜:逐镜卡片(来自 shot_states) */}
          {shots && shots.length > 0 && (
            <div className="hevi-sb__row">
              <span className="hevi-sb__row-label">镜 · {shots.length}</span>
              <div className="hevi-sb__shots">
                {shots.map((s) => (
                  <div
                    key={s.shot_index}
                    className="hevi-sb__shot"
                    data-passed={s.passed === false ? 'no' : s.passed ? 'yes' : undefined}
                  >
                    <span className="hevi-sb__shot-idx">#{s.shot_index}</span>
                    <span className="hevi-sb__shot-status">{s.status}</span>
                    {typeof s.consistency_score === 'number' && (
                      <span className="hevi-sb__shot-score">一致性 {s.consistency_score.toFixed(2)}</span>
                    )}
                    {s.diagnosis_category && (
                      <span className="hevi-sb__shot-diag">{s.diagnosis_category}</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 本集剧情简报(派发时合成的 topic) */}
          <pre className="hevi-sb__ep-brief">{ep.topic || '(无简报)'}</pre>
        </div>
      )}
    </div>
  );
}
