/**
 * TongjianConsole — 通鉴全自动流水线控制台(HEVI-SPEC-01)
 * 输入《资治通鉴》任一章节原文 → 一键启动 L0-L8 流水线 → 实时轮询各层进度
 */
'use client';

import { useState, useEffect, useRef } from 'react';
import { tongjianApi } from '@/lib/api-client';
import type { TongjianRunStatus } from '@/types/api';

const LAYER_LABELS: Record<string, string> = {
  L0: '史料预处理',
  L1: '立意（创作宪法）',
  L2: '剧本',
  L3: '配音 TTS',
  L4: '分镜',
  L5: '角色卡',
  L6: '场景/画面生成',
  L7: '音乐规划',
  L8: '字幕+剪辑合成',
};

const STATUS_ICON: Record<string, string> = {
  PENDING: '○',
  RUNNING: '⟳',
  PASSED: '✓',
  DEGRADED: '⚠',
  FAILED: '✗',
};

const STATUS_CLASS: Record<string, string> = {
  PENDING: 'tj-layer--pending',
  RUNNING: 'tj-layer--running',
  PASSED: 'tj-layer--passed',
  DEGRADED: 'tj-layer--degraded',
  FAILED: 'tj-layer--failed',
};

const DEMO_TEXTS: { label: string; source: string; text: string }[] = [
  {
    label: '周纪一·三家分晋',
    source: '资治通鉴·周纪一',
    text: `初命晋大夫魏斯、赵籍、韩虔为诸侯。臣光曰：臣闻天子之职莫大于礼，礼莫大于分，分莫大于名。何谓礼？纪纲是也。何谓分？君臣是也。何谓名？公、侯、卿、大夫是也。

智伯请地于韩康子，使使者致万家之邑于智伯；又求地于魏桓子，复与之万家之邑；智伯又求蔡皋狼之地于赵襄子，襄子弗与。智伯怒，帅韩、魏之甲以攻赵氏。赵襄子奔保晋阳。

原过从，后，至于王泽，见三人焉，自带以上可见，自带以下不可见，与原过竹二节，莫知其何故，曰："为我以是遗赵毋恤。"原过既至，以竹二节遗赵毋恤，毋恤受，熟视之，乃剖其竹，有朱书曰："赵毋恤，余霍泰山山阳侯天使也，三月丙戌，余将使女反灭智氏，女亦立我百邑，余将赐女林胡之地。至于后世，且有伉王，亦不止霸。"`,
  },
];

