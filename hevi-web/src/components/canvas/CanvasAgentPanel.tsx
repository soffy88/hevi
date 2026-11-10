/**
 * CanvasAgentPanel — S25 对话建画布 / 模板库。
 *
 * 一句话 → 方案（节点/连线/逐节点报价/待确认）→ 确认建图；确认后可改单个节点
 * （只重算该节点与报价，不改其它节点）；模板页可把带版本的模板换成自己的素材。
 *
 * 所有请求走 `/api/canvas/s25/*`，不在这里拼提示词或算钱。
 */
'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  canvasS25Api, studioApi,
  type CanvasPlan, type CanvasTemplate, type StudioFormat,
} from '@/lib/api-client';

export interface CanvasAgentPanelProps {
  open: boolean;
  onClose: () => void;
  onCreated: (graphId: string) => void;
  onFlash: (msg: string) => void;
}

type Tab = 'agent' | 'templates';

export function CanvasAgentPanel({ open, onClose, onCreated, onFlash }: CanvasAgentPanelProps) {
  const [tab, setTab] = useState<Tab>('agent');
  const [prompt, setPrompt] = useState('');
  const [format, setFormat] = useState('');
  const [formats, setFormats] = useState<StudioFormat[]>([]);
  const [useLlm, setUseLlm] = useState(false);
  const [plan, setPlan] = useState<CanvasPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [applied, setApplied] = useState<string>('');
  const [editKey, setEditKey] = useState('');
  const [editPrompt, setEditPrompt] = useState('');
  const [editSeconds, setEditSeconds] = useState('');
  const [templates, setTemplates] = useState<CanvasTemplate[]>([]);
  const [templateBusy, setTemplateBusy] = useState('');

  useEffect(() => {
    if (!open || formats.length) return;
    void studioApi.formats().then((r) => setFormats(r.formats)).catch(() => setFormats([]));
  }, [open, formats.length]);

  const loadTemplates = useCallback(async () => {
    try {
      const r = await canvasS25Api.templates();
      setTemplates(r.templates);
    } catch (err) {
      onFlash(err instanceof Error ? err.message : '模板加载失败');
    }
  }, [onFlash]);

  useEffect(() => {
    if (open && tab === 'templates' && templates.length === 0) void loadTemplates();
  }, [open, tab, templates.length, loadTemplates]);

  const build = async () => {
    const text = prompt.trim();
    if (!text) { setError('先写一句你想做什么'); return; }
    setBusy(true); setError(''); setApplied('');
    try {
      const r = await canvasS25Api.plan({
        prompt: text,
        format: format || undefined,
        use_llm: useLlm,
      });
      setPlan(r.plan);
      if (r.script_source === 'offline' && useLlm) onFlash('文本模型不可用，已用离线脚本生成方案');
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成方案失败');
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!plan) return;
    setBusy(true); setError('');
    try {
      const r = await canvasS25Api.applyPlan({
        plan,
        confirm_token: plan.confirm_token,
        save: true,
      });
      const gid = String(r.graph_id ?? '');
      if (!gid) throw new Error('后端没有返回 graph_id');
      setApplied(gid);
      onFlash(`已建画布：${plan.numbers.nodes} 节点 / ${plan.numbers.edges} 连线`);
      onCreated(gid);
    } catch (err) {
      setError(err instanceof Error ? err.message : '建图失败');
    } finally {
      setBusy(false);
    }
  };

  const startEdit = (key: string) => {
    const node = plan?.nodes.find((n) => n.key === key);
    if (!node) return;
    setEditKey(key);
    setEditPrompt(String(node.config?.prompt ?? node.config?.content ?? ''));
    setEditSeconds(String(node.config?.duration_s ?? ''));
  };

  const saveEdit = async () => {
    if (!plan || !editKey) return;
    setBusy(true); setError('');
    const config: Record<string, unknown> = { prompt: editPrompt };
    if (editSeconds.trim()) config.duration_s = Number(editSeconds);
    try {
      const r = await canvasS25Api.patchPlan(plan, editKey, { config });
      setPlan(r.plan);
      setEditKey('');
      onFlash('已更新该节点与报价');
    } catch (err) {
      setError(err instanceof Error ? err.message : '改节点失败');
    } finally {
      setBusy(false);
    }
  };

  const useTemplate = async (tpl: CanvasTemplate) => {
    setTemplateBusy(tpl.id);
    try {
      const r = await canvasS25Api.applyTemplate(tpl.id, {
        version: tpl.current_version ?? tpl.version ?? 1,
        save: true,
      });
      const gid = String(r.graph_id ?? '');
      if (!gid) throw new Error('后端没有返回 graph_id');
      onFlash(`已从模板建画布：${tpl.name} v${r.template_version}`);
      onCreated(gid);
    } catch (err) {
      onFlash(err instanceof Error ? err.message : '模板应用失败');
    } finally {
      setTemplateBusy('');
    }
  };

  if (!open) return null;

  return (
    <aside className="hevi-agent" aria-label="对话建画布">
      <div className="hevi-agent__head">
        <div className="hevi-agent__tabs">
          <button type="button" data-active={tab === 'agent' ? 'true' : undefined}
            onClick={() => setTab('agent')}>对话建画布</button>
          <button type="button" data-active={tab === 'templates' ? 'true' : undefined}
            onClick={() => setTab('templates')}>模板</button>
        </div>
        <button type="button" className="hevi-agent__close" onClick={onClose} aria-label="关闭">×</button>
      </div>

      {tab === 'agent' && (
        <div className="hevi-agent__body">
          <label className="hevi-agent__label" htmlFor="s25-prompt">你想做什么</label>
          <textarea
            id="s25-prompt"
            className="hevi-agent__input"
            rows={4}
            value={prompt}
            placeholder="例：用 60 秒讲清楚复利为什么反直觉"
            onChange={(e) => setPrompt(e.target.value)}
          />
          <div className="hevi-agent__row">
            <select
              className="hevi-agent__select"
              value={format}
              onChange={(e) => setFormat(e.target.value)}
              aria-label="出品形式"
            >
              <option value="">自动判断形式</option>
              {formats.map((f) => (
                <option key={f.id} value={f.id} disabled={f.gated && !f.available}>
                  {f.label}{f.gated && !f.available ? '（即将开放）' : ''}
                </option>
              ))}
            </select>
            <label className="hevi-agent__check" title="会调用当前配置的文本模型；失败自动退回离线脚本">
              <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
              用文本模型写脚本
            </label>
          </div>
          <button type="button" className="hevi-topbar-btn hevi-topbar-btn--primary"
            onClick={() => void build()} disabled={busy}>
            {busy ? '生成中…' : '生成方案'}
          </button>

          {error && <p className="hevi-agent__error" role="alert">{error}</p>}

          {plan && (
            <div className="hevi-agent__plan">
              <div className="hevi-agent__plan-head">
                <strong>{plan.goal}</strong>
                <span>{plan.format} · {plan.style} · {plan.aspect}</span>
              </div>
              <div className="hevi-agent__numbers">
                {plan.numbers.nodes} 节点 · {plan.numbers.edges} 连线 · {plan.numbers.shots} 镜 ·{' '}
                {plan.numbers.seconds}s
              </div>
              <div className="hevi-agent__cost">
                预估 <strong>¥{plan.estimate.total_cny.toFixed(2)}</strong>
                {plan.estimate.unpriced_nodes > 0 && (
                  <span className="hevi-agent__muted">
                    {' '}· 另有 {plan.estimate.unpriced_nodes} 项未定价（图片按张/渠道另算）
                  </span>
                )}
              </div>

              <div className="hevi-agent__steps">
                {plan.steps.map((s) => (
                  <div key={s.id} className="hevi-agent__step" data-done={applied ? 'true' : undefined}>
                    <span className="hevi-agent__dot" aria-hidden />
                    <span>{s.label}</span>
                    <span className="hevi-agent__muted">{s.node_keys.length} 节点</span>
                  </div>
                ))}
              </div>

              <details className="hevi-agent__questions">
                <summary>待确认（{plan.questions.length}）</summary>
                <ul>
                  {plan.questions.map((q) => <li key={q.id}>{q.question}</li>)}
                </ul>
              </details>

              <details className="hevi-agent__nodes">
                <summary>节点与逐项费用（{plan.nodes.length}）</summary>
                <ul>
                  {plan.nodes.map((n) => {
                    const row = plan.estimate.per_node.find((r) => (r.key ?? r.node_id) === n.key);
                    return (
                      <li key={n.key}>
                        <div className="hevi-agent__node-row">
                          <span className="hevi-agent__node-label">{n.label}</span>
                          <span className="hevi-agent__muted">{n.node_type}</span>
                          <span>{row?.priced ? `¥${row.cny.toFixed(2)}` : '未定价'}</span>
                          <button type="button" className="hevi-agent__link"
                            onClick={() => startEdit(n.key)}>改</button>
                        </div>
                        {editKey === n.key && (
                          <div className="hevi-agent__edit">
                            <textarea
                              rows={3}
                              value={editPrompt}
                              onChange={(e) => setEditPrompt(e.target.value)}
                              aria-label="节点提示词"
                            />
                            <input
                              value={editSeconds}
                              onChange={(e) => setEditSeconds(e.target.value)}
                              placeholder="时长（秒，可空）"
                              aria-label="节点时长"
                            />
                            <div className="hevi-agent__row">
                              <button type="button" className="hevi-topbar-btn"
                                onClick={() => void saveEdit()} disabled={busy}>保存</button>
                              <button type="button" className="hevi-topbar-btn"
                                onClick={() => setEditKey('')}>取消</button>
                            </div>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </details>

              {applied ? (
                <p className="hevi-agent__done">已建画布 <code>{applied}</code>。可在画布上继续改单节点。</p>
              ) : (
                <button type="button" className="hevi-topbar-btn hevi-topbar-btn--primary"
                  onClick={() => void confirm()} disabled={busy}>
                  确认方案并建画布
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {tab === 'templates' && (
        <div className="hevi-agent__body">
          <p className="hevi-agent__muted">
            模板钉住版本；换素材/主题只改槽位，不改结构。
          </p>
          {templates.length === 0 && <p className="hevi-agent__muted">正在加载…</p>}
          <ul className="hevi-agent__templates">
            {templates.map((tpl) => (
              <li key={tpl.id}>
                <div className="hevi-agent__template-head">
                  <strong>{tpl.name}</strong>
                  <span className="hevi-agent__muted">
                    v{tpl.current_version ?? tpl.version ?? 1} · {tpl.format}
                    {tpl.builtin ? ' · 内置' : ''}
                  </span>
                </div>
                <div className="hevi-agent__template-meta">
                  {tpl.stats ? `${tpl.stats.nodes} 节点 / ${tpl.stats.edges} 连线` : ''}
                  {tpl.slots ? ` · ${tpl.slots.length} 个可替换槽位` : ''}
                </div>
                <button type="button" className="hevi-topbar-btn"
                  onClick={() => void useTemplate(tpl)} disabled={templateBusy === tpl.id}>
                  {templateBusy === tpl.id ? '创建中…' : '加入画布'}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}
