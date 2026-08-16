/**
 * TongjianConsole — 通鉴 · 【我在历史现场】(Frontend SPEC v4.0 §2.1)
 * 处理历史素材与史料,以「讲解(分析/铺垫) + 现场演绎(关键节点/高潮高光)」混合呈现,
 * 重现历史情境。输入史料原文 → 一键启动 L0-L8 九层流水线 → 实时轮询各层进度。
 * 史实红线(CG2.5 台词出处校验)显式可开关:开启=严格模式(L2 仅允许带 quote_id 的逐字引语
 * 成对白,无引语事件转纯旁白叙述);关闭=允许为真实事件创作时代口吻的戏剧化对白。
 */
'use client';

import { useState, useEffect, useRef } from 'react';
import { tongjianApi } from '@/lib/api-client';
import { syncAuthToken } from '@/lib/auth-store';
import type { TongjianRunStatus } from '@/types/api';
import { ScriptReviewPanel } from './ScriptReviewPanel';

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

// ── 演绎模式配置(SPEC v4.0 §2.1)──────────────────────────────────────────
// 演绎比例 → L2 params 组合(include_commentary 讲解评论段 / dramatize 创作对白)。
const DRILL_RATIOS: { value: string; label: string; desc: string; commentary: boolean }[] = [
  {
    value: 'commentary', label: '讲解为主 · 讲解80% + 现场演绎20%',
    desc: '侧重旁白分析、铺垫与史论,高潮处少量点映', commentary: true,
  },
  {
    value: 'balanced', label: '均衡 · 讲解70% + 现场演绎30%（默认）',
    desc: '讲解与高潮演绎交错呈现,史料讲解为主轴', commentary: true,
  },
  {
    value: 'drama', label: '演绎为主 · 讲解50% + 现场演绎50%',
    desc: '重现场景冲突与关键节点演绎,讲解退居串联', commentary: false,
  },
];

// 视觉风格四档(SPEC v4.0 §2.1)→ L6 params.style。默认儿童卡通动画
// (水墨是成年观众取向, 通鉴里儿童向内容占比不小 —— 默认改卡通, 水墨保留可选)。
const VISUAL_STYLES: { value: string; label: string; prompt: string }[] = [
  {
    value: 'cartoon', label: '🧸 儿童卡通动画（默认）',
    prompt: '色彩鲜艳的儿童卡通动画风格,圆润可爱的角色造型,明亮欢快的配色,简洁清晰的大色块,温和明快的画风,适合儿童观看',
  },
  {
    value: 'ink', label: '🎨 国风水墨',
    prompt: '国画水墨写意人物画,单色水墨,写意笔触,宣纸质感,古风留白,沉稳大气',
  },
  {
    value: 'cinema', label: '🎬 拟真电影感',
    prompt: '电影级实拍质感,自然光影,写实历史场景,史诗构图,胶片色彩,浅景深',
  },
  {
    value: 'lianhuanhua', label: '🖌️ 连环画/工笔',
    prompt: '工笔重彩连环画风格,线描造型,色彩典雅,传统绘画质感,细节考究',
  },
];

// 讲解人预设(SPEC v4.0 §2.1 "📜 历史旁白·老张")→ L6 params.narr_tone(旁白语气)。
// 数字人出镜时走 L6 cloud_avatar(配音+口型)。
const NARRATORS: { value: string; label: string; tone: string }[] = [
  { value: 'laozhang', label: '📜 历史旁白·老张', tone: '沉稳' },
  { value: 'shusheng', label: '📚 儒生讲史·激昂', tone: '激昂' },
  { value: 'shiguan', label: '🏯 史官正音·凝重', tone: '凝重' },
];

