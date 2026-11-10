/**
 * CreateEntry — 首页创作入口（S21）
 *
 * 一个输入框 + 一排出品形式卡片（默认“自动”）。选了形式后先在画布出
 * 脚本与分镜，确认/改单格后再渲染；内部 line id 不出现。
 */
'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { isAuthenticated } from '@/lib/auth-store';
import { studioApi, USE_MOCK, type CraftIssue, type FormatPlan, type StudioFormat } from '@/lib/api-client';

type FormatEvent = 'format_selected' | 'auto_changed' | 'storyboard_edited' | 'gated_click';

const FALLBACK_FORMATS: StudioFormat[] = [
  { id: 'auto', label: '自动', summary: '让 HEVI 按输入判断', example: '一句话也可以', sample_video: null, needs_media: false, gated: false, default_style: 'auto', styles: [], available: true, available_styles: [] },
  { id: 'history_scene', label: '历史现场', summary: '史料或主题 → 带出处的讲述、演绎与时间线。', example: '「安史之乱前夜，长安城的一夜」', sample_video: null, needs_media: false, gated: false, default_style: 'standard', styles: [], available: true, available_styles: [] },
  { id: 'digital_human', label: '数字人口播', summary: '一段文案 → 数字人或口播人头出镜讲解。', example: '「用 60 秒讲清楚复利为什么反直觉」', sample_video: null, needs_media: false, gated: false, default_style: 'auto', styles: [], available: true, available_styles: [] },
  { id: 'live_drama', label: '真人短剧', summary: '一句话梗概 → 剧本、分镜、写实画面与成片。', example: '「深夜便利店，店员发现常客的小票停在五年前」', sample_video: null, needs_media: false, gated: true, default_style: 'live_action', styles: [], available: false, available_styles: [], gated_reason: '即将开放' },
  { id: 'comic_drama', label: '漫剧', summary: '动漫风短剧，或轻量的静态漫画解说。', example: '「社畜的猫在凌晨三点开口说话了」', sample_video: null, needs_media: false, gated: false, default_style: 'anime', styles: [], available: true, available_styles: [] },
  { id: 'animation', label: '动画', summary: '角色动画、手绘或 2D 解说动画。', example: '「一个小机器人第一次学会走路」', sample_video: null, needs_media: false, gated: false, default_style: 'character', styles: [], available: true, available_styles: [] },
  { id: 'explainer', label: '知识讲解', summary: '把一个问题讲明白：动效标题或 3D 演示。', example: '「为什么飞机能飞起来」', sample_video: null, needs_media: false, gated: false, default_style: 'standard', styles: [], available: true, available_styles: [] },
];

function formatError(error: unknown): string {
  const message = error instanceof Error ? error.message : '请求失败';
  if (message.includes('403')) return '该出品形式即将开放，稍后再来。';
  if (message.includes('429')) return '今天已生成 5 条成片，明天再来。';
  return message;
}

