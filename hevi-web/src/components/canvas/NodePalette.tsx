/**
 * NodePalette — 媒体节点 + kit 工具 + 产线展开
 */
'use client';

import { useEffect, useState } from 'react';
import type { NodeType } from '@/types/api';
import { NODE_META } from '@/lib/canvas-rules';
import { studioApi, USE_MOCK, type StudioFormat } from '@/lib/api-client';

const TYPES: NodeType[] = ['text', 'image', 'video', 'audio', 'script', 'segment', 'asset'];

export type StudioTool = { id: string; kind: string; summary: string };
export type StudioLine = {
  id: string;
  product: string;
  summary: string;
  tools: string[];
  availability?: 'ga' | 'internal';
};

export function NodePalette({
  onAdd,
  onAddTool,
  onApplyLine,
}: {
  onAdd: (type: NodeType) => void;
  onAddTool?: (tool: StudioTool) => void;
  onApplyLine?: (line: StudioLine) => void;
}) {
  const [tools, setTools] = useState<StudioTool[]>([]);
  const [lines, setLines] = useState<StudioLine[]>([]);
  const [formats, setFormats] = useState<StudioFormat[]>([]);
  const [q, setQ] = useState('');
  const [kind, setKind] = useState('');
  const [showInternal, setShowInternal] = useState(false);

  useEffect(() => {
    if (USE_MOCK) return;
    studioApi.tools().then((r) => setTools(r.tools)).catch(() => setTools([]));
    studioApi.lines().then((r) => setLines(r.lines)).catch(() => setLines([]));
    studioApi.formats().then((r) => setFormats(r.formats)).catch(() => setFormats([]));
  }, []);

  const kinds = Array.from(new Set(tools.map((t) => t.kind))).sort();
  const filtered = tools.filter((t) => {
    if (kind && t.kind !== kind) return false;
    return !q || t.id.includes(q) || t.summary.includes(q) || t.kind.includes(q);
  }).slice(0, 32);

  return (
    <div className="hevi-palette hevi-palette--wide">
      <div className="hevi-palette__label">媒体</div>
      {TYPES.map((t) => {
        const meta = NODE_META[t];
        return (
          <button
            key={t}
            type="button"
            className="hevi-palette__btn"
            onClick={() => onAdd(t)}
            style={{ '--node-color': meta.color } as React.CSSProperties}
            title={`添加${meta.label}节点`}
          >
            <span className="hevi-palette__icon" aria-hidden>{meta.icon}</span>
            <span>{meta.label}</span>
          </button>
        );
      })}

      <div className="hevi-palette__label">
        按出品形式
        <label className="hevi-palette__internal-toggle" title="显示尚未开放的内测产线">
          <input
            type="checkbox"
            checked={showInternal}
            onChange={(e) => setShowInternal(e.target.checked)}
          />
          显示内测
        </label>
      </div>
      {formats.length === 0 && lines
        .filter((line) => showInternal || line.availability !== 'internal')
        .map((line) => (
          <button
            key={line.id}
            type="button"
            className="hevi-palette__btn hevi-palette__btn--line"
            title={line.summary}
            onClick={() => onApplyLine?.(line)}
          >
            {line.product}
            {line.availability === 'internal' && (
              <span className="hevi-palette__badge">内测</span>
            )}
          </button>
        ))}
      {formats.map((format) => {
        const styles = format.styles.filter((style) => format.available_styles.includes(style.id));
        if (!styles.length) {
          return (
            <button
              key={format.id}
              type="button"
              className="hevi-palette__btn hevi-palette__btn--line is-gated"
              title={format.gated_reason || '即将开放'}
              disabled
            >
              {format.label}
              <span className="hevi-palette__badge">即将开放</span>
            </button>
          );
        }
        return (
          <div key={format.id} className="hevi-palette__group">
            <div className="hevi-palette__group-title">{format.label}</div>
            {styles.map((style) => {
              const line = lines.find((item) => item.id === style.line_id);
              if (!line) return null;
              return (
                <button
                  key={`${format.id}-${style.id}`}
                  type="button"
                  className="hevi-palette__btn hevi-palette__btn--line"
                  title={style.hint || line.summary}
                  onClick={() => onApplyLine?.({ ...line, product: `${format.label} · ${style.label}` })}
                >
                  {style.label}
                </button>
              );
            })}
          </div>
        );
      })}

      <div className="hevi-palette__label">工具 {tools.length || ''}</div>
      <input
        className="hevi-palette__search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="搜工具"
        aria-label="搜索工具"
      />
      <select
        className="hevi-palette__search"
        value={kind}
        onChange={(e) => setKind(e.target.value)}
        aria-label="工具分类"
      >
        <option value="">全部分类</option>
        {kinds.map((k) => (
          <option key={k} value={k}>{k}</option>
        ))}
      </select>
      {filtered.map((tool) => (
        <button
          key={tool.id}
          type="button"
          className="hevi-palette__btn hevi-palette__btn--tool"
          title={tool.summary}
          onClick={() => onAddTool?.(tool)}
        >
          {tool.id}
        </button>
      ))}
    </div>
  );
}
