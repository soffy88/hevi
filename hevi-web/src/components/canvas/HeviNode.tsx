/**
 * CanvasNode — React Flow 自定义节点(5 类)
 * 文本/图片/视频/音频/脚本,带输入/输出连接点 + 执行状态 + 结果预览。
 */
'use client';

import { Handle, Position, type NodeProps } from 'reactflow';
import type { NodeType, NodeResult, TaskStatus } from '@/types/api';
import { NODE_META } from '@/lib/canvas-rules';

export interface HeviNodeData {
  nodeType: NodeType;
  label?: string;
  inputs?: Record<string, unknown>;
  status?: TaskStatus;
  result?: NodeResult;
}

const STATUS_RING: Record<TaskStatus, string> = {
  pending:   'transparent',
  running:   'var(--primary)',
  completed: 'var(--success, oklch(0.62 0.18 145))',
  failed:    'var(--destructive)',
  paused:    'var(--warning, oklch(0.70 0.15 80))',
};

export function HeviNode({ data, selected }: NodeProps<HeviNodeData>) {
  const meta = NODE_META[data.nodeType];
  const ring = data.status ? STATUS_RING[data.status] : 'transparent';

  return (
    <div
      className="hevi-node"
      data-type={data.nodeType}
      data-selected={selected ? 'true' : undefined}
      style={{ '--node-color': meta.color, '--status-ring': ring } as React.CSSProperties}
    >
      {/* 输入连接点(上游) */}
      <Handle type="target" position={Position.Left} className="hevi-node__handle" />

      {/* 头部 */}
      <div className="hevi-node__head">
        <span className="hevi-node__icon" aria-hidden>{meta.icon}</span>
        <span className="hevi-node__title">{data.label ?? meta.label}</span>
        {data.status === 'running' && <span className="hevi-node__spinner" aria-hidden />}
        {data.status === 'completed' && <span className="hevi-node__check">✓</span>}
        {data.status === 'failed' && <span className="hevi-node__fail">✕</span>}
      </div>

      {/* 结果预览 */}
      {data.result && (
        <div className="hevi-node__result">
          {data.result.kind === 'image' && data.result.url && (
            <img src={data.result.url} alt="" className="hevi-node__thumb" />
          )}
          {data.result.kind === 'video' && data.result.url && (
            <div className="hevi-node__video-badge">▷ 视频已生成</div>
          )}
          {data.result.kind === 'audio' && (
            <div className="hevi-node__audio-badge">♫ 音频已生成</div>
          )}
          {data.result.kind === 'text' && data.result.text && (
            <p className="hevi-node__text-preview">{data.result.text.slice(0, 80)}</p>
          )}
          {data.result.kind === 'data' && (
            <div className="hevi-node__data-badge">⊞ 结构化数据(可渲染成片)</div>
          )}
        </div>
      )}

      {/* 输出连接点(下游) */}
      <Handle type="source" position={Position.Right} className="hevi-node__handle" />
    </div>
  );
}