const DEMO_TEXTS: { label: string; source: string; text: string }[] = [
  {
    label: '周纪一·智宣子立嗣（智果识人）',
    source: '资治通鉴·周纪一',
    text: `智宣子将以瑶为后。智果曰："不如宵也。瑶之贤于人者五，其不逮者一也。美鬓长大则贤，射御足力则贤，伎艺毕给则贤，巧文辩惠则贤，强毅果敢则贤；如是而甚不仁。夫以其五贤陵人，而以不仁行之，其谁能待之？若果立瑶也，智宗必灭。"弗听。智果别族于太史为辅氏。`,
  },
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

  // ── SPEC v4.0 §2.1 演绎与生成模式配置 ──
  const [drillRatio, setDrillRatio] = useState('balanced');       // 演绎比例
  const [visualStyle, setVisualStyle] = useState('cartoon');      // 视觉风格四档(默认儿童卡通动画)
  const [narrator, setNarrator] = useState('laozhang');           // 讲解人预设
  const [onCamera, setOnCamera] = useState(false);                // 数字人出镜讲解
  const [redline, setRedline] = useState(true);                   // CG2.5 史实红线

  // ── 出片规格 ──
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [resolution, setResolution] = useState('1080P');

  // ── 高级参数(折叠) ──
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [candidateN, setCandidateN] = useState(3);       // L1 立意候选数
  const [reviewMode, setReviewMode] = useState(true);    // 剧本出来后先人工审核(pause_after=L2)
  const [sayCharSec, setSayCharSec] = useState(0.32);    // L6 语速(每字秒)
  const [inkStyle, setInkStyle] = useState('');          // 手写风格词覆盖
  const [layerConfigJson, setLayerConfigJson] = useState('');

  const [busy, setBusy] = useState(false);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<TongjianRunStatus | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // run 状态存在后端(内存/DB),刷新页面只是丢了前端 state——挂载时找回仍在跑的 run,
  // 否则用户一刷新就以为流水线被中断了(其实后端还在跑,只是前端没了引用)。
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        syncAuthToken();
        const runs = await tongjianApi.listRuns();
        const active = runs.find(
          r => r.status === 'RUNNING' || r.status === 'PENDING' || r.status === 'AWAITING_REVIEW'
        );
        if (active && !cancelled) {
          setStatus(active);
          setRunId(active.run_id);
        }
      } catch {
        // 静默:找回失败不影响正常"新建一次"流程
      }
    })();
    return () => { cancelled = true; };
  }, []);

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
    if (!rawText.trim()) { setErr('请输入史料原文/纪实材料'); return; }
    setErr(null);
    setBusy(true);
    setStatus(null);

    const ratio = DRILL_RATIOS.find(r => r.value === drillRatio) ?? DRILL_RATIOS[1];
    // 史实红线严格模式:对白必须带 quote_id 逐字引语 → dramatize=False;
    // 否则由演绎比例决定是否允许创作对白。
    const dramatize = redline ? false : true;
    const l2params: Record<string, unknown> = {
      dramatize,
      include_commentary: ratio.commentary,
    };
    l2params.screenwriter_persona = redline
      ? '你是历史纪录片编剧,严守史料红线:凡对白必须逐字引用史料原文引语并标注出处(quote_id),无直接引语的事件一律用旁白叙述,绝不杜撰台词。讲解(分析/铺垫)与现场演绎(关键节点高潮)交错,重现历史情境。'
      : '你是历史纪录片编剧,以「讲解穿插高潮演绎」重现历史情境:讲解负责分析与铺垫,现场演绎还原关键节点与高潮时刻,可为真实事件创作符合时代口吻的戏剧化对白。';

    const l6params: Record<string, unknown> = {
      resolution,
      say_char_sec: sayCharSec,
      narr_tone: NARRATORS.find(n => n.value === narrator)?.tone ?? '沉稳',
    };
    const stylePrompt = inkStyle.trim() || (VISUAL_STYLES.find(v => v.value === visualStyle)?.prompt ?? '');
    if (stylePrompt) l6params.style = stylePrompt;

    // 组装逐层配置:渲染模式 → L6.model;表单参数 → L1/L2/L6.params;高级 JSON 再覆盖/补充。
    const layerConfig: Record<string, { model?: string | null; params?: Record<string, unknown> }> = {};
    if (onCamera) layerConfig.L6 = { model: 'cloud_avatar' };
    layerConfig.L1 = { params: { n: candidateN } };
    layerConfig.L2 = { params: l2params };
    layerConfig.L6 = { ...(layerConfig.L6 || {}), params: l6params };
    if (layerConfigJson.trim()) {
      try {
        const adv = JSON.parse(layerConfigJson);
        for (const [k, v] of Object.entries(adv as Record<string, { model?: string; params?: Record<string, unknown> }>)) {
          layerConfig[k] = {
            ...(layerConfig[k] || {}), ...v,
            params: { ...(layerConfig[k]?.params || {}), ...(v.params || {}) },
          };
        }
      } catch {
        setErr('逐层参数 JSON 格式错误'); setBusy(false); return;
      }
    }
    try {
      const r = await tongjianApi.startRun({
        source_name: sourceName,
        raw_text: rawText,
        target_duration_sec: targetDuration,
        aspect_ratio: aspectRatio,
        pause_after: reviewMode ? 'L2' : undefined,
        layer_config: layerConfig,
      });
      setRunId(r.run_id);
    } catch (e) {
      if (e instanceof Error && e.message === 'NOT_AUTHENTICATED') setErr('请先登录');
      else setErr(e instanceof Error ? e.message : '出错了');
    } finally {
      setBusy(false);
    }
  }

  const allDone = status?.status === 'COMPLETED' || status?.status === 'FAILED';
  const completedCount = status?.layers?.filter(l => l.status === 'PASSED' || l.status === 'DEGRADED').length ?? 0;
  const totalLayers = status?.layers?.length ?? 9;

  return (
    <div className="tj">
      {/* ── 主题头(SPEC v4.0 §2.1) ── */}
      <div className="tj__hero">
        <div className="tj__hero-overline">🏛️ 历史素材与史料大类 · 通鉴通道</div>
        <h1 className="tj__title">【我在历史现场】</h1>
        <p className="tj__sub">
          处理历史素材与史料，以「讲解（分析/铺垫）+ 现场高潮演绎」重现历史情境，
          台词逐句经 CG2.5 史实出处校验
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

      {/* ── ① 历史素材与纪实文本 ── */}
      <section className="tj-sec">
        <div className="tj-sec__head">
          <span className="tj-sec__num">①</span>
          <h2>历史素材与纪实文本</h2>
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
          <span className="tj-field__label">章节/事件标题</span>
          <input value={sourceName} onChange={e => setSourceName(e.target.value)}
            placeholder="如: 赤壁之战·草船借箭 / 巨鹿之战" />
        </label>
        <label className="tj-field tj-field--tall">
          <span className="tj-field__label">
            史料原文/纪实材料（文言文，{rawText.length} 字）
          </span>
          <textarea rows={10}
            placeholder="粘贴史书原文、历史笔记或文献材料… L0 层自动完成分段、纪年换算、人物消歧、事件链抽取"
            value={rawText} onChange={e => setRawText(e.target.value)} />
        </label>
      </section>

      {/* ── ② 演绎与生成模式配置 ── */}
      <section className="tj-sec">
        <div className="tj-sec__head">
          <span className="tj-sec__num">②</span>
          <h2>演绎与生成模式配置</h2>
        </div>

        <div className="tj-field">
          <span className="tj-field__label">演绎比例（讲解 + 现场演绎 混合呈现）</span>
          <div className="tj-radio-list">
            {DRILL_RATIOS.map(r => (
              <button key={r.value} type="button"
                className={`tj-radio tj-radio--${r.value}`}
                data-on={drillRatio === r.value ? 'true' : undefined}
                onClick={() => setDrillRatio(r.value)}>
                <span className="tj-radio__label">{r.label}</span>
                <span className="tj-radio__desc">{r.desc}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="tj-field">
          <span className="tj-field__label">视觉风格</span>
          <div className="tj-seg">
            {VISUAL_STYLES.map(v => (
              <button type="button" key={v.value} data-on={visualStyle === v.value ? 'true' : undefined}
                onClick={() => setVisualStyle(v.value)}>{v.label}</button>
            ))}
          </div>
        </div>

        <div className="tj-grid">
          <div className="tj-field">
            <span className="tj-field__label">讲解人 / 数字人（可选出镜）</span>
            <select value={narrator} onChange={e => setNarrator(e.target.value)}>
              {NARRATORS.map(n => <option key={n.value} value={n.value}>{n.label}</option>)}
            </select>
          </div>
          <div className="tj-field">
            <span className="tj-field__label">讲解呈现</span>
            <div className="tj-seg">
              <button type="button" data-on={!onCamera ? 'true' : undefined}
                onClick={() => setOnCamera(false)}>📜 纯旁白讲解</button>
              <button type="button" data-on={onCamera ? 'true' : undefined}
                onClick={() => setOnCamera(true)}>🎙️ 数字人出镜</button>
            </div>
          </div>
        </div>

        <label className={`tj-field tj-field--check ${redline ? 'tj-field--redline' : ''}`}>
          <input type="checkbox" checked={redline} onChange={e => setRedline(e.target.checked)} />
          <span className="tj-field__label">
            <b>严格开启 CG2.5 台词出处校验</b>（史实红线：对白必须有 quote_id 逐字引语引用；
            无直接引语的事件转为纯旁白叙述，绝不杜撰台词）
          </span>
        </label>
        {redline && (
          <p className="tj-hint">红线模式下，「演绎为主」比例的戏剧化创作对白将被自动收敛为逐字引语对白。</p>
        )}
      </section>

      {/* ── ③ 出片规格 ── */}
      <section className="tj-sec">
        <div className="tj-sec__head">
          <span className="tj-sec__num">③</span>
          <h2>出片规格</h2>
        </div>
        <div className="tj-grid">
          <div className="tj-field">
            <span className="tj-field__label">画幅</span>
            <div className="tj-seg">
              {(['16:9', '9:16', '1:1'] as const).map(r => (
                <button type="button" key={r} data-on={aspectRatio === r ? 'true' : undefined}
                  onClick={() => setAspectRatio(r)}>
                  {r === '16:9' ? '16:9 横屏（纪录片式）' : r === '9:16' ? '9:16 竖屏' : '1:1 方形'}
                </button>
              ))}
            </div>
          </div>
          <div className="tj-field">
            <span className="tj-field__label">画质</span>
            <div className="tj-seg">
              {(['1080P', '720P', '480P'] as const).map(r => (
                <button type="button" key={r} data-on={resolution === r ? 'true' : undefined}
                  onClick={() => setResolution(r)}>{r}</button>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── 高级参数(折叠) ── */}
      <section className="tj-sec">
        <button type="button" className="tj-adv-toggle" onClick={() => setShowAdvanced(!showAdvanced)}>
          {showAdvanced ? '▾' : '▸'} 高级参数（目标时长 / 立意候选 / 语速 / 风格词 / 审核 / 逐层 JSON）
        </button>
        {showAdvanced && (
          <div className="tj-adv-body">
            <div className="tj-grid">
              <label className="tj-field">
                <span className="tj-field__label">目标时长（秒）</span>
                <input type="number" min={60} max={600} step={30}
                  value={targetDuration} onChange={e => setTargetDuration(Number(e.target.value))} />
              </label>
              <label className="tj-field">
                <span className="tj-field__label">立意候选数（L1 · 越多越优但更慢）</span>
                <input type="number" min={1} max={5} step={1}
                  value={candidateN} onChange={e => setCandidateN(Number(e.target.value))} />
              </label>
            </div>
            <div className="tj-grid">
              <label className="tj-field">
                <span className="tj-field__label">语速（L6 · 每字秒 · 越大越慢）</span>
                <input type="number" min={0.2} max={0.5} step={0.02}
                  value={sayCharSec} onChange={e => setSayCharSec(Number(e.target.value))} />
              </label>
              <label className="tj-field">
                <span className="tj-field__label">风格词（手写覆盖，可留空用上方预设）</span>
                <input value={inkStyle} onChange={e => setInkStyle(e.target.value)}
                  placeholder="现代卡通动画风格,鲜艳色彩,简洁线条…" />
              </label>
            </div>
            <label className="tj-field tj-field--check">
              <input type="checkbox" checked={reviewMode} onChange={e => setReviewMode(e.target.checked)} />
              <span className="tj-field__label">
                剧本先人工审核（推荐 · 出立意+剧本后暂停，审核/编辑确认后再渲染，避免在错的剧本上白烧渲染时间）
              </span>
            </label>
            <label className="tj-field">
              <span className="tj-field__label">逐层参数（高级 · JSON · 可留空，覆盖上面没含的层/参数）</span>
              <textarea rows={2} value={layerConfigJson}
                onChange={e => setLayerConfigJson(e.target.value)}
                placeholder='{"L2":{"model":"qwen_cloud"},"L6":{"params":{"watermark":false}}}' />
            </label>
          </div>
        )}
      </section>

      {/* ── 启动按钮 ── */}
      <div className="tj-actions">
        <button type="button" className="tj-btn tj-btn--primary"
          onClick={startPipeline} disabled={busy || (!allDone && !!runId)}>
          {busy ? '提交中…' : (!allDone && runId) ? '流水线运行中…' : '🏛️ 重建历史现场（启动 L0-L8 九层流水线）'}
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
               status.status === 'AWAITING_REVIEW' ? '📝 待人工审核' :
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
                {(() => {
                  const gr = l.gate_report as { errors?: string[]; warnings?: string[] } | null;
                  const items = [...(gr?.errors ?? []), ...(gr?.warnings ?? [])];
                  return items.length > 0 ? (
                    <span className="tj-chip tj-chip--warn" title={items.join('\n')}>
                      门禁 {items.length} 项
                    </span>
                  ) : null;
                })()}
                {l.error && <span className="tj-layer__err" title={l.error}>！</span>}
              </div>
            ))}
          </div>

          {/* 剧本人工审核台(卡在 L2) */}
          {status.status === 'AWAITING_REVIEW' && runId && (
            <ScriptReviewPanel
              runId={runId}
              onResumed={() => setStatus(s => (s ? { ...s, status: 'RUNNING', current_layer: 'L3' } : s))}
            />
          )}

          {/* 成片结果 */}
          {status.status === 'COMPLETED' && status.result_video_path && runId && (
            <div className="tj-result">
              <div className="tj-result__head">🎬 成片已完成</div>
              <video
                className="tj-result__video"
                src={tongjianApi.videoUrl(runId)}
                controls
                playsInline
                preload="metadata"
              />
              <div className="tj-result__actions">
                <a
                  className="oui-btn"
                  href={tongjianApi.videoUrl(runId)}
                  download={`tongjian_${runId.slice(0, 8)}.mp4`}
                >
                  ⬇ 下载成片
                </a>
              </div>
              <p className="tj-result__path">{status.result_video_path}</p>
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