export function TongjianConsole() {
  const [sourceName, setSourceName] = useState('资治通鉴·周纪一');
  const [rawText, setRawText] = useState('');
  const [targetDuration, setTargetDuration] = useState(180);
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [busy, setBusy] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<TongjianRunStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 轮询进度
  useEffect(() => {
    if (!runId) return;
    const poll = async () => {
      try {
        const s = await tongjianApi.getStatus(runId);
        setStatus(s);
        if (s.status === 'COMPLETED' || s.status === 'FAILED') {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        // 静默:网络偶发失败不清状态
      }
    };
    poll();
    pollRef.current = setInterval(poll, 3000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [runId]);

  function fillDemo(d: typeof DEMO_TEXTS[0]) {
    setSourceName(d.source);
    setRawText(d.text);
  }

  async function startPipeline() {
    if (!rawText.trim()) { setErr('请输入原文'); return; }
    setErr(null);
    setBusy(true);
    setStatus(null);
    try {
      const r = await tongjianApi.startRun({
        source_name: sourceName,
        raw_text: rawText,
        target_duration_sec: targetDuration,
        aspect_ratio: aspectRatio,
      });
      setRunId(r.run_id);
    } catch (e) {
      setErr(e instanceof Error ? e.message : '出错了');
    } finally {
      setBusy(false);
    }
  }

  const allDone = status?.status === 'COMPLETED' || status?.status === 'FAILED';
  const completedCount = status?.layers?.filter(l => l.status === 'PASSED' || l.status === 'DEGRADED').length ?? 0;
  const totalLayers = status?.layers?.length ?? 9;

  return (
    <div className="tj">
      <div className="tj__hero">
        <h1 className="tj__title">通鉴自动成片</h1>
        <p className="tj__sub">
          输入《资治通鉴》任一章节原文，零人工干预输出历史解说视频（含配音、字幕、配乐）
        </p>
        <div className="tj__badges">
          <span className="tj__badge">L0 史料</span>
          <span className="tj__badge-arrow">→</span>
          <span className="tj__badge">L1 立意</span>
          <span className="tj__badge-arrow">→</span>
          <span className="tj__badge">L2 剧本</span>
          <span className="tj__badge-arrow">→</span>
          <span className="tj__badge">L3 配音</span>
          <span className="tj__badge-arrow">→</span>
          <span className="tj__badge">L6 画面</span>
          <span className="tj__badge-arrow">→</span>
          <span className="tj__badge tj__badge--end">成片</span>
        </div>
      </div>

      {/* ── 输入区 ── */}
      <section className="tj-sec">
        <div className="tj-sec__head">
          <span className="tj-sec__num">①</span>
          <h2>章节原文</h2>
        </div>
        <div className="tj-demos">
          {DEMO_TEXTS.map(d => (
            <button key={d.label} type="button" className="tj-demo-btn"
              onClick={() => fillDemo(d)}>
              填入示例：{d.label}
            </button>
          ))}
        </div>
        <label className="tj-field">
          <span className="tj-field__label">章节名（来源标注）</span>
          <input value={sourceName} onChange={e => setSourceName(e.target.value)}
            placeholder="资治通鉴·周纪一" />
        </label>
        <label className="tj-field tj-field--tall">
          <span className="tj-field__label">
            原文（文言文，{rawText.length} 字）
          </span>
          <textarea rows={10}
            placeholder="粘贴资治通鉴原文，L0 层自动完成分段、纪年换算、人物消歧、事件链抽取…"
            value={rawText} onChange={e => setRawText(e.target.value)} />
        </label>
      </section>

      {/* ── 参数区 ── */}
      <section className="tj-sec">
        <div className="tj-sec__head">
          <span className="tj-sec__num">②</span>
          <h2>成片参数</h2>
        </div>
        <div className="tj-grid">
          <label className="tj-field">
            <span className="tj-field__label">目标时长（秒）</span>
            <input type="number" min={60} max={600} step={30}
              value={targetDuration} onChange={e => setTargetDuration(Number(e.target.value))} />
          </label>
          <div className="tj-field">
            <span className="tj-field__label">画幅</span>
            <div className="tj-seg">
              {(['16:9', '9:16', '1:1'] as const).map(r => (
                <button type="button" key={r} data-on={aspectRatio === r ? 'true' : undefined}
                  onClick={() => setAspectRatio(r)}>{r}</button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── 启动按钮 ── */}
      <div className="tj-actions">
        <button type="button" className="tj-btn tj-btn--primary"
          onClick={startPipeline} disabled={busy || (!allDone && !!runId)}>
          {busy ? '提交中…' : (!allDone && runId) ? '流水线运行中…' : '▶ 一键开始成片'}
        </button>
        {runId && allDone && (
          <button type="button" className="tj-btn"
            onClick={() => { setRunId(null); setStatus(null); }}>
            重新开始
          </button>
        )}
      </div>

      {err && <div className="tj-err">{err}</div>}

      {/* ── 进度面板 ── */}
      {status && (
        <div className="tj-progress">
          <div className="tj-progress__head">
            <span className={`tj-run-badge tj-run-badge--${status.status.toLowerCase()}`}>
              {status.status === 'RUNNING' ? '⟳ 运行中' :
               status.status === 'COMPLETED' ? '✓ 已完成' :
               status.status === 'FAILED' ? '✗ 失败' : '待机'}
            </span>
            <span className="tj-progress__count">{completedCount}/{totalLayers} 层完成</span>
            {status.current_layer && status.status === 'RUNNING' && (
              <span className="tj-progress__cur">
                当前：{LAYER_LABELS[status.current_layer] ?? status.current_layer}
              </span>
            )}
          </div>

          {/* 进度条 */}
          <div className="tj-bar">
            <div className="tj-bar__fill"
              style={{ width: `${Math.round(completedCount / totalLayers * 100)}%` }} />
          </div>

          {/* 各层状态 */}
          <div className="tj-layers">
            {status.layers.map(l => (
              <div key={l.layer} className={`tj-layer ${STATUS_CLASS[l.status] ?? ''}`}>
                <span className="tj-layer__icon">{STATUS_ICON[l.status] ?? '○'}</span>
                <span className="tj-layer__code">{l.layer}</span>
                <span className="tj-layer__name">{LAYER_LABELS[l.layer] ?? l.layer}</span>
                {l.status === 'RUNNING' && <span className="tj-layer__spin" />}
                {l.degraded && <span className="tj-chip tj-chip--warn">降级</span>}
                {l.error && <span className="tj-layer__err" title={l.error}>！</span>}
              </div>
            ))}
          </div>

          {/* 成片结果 */}
          {status.status === 'COMPLETED' && status.result_video_path && (
            <div className="tj-result">
              <div className="tj-result__head">🎬 成片已完成</div>
              <p className="tj-result__path">{status.result_video_path}</p>
              <p className="tj-hint">成片已落盘，可在「我的」任务列表查看或下载。</p>
            </div>
          )}

          {status.status === 'FAILED' && (
            <div className="tj-result tj-result--fail">
              <div className="tj-result__head">流水线失败</div>
              <p className="tj-hint">{status.error ?? '未知错误'}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
