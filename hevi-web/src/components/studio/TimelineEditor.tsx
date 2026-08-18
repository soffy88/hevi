'use client';

import { useEffect, useMemo, useState, type MouseEvent } from 'react';
import { studioApi, type StudioTimeline, type StudioTimelineClip } from '@/lib/api-client';

const TRACKS = [
  { id: 'video', label: '画面' },
  { id: 'audio', label: '对白' },
  { id: 'captions', label: '字幕' },
] as const;

export function TimelineEditor() {
  const [tl, setTl] = useState<StudioTimeline | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [topic, setTopic] = useState('盐税为什么叫薪水');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [px, setPx] = useState(28);
  const [playhead, setPlayhead] = useState(0);
  const [bgmDraft, setBgmDraft] = useState('');

  const width = useMemo(
    () => Math.max(720, Math.ceil((tl?.duration_s ?? 20) * px) + 96),
    [tl, px],
  );
  const clip = tl?.clips.find((c) => c.clip_id === selected) ?? null;

  useEffect(() => {
    setBgmDraft(tl?.bgm ?? '');
  }, [tl?.bgm, tl?.timeline_id]);

  const flash = (t: string) => setMsg(t);

  const fromSlate = async () => {
    setBusy(true);
    try {
      const slate = await studioApi.slate('explainer', { topic }) as {
        data?: { edit_plan?: Record<string, unknown>; timeline?: StudioTimeline };
        production_order?: { edit_plan?: Record<string, unknown> };
      };
      const existing = slate.data?.timeline;
      if (existing?.timeline_id) {
        setTl(existing);
        flash('已挂上产线时间线');
        return;
      }
      const plan = slate.data?.edit_plan ?? slate.production_order?.edit_plan ?? { cuts: [] };
      const created = await studioApi.createTimeline(topic, plan as Record<string, unknown>);
      setTl(created);
      flash('已从解说产线生成时间线');
    } catch (e) {
      flash(e instanceof Error ? e.message : '生成失败');
    } finally {
      setBusy(false);
    }
  };

  const patch = async (body: Record<string, unknown>) => {
    if (!tl) return;
    try {
      setTl(await studioApi.patchTimeline(tl.timeline_id, body));
    } catch (e) {
      flash(e instanceof Error ? e.message : '更新失败');
    }
  };

  const exportTl = async () => {
    if (!tl) return;
    setBusy(true);
    try {
      const out = await studioApi.exportTimeline(tl.timeline_id);
      flash(String(out.status ?? out.reason ?? '已提交导出'));
    } catch (e) {
      flash(e instanceof Error ? e.message : '导出失败');
    } finally {
      setBusy(false);
    }
  };

  const seekFromEvent = (e: MouseEvent<HTMLDivElement>) => {
    const lane = e.currentTarget.getBoundingClientRect();
    const next = Math.max(0, (e.clientX - lane.left) / px);
    setPlayhead(Math.round(next * 10) / 10);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!tl || !selected) return;
      const target = e.target as HTMLElement;
      if (target.matches('input,textarea,select')) return;
      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        void patch({ clip_id: selected, action: 'drop' });
      } else if (e.key === 'm') {
        void patch({ clip_id: selected, action: 'mute' });
      } else if (e.key === 'k') {
        void patch({ clip_id: selected, action: 'keep' });
      } else if (e.key === 's') {
        e.preventDefault();
        void patch({ split_at_s: playhead });
      } else if (e.key === 'r') {
        void patch({ ripple: true });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [tl, selected, playhead]);

  const ticks = Math.ceil((tl?.duration_s ?? 20) / 5) + 1;

  return (
    <div className="hevi-tl">
      <header className="hevi-tl__bar">
        <h1>时间线</h1>
        <input aria-label="主题" value={topic} onChange={(e) => setTopic(e.target.value)} />
        <button type="button" onClick={fromSlate} disabled={busy}>从产线生成</button>
        <button type="button" onClick={() => void patch({ split_at_s: playhead })} disabled={!tl}>
          切开 {playhead.toFixed(1)}s
        </button>
        <button type="button" onClick={() => void patch({ ripple: true })} disabled={!tl}>
          收缝
        </button>
        <button type="button" onClick={exportTl} disabled={!tl || busy}>重导出</button>
        <label className="hevi-tl__zoom">缩放
          <input
            type="range"
            min={12}
            max={64}
            value={px}
            onChange={(e) => setPx(Number(e.target.value))}
            aria-label="时间线缩放"
          />
        </label>
        <a href="/studio">回画布</a>
      </header>
      {msg && <p className="hevi-tl__msg">{msg}</p>}
      <p className="hevi-tl__hint">
        点尺条定位游标。选中镜后：Delete 丢掉 · M 静音 · K 保留 · S 切开 · R 收缝。改镜不会重跑产线。
      </p>

      <div className="hevi-tl__board" style={{ minWidth: width }}>
        <div className="hevi-tl__ruler" onClick={seekFromEvent} role="slider" aria-valuenow={playhead} aria-label="游标">
          {Array.from({ length: ticks }, (_, i) => (
            <span key={i} style={{ left: i * 5 * px }}>{i * 5}s</span>
          ))}
          <i className="hevi-tl__playhead" style={{ left: playhead * px }} />
        </div>
        {TRACKS.map((track) => (
          <div key={track.id} className="hevi-tl__track">
            <div className="hevi-tl__track-label">{track.label}</div>
            <div className="hevi-tl__lane" onClick={seekFromEvent}>
              {(tl?.tracks[track.id] ?? []).map((c: StudioTimelineClip) => (
                <button
                  key={c.clip_id}
                  type="button"
                  className="hevi-tl__clip"
                  data-action={c.action}
                  data-selected={selected === c.clip_id ? 'true' : undefined}
                  style={{ left: c.start_s * px, width: Math.max(36, c.duration_s * px) }}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelected(c.clip_id);
                    setPlayhead(c.start_s);
                  }}
                >
                  {c.label}
                </button>
              ))}
              <i className="hevi-tl__playhead" style={{ left: playhead * px }} />
            </div>
          </div>
        ))}
        {tl?.bgm ? (
          <div className="hevi-tl__track">
            <div className="hevi-tl__track-label">配乐</div>
            <div className="hevi-tl__lane">
              <span className="hevi-tl__clip hevi-tl__clip--bgm" style={{ left: 0, width: Math.max(36, (tl.duration_s || 1) * px) }}>
                {tl.bgm}
              </span>
            </div>
          </div>
        ) : null}
      </div>

      {clip && tl && (
        <aside className="hevi-tl__inspect">
          <h2>{clip.clip_id} · {clip.track}</h2>
          <p>{clip.text}</p>
          <label>动作
            <select
              value={clip.action}
              onChange={(e) => void patch({ clip_id: clip.clip_id, action: e.target.value })}
            >
              <option value="keep">保留</option>
              <option value="drop">丢掉</option>
              <option value="mute">静音</option>
            </select>
          </label>
          <label>时长（秒）
            <input
              type="number"
              min={0.4}
              step={0.1}
              value={clip.duration_s}
              onChange={(e) => void patch({ clip_id: clip.clip_id, duration_s: Number(e.target.value) })}
            />
          </label>
          <label>BGM
            <input
              value={bgmDraft}
              onChange={(e) => setBgmDraft(e.target.value)}
              onBlur={() => {
                if (bgmDraft !== tl.bgm) void patch({ bgm: bgmDraft });
              }}
              placeholder="warm / tense / 路径"
            />
          </label>
        </aside>
      )}
    </div>
  );
}
