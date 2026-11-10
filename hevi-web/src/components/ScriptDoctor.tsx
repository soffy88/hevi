'use client';

import { useState } from 'react';
import { studioApi } from '@/lib/api-client';

type Json = Record<string, unknown>;

const obj = (v: unknown): Json =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Json) : {};
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const text = (v: unknown): string => (typeof v === 'string' ? v : '');
const num = (v: unknown): number => (typeof v === 'number' ? v : 0);

function Findings({ items, title }: { items: unknown[]; title: string }) {
  if (!items.length) return <p className="text-sm text-emerald-700">{title}：无</p>;
  return (
    <div className="space-y-2">
      <h4 className="font-medium">{title}（{items.length}）</h4>
      {items.map((raw, index) => {
        const item = obj(raw);
        return (
          <div key={index} className="rounded border border-amber-200 bg-amber-50 p-3 text-sm">
            <div className="font-medium">
              {text(item.severity_label) || text(item.severity)} · {text(item.position) || text(item.ref)}
            </div>
            <div>{text(item.problem) || text(item.message)}</div>
            {text(item.audience) ? <div className="text-neutral-600">观众：{text(item.audience)}</div> : null}
            {text(item.fix) ? <div className="text-neutral-600">改法：{text(item.fix)}</div> : null}
          </div>
        );
      })}
    </div>
  );
}

