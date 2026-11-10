'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { authedBlob, studioApi } from '@/lib/api-client';

type Json = Record<string, unknown>;
const obj = (v: unknown): Json => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const text = (v: unknown): string => (typeof v === 'string' ? v : '');
const num = (v: unknown): number => (typeof v === 'number' ? v : 0);

type Style = { id: string; name: string; family: string; medium: string; hero: string; draw_film: string; status?: string; score?: number; reason?: string };
type Family = { family: string; styles: Style[] };

const playable = ['lofiElectronic', 'cinematic', 'folk', 'musicBox'] as const;

export function AnidoodleStudio() {
  const [families, setFamilies] = useState<Family[]>([]);
  const [selected, setSelected] = useState('lighthouse');
  const [topic, setTopic] = useState('灯塔为什么建在礁石上');
  const [intent, setIntent] = useState('explainer');
  const [recommendation, setRecommendation] = useState<Json | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [still, setStill] = useState<Json | null>(null);
  const [clip, setClip] = useState<Json | null>(null);
  const [music, setMusic] = useState<Json | null>(null);
  const [musicStyle, setMusicStyle] = useState<string>('lofiElectronic');
  const [bars, setBars] = useState(12);
  const [seed, setSeed] = useState(29);
  const [engine, setEngine] = useState<Json | null>(null);
  const imageUrl = useRef<string>('');
  const videoUrl = useRef<string>('');
  const audioUrl = useRef<string>('');
  const [imageSrc, setImageSrc] = useState('');
  const [videoSrc, setVideoSrc] = useState('');
  const [audioSrc, setAudioSrc] = useState('');

  const styleIndex = useMemo(() => {
    const map = new Map<string, Style>();
    families.forEach((group) => group.styles.forEach((style) => map.set(style.id, style)));
    return map;
  }, [families]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const data = await studioApi.anidoodleStyles();
        if (!alive) return;
        setFamilies(arr(data.families) as Family[]);
        const recommended = obj(data.recommendation);
        if (recommended.style) setRecommendation(recommended);
        try {
          const info = await studioApi.anidoodleEngine();
          if (alive) setEngine(info);
        } catch {
          /* engine status is optional in the header */
        }
      } catch (err) {
        if (alive) setError(err instanceof Error ? err.message : '风格库加载失败');
      }
    })();
    return () => {
      alive = false;
      if (imageUrl.current) URL.revokeObjectURL(imageUrl.current);
      if (videoUrl.current) URL.revokeObjectURL(videoUrl.current);
      if (audioUrl.current) URL.revokeObjectURL(audioUrl.current);
    };
  }, []);

  async function fetchInto(url: string, set: (value: string) => void, slot: { current: string }) {
    const blob = await authedBlob(url);
    if (slot.current) URL.revokeObjectURL(slot.current);
    const next = URL.createObjectURL(blob);
    slot.current = next;
    set(next);
  }

  async function recommend() {
    setBusy('recommend');
    setError('');
    try {
      const result = await studioApi.anidoodleRecommend({ topic, intent });
      setRecommendation(result);
      const style = obj(result.style);
      if (text(style.id)) setSelected(text(style.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : '推荐失败');
    } finally {
      setBusy('');
    }
  }

  async function renderStill(styleId = selected) {
    setBusy('still');
    setError('');
    try {
      const result = await studioApi.anidoodleStill({ style_id: styleId, scale: 1 });
      setStill(result);
      const file = obj(result.file);
      if (text(file.url)) await fetchInto(text(file.url), setImageSrc, imageUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : '成图失败');
    } finally {
      setBusy('');
    }
  }

  async function renderDraw(styleId = selected) {
    setBusy('draw');
    setError('');
    setClip(null);
    try {
      const result = await studioApi.anidoodleDraw({ style_id: styleId, gates: true });
      setClip(result);
      const file = obj(result.file);
      if (text(file.url)) await fetchInto(text(file.url), setVideoSrc, videoUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : '绘制过程渲染失败');
    } finally {
      setBusy('');
    }
  }

  async function renderMusic() {
    setBusy('music');
    setError('');
    try {
      const result = await studioApi.anidoodleMusic({ style: musicStyle, bars, seed, format: 'mp3' });
      setMusic(result);
      const file = obj(result.file);
      if (text(file.url)) await fetchInto(text(file.url), setAudioSrc, audioUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : '作曲失败');
    } finally {
      setBusy('');
    }
  }

  const current = styleIndex.get(selected);
  const recStyle = obj(recommendation?.style);
  const gate = obj(clip?.gate);
  const verify = obj(clip?.verify_export);
  const check = obj(music?.check);
  const attribution = obj(obj(engine).engine);

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">手绘代码风格库 · S29</h1>
        <p className="text-sm text-neutral-600">
          32 种用手绘语法写出来的风格：每一种都在代码里按该媒介的顺序画，成图与绘制过程同源、可复现。
          这是「代码绘制」，与 handraw-style 的「生图提示风格」是两套库。
        </p>
        {text(attribution.node) ? (
          <p className="text-xs text-neutral-500">
            代码绘制引擎已就绪 · Node {num(attribution.node_major)} · Chromium（playwright 后端）
          </p>
        ) : null}
      </header>

      {error ? <p className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p> : null}

      <section className="space-y-3 rounded-lg border p-4">
        <div className="grid gap-3 md:grid-cols-[2fr_1fr_auto]">
          <label className="text-sm">
            主题
            <input className="mt-1 w-full rounded border px-3 py-2" value={topic} onChange={(event) => setTopic(event.target.value)} />
          </label>
          <label className="text-sm">
            用途
            <select className="mt-1 w-full rounded border px-3 py-2" value={intent} onChange={(event) => setIntent(event.target.value)}>
              <option value="explainer">知识讲解</option>
              <option value="story">故事 / 绘本</option>
              <option value="brand">品牌 / 产品</option>
              <option value="education">课堂</option>
              <option value="editorial">编辑插图</option>
            </select>
          </label>
          <button type="button" className="self-end rounded bg-neutral-900 px-4 py-2 text-sm text-white disabled:opacity-50" disabled={busy === 'recommend'} onClick={recommend}>
            {busy === 'recommend' ? '推荐中…' : '自动推荐'}
          </button>
        </div>
        {recommendation && text(recStyle.id) ? (
          <div className="rounded border border-emerald-200 bg-emerald-50 p-3 text-sm">
            <div className="font-medium">
              推荐：{text(recStyle.name)}（{text(recStyle.family)}）
            </div>
            <div>{text(recommendation.reason)}</div>
            <div className="mt-1 text-neutral-600">
              备选：{arr(recommendation.alternatives).map((item) => text(obj(item).name)).filter(Boolean).join('、')}
            </div>
            <button type="button" className="mt-2 rounded border px-3 py-1" onClick={() => setSelected(text(recStyle.id))}>
              选中这个风格
            </button>
          </div>
        ) : null}
      </section>

      <section className="grid gap-4 md:grid-cols-[1.1fr_1fr]">
        <div className="space-y-4 rounded-lg border p-4">
          <h2 className="font-medium">按媒介分组</h2>
          <div className="max-h-[520px] space-y-4 overflow-auto pr-1">
            {families.map((group) => (
              <div key={group.family}>
                <div className="mb-1 text-xs uppercase tracking-wide text-neutral-500">{group.family}</div>
                <div className="flex flex-wrap gap-1">
                  {group.styles.map((style) => (
                    <button
                      key={style.id}
                      type="button"
                      title={style.hero}
                      className={`rounded border px-2 py-1 text-xs ${selected === style.id ? 'border-neutral-900 bg-neutral-900 text-white' : 'hover:bg-neutral-100'}`}
                      onClick={() => setSelected(style.id)}
                    >
                      {style.name}
                      {style.status === 'public' ? '' : ' · admin'}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-4 rounded-lg border p-4">
          <h2 className="font-medium">当前风格</h2>
          {current ? (
            <div className="space-y-1 text-sm">
              <div className="text-lg font-medium">{current.name}</div>
              <div className="text-neutral-600">{current.family} · {current.hero}</div>
              <p className="text-neutral-600">{current.medium}</p>
              <p className="text-xs text-neutral-500">绘制过程片：{current.draw_film}</p>
              <p className={`text-xs ${current.status === 'public' ? 'text-emerald-700' : 'text-amber-700'}`}>
                {current.status === 'public'
                  ? `已通过黑盒（${current.score}/5）：${current.reason}`
                  : `仅管理员：${current.reason}`}
              </p>
            </div>
          ) : (
            <p className="text-sm text-neutral-600">从左侧选择一个风格。</p>
          )}
          <div className="flex flex-wrap gap-2">
            <button type="button" className="rounded border px-3 py-2 text-sm disabled:opacity-50" disabled={busy === 'still' || current?.status !== 'public'} onClick={() => renderStill()}>
              {busy === 'still' ? '画成图中…' : '看成图'}
            </button>
            <button type="button" className="rounded border px-3 py-2 text-sm disabled:opacity-50" disabled={busy === 'draw' || current?.status !== 'public'} onClick={() => renderDraw()}>
              {busy === 'draw' ? '渲染绘制过程…' : '看绘制过程片'}
            </button>
          </div>

          {imageSrc ? <img src={imageSrc} alt={`${current?.name || selected} 成图`} className="w-full rounded border" /> : null}
          {still ? (
            <p className="text-xs text-neutral-500">
              {num(still.width)}×{num(still.height)} · frame {num(still.frame)} · md5 {text(still.md5)} · {still.reproducible ? '可复现' : '未确认可复现'} · {still.cached ? '缓存命中' : '新渲染'}
            </p>
          ) : null}
          {videoSrc ? <video src={videoSrc} controls className="w-full rounded border" /> : null}
          {clip ? (
            <div className="space-y-1 text-xs text-neutral-600">
              <div>
                {num(clip.width)}×{num(clip.height)} · {num(clip.duration_s)}s · 确定性 {text(clip.determinism)}
              </div>
              <div className={gate.ok ? 'text-emerald-700' : 'text-red-700'}>
                gate {text(gate.verdict)}（{text(gate.passed_count)}） · verify {text(verify.verdict)}（{text(verify.passed_count)}）
              </div>
              <div className="break-all">sha256 {text(clip.sha256)}</div>
            </div>
          ) : null}
        </div>
      </section>

      <section className="space-y-3 rounded-lg border p-4">
        <h2 className="font-medium">代码作曲（无授权风险的 BGM）</h2>
        <p className="text-sm text-neutral-600">
          音符写成数据，引擎合成；不下载音色包、不用录音。引擎自检调式、响度、掩蔽、分轨与 novelty。
        </p>
        <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto_auto]">
          <label className="text-sm">
            曲风
            <select className="mt-1 w-full rounded border px-3 py-2" value={musicStyle} onChange={(event) => setMusicStyle(event.target.value)}>
              {playable.map((id) => (
                <option key={id} value={id}>{id}</option>
              ))}
            </select>
          </label>
          <label className="text-sm">
            长度（小节，每小节约 3 秒）
            <input type="number" min={6} max={96} className="mt-1 w-full rounded border px-3 py-2" value={bars} onChange={(event) => setBars(Number(event.target.value) || 12)} />
          </label>
          <label className="text-sm">
            种子
            <input type="number" min={0} className="mt-1 w-full rounded border px-3 py-2" value={seed} onChange={(event) => setSeed(Number(event.target.value) || 0)} />
          </label>
          <button type="button" className="self-end rounded border px-3 py-2 text-sm disabled:opacity-50" disabled={busy === 'music'} onClick={renderMusic}>
            {busy === 'music' ? '作曲中…' : '生成 BGM'}
          </button>
        </div>
        {audioSrc ? <audio src={audioSrc} controls className="w-full" /> : null}
        {music ? (
          <div className="space-y-1 text-xs text-neutral-600">
            <div className={check.verdict === 'pass' ? 'text-emerald-700' : 'text-red-700'}>
              check {text(check.verdict)} · {text(check.lufs)} LUFS · true peak {text(check.true_peak_dbtp)} dBTP
            </div>
            <div>{text(check.guards)}</div>
            <div>stems {text(check.stems)} · novelty {text(check.novelty)}</div>
          </div>
        ) : null}
      </section>

      <section className="space-y-2 rounded-lg border p-4 text-sm">
        <h2 className="font-medium">许可与使用</h2>
        <p>
          风格引擎来自 anidoodle（作者 Alex Greenshpun，Apache-2.0，仓库
          <a className="underline" href="https://github.com/alexgreensh/anidoodle" target="_blank" rel="noopener noreferrer"> anidoodle</a>）。
          HEVI 保留 LICENSE 与 NOTICE，修改过的文件在 <code>THIRD_PARTY_NOTICES.md</code> 标明。
        </p>
        <p className="text-neutral-600">
          「匹配参考图」只接受用户自己拥有权利的图片，并在界面提示；不做照片转真人写真。上游示例片、README 图片与音色包不作为 HEVI 示例或默认内容。
        </p>
      </section>
    </div>
  );
}
