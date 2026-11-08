/**
 * CanvasNode — React Flow 自定义节点(5 类)
 * 文本/图片/视频/音频/脚本,带输入/输出连接点 + 执行状态 + 结果预览。
 */
'use client';

import { Handle, Position, type NodeProps } from 'reactflow';
import type { CanvasArtifact, CanvasReview, NodeType, NodeResult, TaskStatus } from '@/types/api';
import { NODE_META } from '@/lib/canvas-rules';

export interface HeviNodeData {
  nodeType: NodeType;
  label?: string;
  // 节点配置(prompt/reference_image/mode 等,因 type 而异)——保存时映射到后端
  // CanvasNode.config 字段名,不是 inputs(见 types/api.ts 的注释)。
  config?: Record<string, unknown>;
  status?: TaskStatus;
  result?: NodeResult;
  revision?: number;
  locked?: boolean;
  review?: CanvasReview | null;
  artifacts?: CanvasArtifact[];
}

const STATUS_RING: Partial<Record<TaskStatus, string>> = {
  pending:   'transparent',
  running:   'var(--primary)',
  completed: 'var(--success, oklch(0.62 0.18 145))',
  ok:        'var(--success, oklch(0.62 0.18 145))',
  warn:      'var(--warning, oklch(0.70 0.15 80))',
  failed:    'var(--destructive)',
  fail:      'var(--destructive)',
  stale:     'oklch(0.62 0.02 90)',
  locked:    'oklch(0.55 0.12 240)',
  paused:    'var(--warning, oklch(0.70 0.15 80))',
};

const REVIEW_COLOR: Record<string, string> = {
  pass: 'oklch(0.62 0.18 145)',
  warn: 'oklch(0.70 0.15 80)',
  fail: 'var(--destructive)',
};

export function HeviNode({ data, selected }: NodeProps<HeviNodeData>) {
  const meta = NODE_META[data.nodeType];
  const ring = data.status ? STATUS_RING[data.status] : 'transparent';
  const review = data.review ?? null;
  const artifactCount = data.artifacts?.length ?? 0;

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
        {typeof data.config?.tool_id === 'string' && (
          <span className="hevi-node__tool">{String(data.config.tool_id)}</span>
        )}
        {data.status === 'running' && <span className="hevi-node__spinner" aria-hidden />}
        {(data.status === 'completed' || data.status === 'ok') && <span className="hevi-node__check">✓</span>}
        {(data.status === 'failed' || data.status === 'fail') && <span className="hevi-node__fail">✕</span>}
        {data.status === 'warn' && <span className="hevi-node__fail" style={{ color: REVIEW_COLOR.warn }}>!</span>}
        {data.status === 'stale' && <span className="hevi-node__tool">stale</span>}
        {data.locked && <span className="hevi-node__tool" title="已锁定，不会重跑">🔒</span>}
        {typeof data.revision === 'number' && data.revision > 0 && (
          <span className="hevi-node__tool">v{data.revision}</span>
        )}
      </div>

      {/* 自检回写：绿/黄/红 + 第一条原因 + 产物数 */}
      {(review || artifactCount > 0) && (
        <div className="hevi-node__result">
          {review && (
            <div
              className="hevi-node__data-badge"
              style={{ color: REVIEW_COLOR[review.result] ?? undefined }}
              title={(review.reasons ?? []).join('\n')}
            >
              {review.result === 'pass' ? '自检通过' : review.result === 'warn' ? '自检提醒' : '自检未通过'}
              {review.reasons?.[0] ? `：${review.reasons[0].slice(0, 40)}` : ''}
            </div>
          )}
          {artifactCount > 0 && (
            <div className="hevi-node__data-badge">
              产物 {artifactCount} 个 · {data.artifacts!.map((a) => a.kind).slice(0, 3).join('/')}
            </div>
          )}
        </div>
      )}

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

      {/* 材料包片段:prompt 摘要 + 状态 + 门徽章;资产:主版信息 */}
      {data.nodeType === 'segment' && (
        <div className="hevi-node__result">
          {typeof data.config?.prompt === 'string' && data.config.prompt && (
            <p className="hevi-node__text-preview">{data.config.prompt.slice(0, 80)}</p>
          )}
          <div className="hevi-node__data-badge">
            {typeof data.config?.duration_s === 'number' ? `${data.config.duration_s}秒` : ''}
            {typeof data.config?.material_pack_status === 'string' ? ` · ${data.config.material_pack_status}` : ''}
            {data.config?.material_pack_dirty === true ? ' · 已改动' : ''}
            {data.config?.material_pack_review_pending === true ? ' · 待复核' : ''}
          </div>
          {Array.isArray(data.config?.material_pack_gate_badges) && (
            <div className="hevi-node__data-badge">
              {(data.config.material_pack_gate_badges as Array<Record<string, unknown>>)
                .slice(0, 2)
                .map((b) => `${String(b.gate ?? '')}:${String(b.verdict ?? '')}`)
                .join(' / ')}
            </div>
          )}
        </div>
      )}
      {data.nodeType === 'asset' && (
        <div className="hevi-node__result">
          <div className="hevi-node__data-badge">
            {typeof data.config?.asset_kind === 'string' ? `${data.config.asset_kind}` : ''}
            {data.config?.asset_version != null ? ` · v${String(data.config.asset_version)}` : ' · 版本缺失'}
            {typeof data.config?.material_pack_status === 'string' ? ` · ${data.config.material_pack_status}` : ''}
          </div>
        </div>
      )}

      {/* 输出连接点(下游) */}
      <Handle type="source" position={Position.Right} className="hevi-node__handle" />
    </div>
  );
}