export function ScriptDoctor() {
  const [topic, setTopic] = useState('离婚冷静期最后一天，她把公司公章缝进婚纱');
  const [genre, setGenre] = useState('');
  const [mode, setMode] = useState<'short_drama' | 'short_film'>('short_drama');
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [plan, setPlan] = useState<Json | null>(null);

  async function generate(nextConfirm = confirm) {
    if (!topic.trim()) {
      setError('先写一句主题或梗概');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const body = { topic, genre, confirm: nextConfirm };
      const result = mode === 'short_drama'
        ? await studioApi.scriptShortDrama(body)
        : await studioApi.scriptShortFilm(body);
      setPlan(result);
      setConfirm(nextConfirm);
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成失败');
    } finally {
      setBusy(false);
    }
  }

  const master = obj(plan?.master_plan);
  const gate = obj(plan?.gate);
  const premise = obj(plan?.premise_gate);
  const checks = obj(plan?.checks);
  const review = obj(plan?.review);
  const summary = obj(review.summary);
  const outline = arr(plan?.episode_outline);
  const beats = arr(plan?.ep1_beat_sheet);
  const seven = arr(master.seven_steps);
  const findings = arr(review.findings).filter((item) => text(obj(item).severity) === 'must');
  const should = arr(review.findings).filter((item) => text(obj(item).severity) === 'should');
  const script = obj(plan?.script);
  const scenes = arr(script.scenes);

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">剧本门诊 · S28</h1>
        <p className="text-sm text-neutral-600">
          出图前先把剧本问题解决：立项四槽、人物、因果、AI 可拍、短剧/短片结构、三轮审稿。
          只做文字，不调用付费模型。
        </p>
      </header>

      <section className="grid gap-3 rounded-lg border p-4 md:grid-cols-[2fr_1fr_1fr_auto]">
        <label className="text-sm">
          一句话主题/梗概
          <input
            className="mt-1 w-full rounded border px-3 py-2"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
          />
        </label>
        <label className="text-sm">
          类型（可选）
          <input
            className="mt-1 w-full rounded border px-3 py-2"
            value={genre}
            onChange={(event) => setGenre(event.target.value)}
            placeholder="都市复仇 / 家庭 / 悬疑"
          />
        </label>
        <label className="text-sm">
          模式
          <select
            className="mt-1 w-full rounded border px-3 py-2"
            value={mode}
            onChange={(event) => setMode(event.target.value as 'short_drama' | 'short_film')}
          >
            <option value="short_drama">连续短剧（10 集）</option>
            <option value="short_film">短片（5–8 分钟）</option>
          </select>
        </label>
        <button
          type="button"
          className="self-end rounded bg-neutral-900 px-4 py-2 text-white disabled:opacity-50"
          disabled={busy}
          onClick={() => generate(confirm)}
        >
          {busy ? '生成中…' : confirm ? '重新生成' : '先出总盘'}
        </button>
      </section>
      {error ? <p className="text-sm text-red-600">{error}</p> : null}

      {plan ? (
        <div className="space-y-6">
          <section className="grid gap-3 md:grid-cols-4">
            <div className="rounded border p-3">
              <div className="text-xs text-neutral-500">立项闸门</div>
              <div className="text-lg font-medium">{text(premise.verdict)}</div>
            </div>
            <div className="rounded border p-3">
              <div className="text-xs text-neutral-500">结构自检</div>
              <div className="text-lg font-medium">{checks.passed ? '通过' : `必须修 ${num(checks.must_count)}`}</div>
            </div>
            <div className="rounded border p-3">
              <div className="text-xs text-neutral-500">审稿</div>
              <div className="text-lg font-medium">
                必须修 {num(summary.must)} · 应该修 {num(summary.should)}
              </div>
            </div>
            <div className="rounded border p-3">
              <div className="text-xs text-neutral-500">确认</div>
              <div className="text-lg font-medium">{gate.confirmed ? '已确认' : '待确认'}</div>
            </div>
          </section>

          <section className="space-y-2 rounded border p-4">
            <h2 className="text-lg font-semibold">立项</h2>
            <p className="text-sm">{text(premise.one_line) || text(master.mainline)}</p>
            <p className="text-sm text-neutral-600">
              建议：{text(obj(premise.recommendation).mode)} · {text(obj(premise.recommendation).reason)}
            </p>
            {arr(premise.findings).map((raw, index) => (
              <p key={index} className="text-sm text-amber-700">
                {text(obj(raw).message)}
              </p>
            ))}
          </section>

          <section className="space-y-2 rounded border p-4">
            <h2 className="text-lg font-semibold">{mode === 'short_drama' ? '故事总盘' : '短片总盘'}</h2>
            <dl className="grid gap-2 text-sm md:grid-cols-2">
              <div><dt className="text-neutral-500">卖点</dt><dd>{text(master.sell_point) || text(master.door)}</dd></div>
              <div><dt className="text-neutral-500">核心钩子</dt><dd>{text(master.core_hook)}</dd></div>
              <div><dt className="text-neutral-500">主线</dt><dd>{text(master.mainline) || text(master.door)}</dd></div>
              <div><dt className="text-neutral-500">底牌</dt><dd>{text(master.trump_card) || text(master.subtext)}</dd></div>
              <div><dt className="text-neutral-500">结局</dt><dd>{text(master.ending)}</dd></div>
              <div><dt className="text-neutral-500">竖屏理由</dt><dd>{text(master.why_vertical)}</dd></div>
            </dl>
          </section>

          <section className="space-y-2 rounded border p-4">
            <h2 className="text-lg font-semibold">人物</h2>
            <div className="grid gap-3 md:grid-cols-2">
              {arr(plan.characters).map((raw, index) => {
                const person = obj(raw);
                return (
                  <div key={index} className="rounded border p-3 text-sm">
                    <div className="font-medium">{text(person.name)} · {text(person.role)}</div>
                    <div>缺陷：{text(person.defect)}</div>
                    <div>弧光：{text(person.arc)}</div>
                    <div>视觉标记：{arr(person.visual_markers).map(text).join('、')}</div>
                  </div>
                );
              })}
            </div>
          </section>

          {mode === 'short_drama' ? (
            <>
              <section className="space-y-2 rounded border p-4">
                <h2 className="text-lg font-semibold">10 集大纲</h2>
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead><tr className="border-b"><th>集</th><th>开头接什么</th><th>核心事件</th><th>爽点（结果）</th><th>卡点</th></tr></thead>
                    <tbody>
                      {outline.map((raw) => {
                        const row = obj(raw);
                        return (
                          <tr key={text(row.ep)} className="border-b align-top">
                            <td className="py-1">{text(row.ep)}</td>
                            <td className="py-1">{text(row.opening_connects)}</td>
                            <td className="py-1">{text(row.core_event)}</td>
                            <td className="py-1">{text(row.payoff)}</td>
                            <td className="py-1">{text(row.cliffhanger_type)}：{text(row.cliffhanger)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
              <section className="space-y-2 rounded border p-4">
                <h2 className="text-lg font-semibold">第 1 集秒级节拍</h2>
                <table className="w-full text-left text-sm">
                  <thead><tr className="border-b"><th>秒</th><th>模块</th><th>拍</th></tr></thead>
                  <tbody>
                    {beats.map((raw, index) => {
                      const row = obj(raw);
                      return (
                        <tr key={index} className="border-b align-top">
                          <td className="py-1">{num(row.start_s)}–{num(row.end_s)}s</td>
                          <td className="py-1">{text(row.module)}</td>
                          <td className="py-1">{text(row.beat)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </section>
            </>
          ) : (
            <>
              <section className="space-y-2 rounded border p-4">
                <h2 className="text-lg font-semibold">戏剧游戏 / 7 步</h2>
                <div className="grid gap-2 text-sm md:grid-cols-2">
                  {Object.entries(obj(master.dramatic_game)).map(([key, value]) => (
                    <div key={key}><span className="text-neutral-500">{key}：</span>{text(value)}</div>
                  ))}
                </div>
                <ol className="list-decimal space-y-1 pl-5 text-sm">
                  {seven.map((raw, index) => {
                    const step = obj(raw);
                    return <li key={index}>{text(step.label)}：{text(step.summary)}</li>;
                  })}
                </ol>
              </section>
              <section className="space-y-2 rounded border p-4">
                <h2 className="text-lg font-semibold">反转 / 母题</h2>
                {arr(master.reversals).map((raw, index) => {
                  const reversal = obj(raw);
                  return (
                    <p key={index} className="text-sm">
                      反转 {num(reversal.index)}（改{text(reversal.changes)}）：{text(reversal.summary)}
                    </p>
                  );
                })}
                <p className="text-sm">母题：{text(obj(master.motif).object)} × {num(obj(master.motif).count)} 次</p>
              </section>
            </>
          )}

          <section className="space-y-3 rounded border p-4">
            <h2 className="text-lg font-semibold">三轮审稿</h2>
            <Findings items={findings} title="必须修" />
            <Findings items={should} title="应该修" />
            <details>
              <summary className="cursor-pointer text-sm text-neutral-600">按轮次查看</summary>
              <div className="mt-2 space-y-2">
                {arr(review.rounds).map((raw, index) => {
                  const round = obj(raw);
                  return (
                    <div key={index} className="rounded border p-2 text-sm">
                      <div className="font-medium">{text(round.label)} · {text(round.focus)}</div>
                      <div>{arr(round.findings).length} 条</div>
                    </div>
                  );
                })}
              </div>
            </details>
          </section>

          <section className="space-y-2 rounded border p-4">
            <h2 className="text-lg font-semibold">剧本预览</h2>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded bg-neutral-50 p-3 text-xs">
              {[text(script.title), text(script.logline), '', ...scenes.flatMap((raw) => {
                const scene = obj(raw);
                return [
                  `## ${text(scene.scene_id)} ${text(scene.name)} [${text(scene.int_ext)}] [${text(scene.day_night)}]`,
                  ...arr(scene.beats).flatMap((beatRaw) => {
                    const beat = obj(beatRaw);
                    return [
                      ...arr(beat.action).map((line) => text(line)),
                      ...arr(beat.dialogue).map((lineRaw) => {
                        const line = obj(lineRaw);
                        const kind = text(line.kind) === 'inner' ? '（内心）' : text(line.kind) === 'vo' ? '（画外）' : '';
                        return `${text(line.speaker_name) || text(line.speaker)}${kind}：${text(line.text)}`;
                      }),
                      '',
                    ];
                  }),
                ];
              })].join('\n')}
            </pre>
          </section>

          {!confirm ? (
            <button
              type="button"
              className="rounded bg-emerald-700 px-4 py-2 text-white"
              onClick={() => generate(true)}
            >
              确认总盘，继续出大纲/剧本
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
