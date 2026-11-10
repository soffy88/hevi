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
import { studioApi, USE_MOCK, type FormatPlan, type StudioFormat } from '@/lib/api-client';

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
  const [busy, setBusy] = useState<'' | 'plan' | 'render' | 'upload'>('');
  const [error, setError] = useState('');
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const prevAutoRef = useRef<string | null>(null);

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

  const track = useCallback((event: FormatEvent, detail?: Record<string, unknown>) => {
    if (USE_MOCK) return;
    void studioApi.recordFormatEvent({
      event,
      format: formatId === 'auto' ? 'auto' : formatId,
      style: selectedStyle?.id ?? '',
      detail,
    }).catch(() => undefined);
  }, [formatId, selectedStyle]);

  const chooseFormat = (item: StudioFormat) => {
    if (!item.available) {
      setError(item.gated_reason || '该出品形式即将开放');
      if (!USE_MOCK) {
        void studioApi.recordFormatEvent({ event: 'gated_click', format: item.id }).catch(() => undefined);
      }
      return;
    }
    if (prevAutoRef.current && prevAutoRef.current !== item.id) {
      void studioApi.recordFormatEvent({
        event: 'auto_changed', format: item.id, detail: { from: prevAutoRef.current, to: item.id },
      }).catch(() => undefined);
      prevAutoRef.current = null;
    } else if (formatId === 'auto' && item.id !== 'auto') {
      prevAutoRef.current = 'auto';
    }
    setError('');
    setResult(null);
    setPlan(null);
    setFormatId(item.id);
    track('format_selected');
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
      const next = await studioApi.planFormat(body);
      setPlan(next);
      setScriptText(next.script.lines.join('\n'));
      setEdits(0);
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
            {plan.shots.map((shot) => (
              <article key={shot.index} className="create-entry__shot">
                <span className="create-entry__shot-index">{shot.index}</span>
                <strong>{shot.label}</strong>
                <p>{shot.line}</p>
                <small>{shot.duration_s}s · 关键帧：{shot.keyframe_prompt}</small>
              </article>
            ))}
          </div>
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