export function CreateEntry() {
  const router = useRouter();
  const [formats, setFormats] = useState<StudioFormat[]>(FALLBACK_FORMATS);
  const [formatId, setFormatId] = useState('auto');
  const [styleId, setStyleId] = useState('');
  const [topic, setTopic] = useState('');
  const [mediaPath, setMediaPath] = useState('');
  const [imagePath, setImagePath] = useState('');
  const [hasMedia, setHasMedia] = useState(false);
  const [plan, setPlan] = useState<FormatPlan | null>(null);
  const [scriptText, setScriptText] = useState('');
  const [edits, setEdits] = useState(0);
  const [busy, setBusy] = useState<'' | 'plan' | 'render' | 'upload' | 'review'>('');
  const [error, setError] = useState('');
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [factsText, setFactsText] = useState('');
  const [gateSkips, setGateSkips] = useState<string[]>([]);
  const [seriesTemplate, setSeriesTemplate] = useState('');
  const [review, setReview] = useState<{ mode: string; issues: CraftIssue[]; keep_half_text?: string[]; llm_error?: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const selected = useMemo(
    () => formats.find((item) => item.id === formatId) ?? formats[0],
    [formats, formatId],
  );
  const selectedStyle = useMemo(
    () => selected?.styles.find((item) => item.id === styleId) ?? selected?.styles[0],
    [selected, styleId],
  );

  const loadFormats = useCallback((withMedia: boolean) => {
    if (USE_MOCK) return;
    studioApi.formats(withMedia)
      .then((response) => {
        const auto: StudioFormat = {
          id: 'auto', label: '自动', summary: '让 HEVI 按输入判断', example: '一句话也可以',
          sample_video: null, needs_media: false, gated: false, default_style: 'auto',
          styles: [], available: true, available_styles: [],
        };
        const items = [auto, ...response.formats.filter((item) => item.id !== 'auto')];
        setFormats(items);
      })
      .catch(() => setFormats(FALLBACK_FORMATS));
  }, []);

  useEffect(() => {
    if (!isAuthenticated()) { router.push('/login'); return; }
    loadFormats(false);
    const requested = new URLSearchParams(window.location.search).get('format');
    if (requested) setFormatId(requested);
  }, [loadFormats, router]);

  useEffect(() => {
    if (!selected) return;
    const availableStyles = selected.styles.filter((style) => selected.available_styles.includes(style.id));
    const preferred = availableStyles.find((style) => style.id === selected.default_style) ?? availableStyles[0];
    setStyleId(preferred?.id ?? '');
  }, [selected]);

  const track = useCallback(
    (event: FormatEvent, detail?: Record<string, unknown>, format?: string, style?: string) => {
      if (USE_MOCK) return;
      void studioApi.recordFormatEvent({
        event,
        format: format ?? (formatId === 'auto' ? 'auto' : formatId),
        style: style ?? selectedStyle?.id ?? '',
        detail,
      }).catch(() => undefined);
    },
    [formatId, selectedStyle],
  );

  const chooseFormat = (item: StudioFormat) => {
    if (!item.available) {
      setError(item.gated_reason || '该出品形式即将开放');
      if (!USE_MOCK) {
        void studioApi.recordFormatEvent({ event: 'gated_click', format: item.id }).catch(() => undefined);
      }
      return;
    }
    const nextStyle = item.available_styles.includes(item.default_style)
      ? item.default_style
      : item.available_styles[0] ?? '';
    if (formatId === 'auto' && item.id !== 'auto') {
      void studioApi.recordFormatEvent({
        event: 'auto_changed',
        format: item.id,
        style: nextStyle,
        detail: { from: 'auto', to: item.id },
      }).catch(() => undefined);
    }
    setError('');
    setResult(null);
    setPlan(null);
    setFormatId(item.id);
    track('format_selected', undefined, item.id, nextStyle);
  };

  const onDrop = async (event: React.DragEvent) => {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (!file) return;
    setBusy('upload');
    setError('');
    try {
      if (file.type.startsWith('video/')) {
        const uploaded = await studioApi.uploadSource(file);
        setMediaPath(uploaded.media_path);
        setHasMedia(true);
        loadFormats(true);
      } else if (file.type.startsWith('image/')) {
        const { canvasApi } = await import('@/lib/api-client');
        const uploaded = await canvasApi.uploadReferenceImage(file);
        setImagePath(uploaded.path);
      } else {
        setError('只支持视频或图片素材');
      }
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy('');
    }
  };

  const parseFacts = (raw: string) =>
    raw
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const parts = line.split(/[|｜]/);
        return { claim: (parts[0] || '').trim(), source: parts.slice(1).join('|').trim() };
      });

  const skipGate = (gateId: string) => {
    if (!plan?.craft) return;
    const nextSkips = gateSkips.includes(gateId) ? gateSkips : [...gateSkips, gateId];
    setGateSkips(nextSkips);
    setPlan({
      ...plan,
      craft: {
        ...plan.craft,
        gates: plan.craft.gates.map((gate) =>
          gate.id === gateId ? { ...gate, status: 'skipped', detail: '熟练用户一键跳过；审稿记录会保留。' } : gate,
        ),
      },
    });
    if (!USE_MOCK) {
      void studioApi.craftEvent({
        event: 'gate_skip', plan_id: plan.craft.plan_id, format: plan.craft.format, style: plan.craft.style, gate: gateId,
      }).catch(() => undefined);
    }
  };

  const runReview = async () => {
    if (!plan) return;
    setBusy('review');
    setError('');
    try {
      const data = await studioApi.craftReview({
        target: 'script',
        topic: plan.title || topic.trim(),
        lines: scriptText.split('\n').map((line) => line.trim()).filter(Boolean),
        shots: plan.shots as unknown as Array<Record<string, unknown>>,
        facts: parseFacts(factsText),
        skipped_gates: gateSkips,
        allow_llm: true,
      });
      setReview(data);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy('');
    }
  };

  const makePlan = async () => {
    if (!topic.trim()) { setError('先写一句主题或梗概'); return; }
    setBusy('plan');
    setError('');
    setResult(null);
    try {
      const body = {
        format: formatId,
        style: selectedStyle?.id,
        topic: topic.trim(),
        slots: {
          ...(mediaPath ? { media_path: mediaPath } : {}),
          ...(imagePath ? { image_path: imagePath } : {}),
        },
      };
      const next = await studioApi.planFormat({
        ...body,
        facts: parseFacts(factsText),
        skip_gates: gateSkips,
        series_template: seriesTemplate || undefined,
      });
      setPlan(next);
      setScriptText(next.script.lines.join('\n'));
      setEdits(0);
      setReview(null);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy('');
    }
  };

  const render = async () => {
    if (!plan) return;
    if (edits > 0) track('storyboard_edited', { count: edits });
    setBusy('render');
    setError('');
    try {
      const output = await studioApi.createFormatSlate({
        format: plan.format,
        style: plan.style,
        slots: {
          topic: plan.title || topic.trim(),
          source_text: scriptText,
          ...(mediaPath ? { media_path: mediaPath } : {}),
          ...(imagePath ? { image_path: imagePath } : {}),
        },
      });
      setResult(output);
    } catch (err) {
      setError(formatError(err));
    } finally {
      setBusy('');
    }
  };

  const onScriptChange = (value: string) => {
    setScriptText(value);
    if (plan) {
      const original = plan.script.lines.join('\n');
      if (value !== original) setEdits((n) => (n === 0 ? 1 : n + 1));
    }
  };

  const downloadUrl = typeof result?.download_url === 'string' ? result.download_url : '';
  const status = typeof result?.status === 'string' ? result.status : '';

  return (
    <div className="create-entry" onDragOver={(e) => e.preventDefault()} onDrop={onDrop}>
      <section className="create-entry__hero">
        <p className="create-entry__eyebrow">HEVI 创作</p>
        <h1>先选一种出品形式，再开始</h1>
        <p className="create-entry__sub">写一句想法，或把素材拖进来。选了形式，流水线与自检规则就锁定，不再自动猜。</p>
      </section>

      <section className="create-entry__input">
        <textarea
          aria-label="创作输入"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder="例如：用 60 秒讲清楚复利为什么反直觉。也可以把视频拖到这里。"
          rows={3}
        />
        <div className="create-entry__input-actions">
          <button type="button" className="create-entry__ghost" onClick={() => fileRef.current?.click()}>
            {busy === 'upload' ? '上传中…' : '添加素材'}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="video/*,image/*"
            hidden
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              const fake = { preventDefault() {}, dataTransfer: { files: [file] } } as unknown as React.DragEvent;
              await onDrop(fake);
            }}
          />
          {(mediaPath || imagePath) && (
            <span className="create-entry__media">已附素材：{mediaPath ? '视频' : '图片'}</span>
          )}
        </div>
      </section>

      <section className="create-entry__formats" aria-label="出品形式">
        {formats.map((item) => {
          const active = item.id === formatId;
          const disabled = !item.available;
          return (
            <button
              key={item.id}
              type="button"
              className={`create-entry__card${active ? ' is-active' : ''}${disabled ? ' is-gated' : ''}`}
              onClick={() => chooseFormat(item)}
              aria-pressed={active}
              data-format={item.id}
            >
              <span className="create-entry__card-media">
                {item.sample_video
                  ? <video src={item.sample_video} muted loop autoPlay playsInline />
                  : <span className="create-entry__card-poster" aria-hidden>{item.label.slice(0, 2)}</span>}
              </span>
              <span className="create-entry__card-title">
                {item.label}
                {disabled && <em>即将开放</em>}
              </span>
              <span className="create-entry__card-summary">{item.summary}</span>
              <span className="create-entry__card-example">{item.example}</span>
            </button>
          );
        })}
      </section>

      {selected && selected.styles.length > 1 && (
        <section className="create-entry__styles" aria-label="子风格">
          <span className="create-entry__label">子风格</span>
          {selected.styles.map((style) => {
            const available = selected.available_styles.includes(style.id);
            return (
              <button
                key={style.id}
                type="button"
                className={`create-entry__chip${style.id === selectedStyle?.id ? ' is-active' : ''}${available ? '' : ' is-gated'}`}
                onClick={() => { if (available) setStyleId(style.id); }}
                title={style.hint}
              >
                {style.label}{available ? '' : ' · 即将开放'}
              </button>
            );
          })}
        </section>
      )}

      <section className="create-entry__facts">
        <label className="create-entry__label" htmlFor="craft-facts">
          事实与出处（每行一条：事实｜出处；数字没有出处会被自检标红，查不到就删）
        </label>
        <textarea
          id="craft-facts"
          value={factsText}
          onChange={(e) => setFactsText(e.target.value)}
          placeholder="例如：蓝光波长约 450 纳米｜物理教材第 3 章"
          rows={2}
        />
        <small>公测期零付费：这些出处只用于自检，不会联网核对。</small>
      </section>

      {error && <div className="create-entry__notice is-error" role="alert">{error}</div>}

      <section className="create-entry__actions">
        <button type="button" className="create-entry__primary" onClick={makePlan} disabled={busy !== '' || !topic.trim()}>
          {busy === 'plan' ? '正在出脚本与分镜…' : '生成脚本与分镜'}
        </button>
        <span className="create-entry__hint">确认分镜后再渲染，单格可以改。</span>
      </section>

      {plan && (
        <section className="create-entry__plan">
          <header>
            <div>
              <p className="create-entry__label">分镜确认</p>
              <h2>{plan.title}</h2>
            </div>
            <button type="button" className="create-entry__primary" onClick={render} disabled={busy !== ''}>
              {busy === 'render' ? '渲染中…' : '确认并渲染'}
            </button>
          </header>
          <label className="create-entry__script">
            <span>脚本（可直接改）</span>
            <textarea
              value={scriptText}
              onChange={(e) => onScriptChange(e.target.value)}
              rows={Math.max(4, plan.script.lines.length + 1)}
            />
          </label>
          <div className="create-entry__shots">
            {plan.shots.map((shot) => {
              const craftShot = plan.craft?.shots.find((item) => item.index === shot.index);
              return (
                <article key={shot.index} className="create-entry__shot">
                  <span className="create-entry__shot-index">{shot.index}</span>
                  <strong>{shot.label}</strong>
                  <p>{shot.line}</p>
                  <small>{shot.duration_s}s · 关键帧：{shot.keyframe_prompt}</small>
                  {craftShot && (
                    <div className="create-entry__shot-route">
                      <span data-route={craftShot.route}>{craftShot.route_label}</span>
                      <em>{craftShot.model || '本地'} · ¥{craftShot.cost_cny.toFixed(2)} · 约 {craftShot.render_s_est}s</em>
                    </div>
                  )}
                </article>
              );
            })}
          </div>

          {plan.craft && (
            <div className="create-entry__craft">
              <div className="create-entry__craft-budget">
                <strong>{plan.craft.budget.quote}</strong>
                <small>{plan.craft.budget.disclaimer}</small>
              </div>

              {plan.craft.series_templates.length > 0 && (
                <div className="create-entry__craft-row">
                  <span className="create-entry__label">栏目模板</span>
                  {plan.craft.series_templates.map((template) => {
                    const id = String(template.id);
                    return (
                      <button
                        key={id}
                        type="button"
                        className={`create-entry__chip${seriesTemplate === id ? ' is-active' : ''}`}
                        onClick={() => setSeriesTemplate(id)}
                        title={String(template.speedup || '')}
                      >
                        {String(template.label || id)}
                      </button>
                    );
                  })}
                  {seriesTemplate && <small>重新生成计划后套用；只换标题、比喻、标签。</small>}
                </div>
              )}

              <div className="create-entry__craft-block">
                <p className="create-entry__label">阶段闸门（可一键跳过，跳过会进审稿记录）</p>
                <ol className="create-entry__gates">
                  {plan.craft.gates.map((gate) => (
                    <li key={gate.id} data-status={gate.status}>
                      <div>
                        <strong>{gate.label}</strong>
                        <small>{gate.require}</small>
                        {gate.status === 'skipped' && <em>已跳过</em>}
                        {gate.status === 'done' && <em>已完成</em>}
                      </div>
                      {gate.skippable && gate.status === 'pending' && (
                        <button type="button" className="create-entry__ghost" onClick={() => skipGate(gate.id)}>
                          跳过
                        </button>
                      )}
                    </li>
                  ))}
                </ol>
              </div>

              <div className="create-entry__craft-block">
                <p className="create-entry__label">
                  规则自检 · 红 {plan.craft.rules.counts.fail} / 黄 {plan.craft.rules.counts.warn}
                </p>
                <p className="create-entry__craft-policy">{plan.craft.rules.text_policy}</p>
                {plan.craft.rules.issues.length === 0
                  ? <small>没有发现问题。</small>
                  : (
                    <ul className="create-entry__issues">
                      {plan.craft.rules.issues.map((issue, index) => (
                        <li key={`${issue.rule}-${index}`} data-level={issue.level}>
                          <span>{issue.level === 'fail' ? '红' : issue.level === 'warn' ? '黄' : '提示'}</span>
                          {issue.message}
                          {issue.fix && <em> → {issue.fix}</em>}
                        </li>
                      ))}
                    </ul>
                  )}
              </div>

              <div className="create-entry__craft-grid">
                <div className="create-entry__craft-block">
                  <p className="create-entry__label">声音</p>
                  <small>
                    {plan.craft.sound.strategy === 'music_first_beat_cut' ? '先定整首配乐，再按拍点剪' : '旁白先行，配乐避让'}
                    · {plan.craft.sound.bpm} BPM · 前 1 秒必须有声 · 淡出到黑场 · 无 BGM 版
                  </small>
                  <ul>
                    {plan.craft.sound.checks.map((check) => (
                      <li key={check.id}>{check.label}</li>
                    ))}
                  </ul>
                </div>
                <div className="create-entry__craft-block">
                  <p className="create-entry__label">标题 3 候选</p>
                  <ul>
                    {plan.craft.titles.map((title) => (
                      <li key={title.title}><strong>{title.title}</strong><small>{title.gain}</small></li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="create-entry__craft-block">
                <p className="create-entry__label">封面（单独生成，不截帧）</p>
                <small>{plan.craft.cover.prompt}</small>
              </div>

              <div className="create-entry__craft-block">
                <p className="create-entry__label">许可风险</p>
                <small>{plan.craft.license.policy}</small>
                <div className="create-entry__craft-row">
                  {plan.craft.license.high_risk.map((item) => (
                    <span key={item} className="create-entry__risk">{item}</span>
                  ))}
                </div>
              </div>

              <div className="create-entry__craft-row">
                <button type="button" className="create-entry__ghost" onClick={runReview} disabled={busy !== ''}>
                  {busy === 'review' ? '独立审稿中…' : '独立审稿（只列问题）'}
                </button>
                {review && <small>{review.mode === 'llm' ? 'LLM 独立审稿' : '离线规则审稿'}{review.llm_error ? ` · ${review.llm_error}` : ''}</small>}
              </div>
              {review && (
                <div className="create-entry__craft-block">
                  <ul className="create-entry__issues">
                    {review.issues.length === 0 && <li data-level="info"><span>提示</span>没有发现问题。</li>}
                    {review.issues.map((issue, index) => (
                      <li key={`review-${index}`} data-level={issue.dimension === 'fact' ? 'fail' : 'warn'}>
                        <span>{issue.dimension || '问题'}</span>{issue.message}{issue.fix && <em> → {issue.fix}</em>}
                      </li>
                    ))}
                  </ul>
                  {review.keep_half_text && review.keep_half_text.length > 0 && (
                    <small>只能留一半时，保留：{review.keep_half_text.join(' / ')}</small>
                  )}
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {result && (
        <section className="create-entry__result">
          <h2>渲染结果：{status || '已提交'}</h2>
          {downloadUrl
            ? <a className="create-entry__primary" href={downloadUrl} download>下载成片</a>
            : <p>任务已提交。可到「项目」查看进度；完成后再下载。</p>}
          <a className="create-entry__ghost" href="/canvas">在画布中查看/改单格 →</a>
        </section>
      )}
    </div>
  );
}
