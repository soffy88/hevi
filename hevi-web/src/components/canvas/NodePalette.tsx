/**
 * NodePalette — 节点工具栏(5 类节点添加入口)
 */
'use client';

import type { NodeType } from '@/types/api';
import { NODE_META } from '@/lib/canvas-rules';

const TYPES: NodeType[] = ['text', 'image', 'video', 'audio', 'script'];

export function NodePalette({ onAdd }: { onAdd: (type: NodeType) => void }) {
  return (
    <div className="hevi-palette">
      <div className="hevi-palette__label">添加节点</div>
      {TYPES.map(t => {
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
    </div>
  );
}
