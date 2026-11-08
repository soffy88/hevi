/**
 * NodeInspector — 选中节点的属性面板(HEVI 路线图 Phase1 #31)。
 *
 * 目前只做 video 节点:prompt + 通用 i2v 参考图上传("上传任意一张照片,不经过
 * 角色库,直接给这个镜头做参考图")——角色库锁定 i2v 已经有独立入口
 * (DirectorConsole/SimpleGenerate 选主体自动锁脸),这里补的是那条路覆盖不到的
 * 场景。其它节点类型暂不做属性编辑,面板不渲染(不假装有功能)。
 */
'use client';

import { useState } from 'react';
import type { Node } from 'reactflow';
import type { HeviNodeData } from './HeviNode';
import { canvasApi } from '@/lib/api-client';

export interface NodeInspectorProps {
  node: Node<HeviNodeData>;
  onChange: (patch: Record<string, unknown>) => void;
  onError: (msg: string) => void;
  onRerun?: () => void;
  onReview?: () => void;
  onToggleLock?: () => void;
  busy?: boolean;
}

export function NodeInspector({
  node, onChange, onError, onRerun, onReview, onToggleLock, busy,
}: NodeInspectorProps) {
  const [uploading, setUploading] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState('');
  const toolId = typeof node.data.config?.tool_id === 'string' ? node.data.config.tool_id : '';
  const canInspect = node.data.nodeType === 'video'
    || node.data.nodeType === 'segment'
    || Boolean(toolId)
    || Boolean(node.data.config?.koubo_step)
    || Boolean(node.data.review)
    || (node.data.artifacts?.length ?? 0) > 0;
  if (!canInspect) return null;

  const config = node.data.config ?? {};
  const review = node.data.review ?? null;
  const artifacts = node.data.artifacts ?? [];
  const general = (
    <>
      <div className="hevi-inspector__title">
        {node.data.label || node.data.nodeType}
        {typeof node.data.revision === 'number' ? ` · v${node.data.revision}` : ''}
        {node.data.locked ? ' · 已锁定' : ''}
      </div>
      {review && (
        <div
          className="hevi-inspector__section"
          data-review={review.result}
          style={{ borderLeft: `4px solid ${review.result === 'pass'
            ? 'oklch(0.62 0.18 145)' : review.result === 'warn'
              ? 'oklch(0.70 0.15 80)' : 'var(--destructive)'}` }}
        >
          <div className="hevi-inspector__label">
            自检：{review.result === 'pass' ? '通过' : review.result === 'warn' ? '提醒' : '未通过'}
            {review.model ? `（${review.model}）` : ''}
            {review.review_mode === 'offline_rules'
              ? ' · 离线规则审稿'
              : review.review_mode === 'llm'
                ? ' · LLM 审稿'
                : ''}
          </div>
          {(review.reasons ?? []).length > 0 && (
            <ul className="hevi-inspector__reasons">
              {(review.reasons ?? []).map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          )}
          {review.suggested_prompt && (
            <p className="hevi-inspector__ref-path">建议：{review.suggested_prompt}</p>
          )}
        </div>
      )}
      {artifacts.length > 0 && (
        <div className="hevi-inspector__label">
          产物
          <ul className="hevi-inspector__artifacts">
            {artifacts.map((a, i) => (
              <li key={`${a.path}-${i}`} title={a.path}>
                {a.kind}: {a.path.split('/').pop()}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="hevi-inspector__actions">
        {onRerun && (
          <button type="button" className="hevi-topbar-btn hevi-topbar-btn--primary"
            onClick={onRerun} disabled={busy || node.data.locked}>
            {busy ? '重做中…' : '重做此节点及下游'}
          </button>
        )}
        {onReview && (
          <button type="button" className="hevi-topbar-btn" onClick={onReview} disabled={busy}>
            重新自检
          </button>
        )}
        {onToggleLock && (
          <button type="button" className="hevi-topbar-btn" onClick={onToggleLock} disabled={busy}>
            {node.data.locked ? '解锁' : '锁定'}
          </button>
        )}
      </div>
    </>
  );
  const referenceImage = typeof config.reference_image === 'string' ? config.reference_image : '';

  // 材料包片段节点:可改 prompt / 负面清单 / 时长 / 参考图编号 / 缓动。
  // 改动即标 dirty + 待复核(与后端 apply_segment_edit 同语义);参考图编号
  // 按材料包顺序稳定显示,不重排;真正写回事实源须走"采用"(后端)。
  if (node.data.nodeType === 'segment') {
    const seg = config;
    const prompt = typeof seg.prompt === 'string' ? seg.prompt : '';
    const negatives = Array.isArray(seg.negative_prompts)
      ? (seg.negative_prompts as unknown[]).join('\n') : '';
    const duration = typeof seg.duration_s === 'number' ? seg.duration_s
      : typeof seg.duration_sec === 'number' ? seg.duration_sec : 0;
    const refNumbers = Array.isArray(seg.reference_numbers)
      ? (seg.reference_numbers as unknown[]).join(', ') : '';
    const easing = typeof seg.easing === 'string' ? seg.easing : '';
    const firstFrame = typeof seg.first_frame_ref === 'string' ? seg.first_frame_ref : '';
    const badges = Array.isArray(seg.material_pack_gate_badges)
      ? (seg.material_pack_gate_badges as Array<Record<string, unknown>>) : [];
    const markDirty = (patch: Record<string, unknown>) =>
      onChange({ ...patch, material_pack_dirty: true, material_pack_review_pending: true });
    return (
      <div className="hevi-inspector" role="region" aria-label="片段属性">
        {general}
        <div className="hevi-inspector__title">片段节点 {String(seg.material_pack_segment_id ?? '')}</div>
        {(seg.material_pack_dirty === true || seg.material_pack_review_pending === true) && (
          <p className="hevi-inspector__ref-path">已改动（dirty），待复核；下游段已标待复核</p>
        )}
        {badges.length > 0 && (
          <p className="hevi-inspector__ref-path">
            {badges.map((b) => `${String(b.gate ?? '')}:${String(b.verdict ?? '')}`).join(' / ')}
          </p>
        )}
        <label className="hevi-inspector__label" htmlFor="hevi-inspector-seg-prompt">Prompt</label>
        <textarea
          id="hevi-inspector-seg-prompt"
          className="hevi-inspector__textarea"
          rows={4}
          value={prompt}
          onChange={(e) => markDirty({ prompt: e.target.value })}
        />
        <label className="hevi-inspector__label" htmlFor="hevi-inspector-seg-neg">负面清单（每行一条）</label>
        <textarea
          id="hevi-inspector-seg-neg"
          className="hevi-inspector__textarea"
          rows={2}
          value={negatives}
          onChange={(e) => markDirty({ negative_prompts: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean) })}
        />
        <label className="hevi-inspector__label" htmlFor="hevi-inspector-seg-dur">时长（秒）</label>
        <input
          id="hevi-inspector-seg-dur"
          className="hevi-inspector__textarea"
          type="number"
          min={0}
          step={0.1}
          value={duration}
          onChange={(e) => { const v = Number(e.target.value); if (Number.isFinite(v) && v > 0) markDirty({ duration_sec: v, duration_s: v }); }}
        />
        <label className="hevi-inspector__label" htmlFor="hevi-inspector-seg-refs">参考图编号（逗号分隔，顺序稳定不重排）</label>
        <input
          id="hevi-inspector-seg-refs"
          className="hevi-inspector__textarea"
          value={refNumbers}
          onChange={(e) => {
            const nums = e.target.value.split(',').map((s) => Number(s.trim())).filter((n) => Number.isInteger(n) && n >= 1);
            markDirty({ reference_numbers: nums });
          }}
        />
        <label className="hevi-inspector__label" htmlFor="hevi-inspector-seg-easing">缓动</label>
        <select
          id="hevi-inspector-seg-easing"
          className="hevi-inspector__textarea"
          value={easing}
          onChange={(e) => markDirty({ easing: e.target.value || null })}
        >
          <option value="">（未指定）</option>
          <option value="linear">linear 匀速</option>
          <option value="ease_in">ease_in 起步慢</option>
          <option value="ease_out">ease_out 落定慢</option>
          <option value="ease_in_out">ease_in_out 起慢落慢</option>
          <option value="hold">hold 保持不动</option>
        </select>
        <label className="hevi-inspector__label" htmlFor="hevi-inspector-seg-ff">首帧引用</label>
        <input
          id="hevi-inspector-seg-ff"
          className="hevi-inspector__textarea"
          value={firstFrame}
          onChange={(e) => markDirty({ first_frame_ref: e.target.value })}
        />
      </div>
    );
  }

  const onUploadReference = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setUploading(true);
    try {
      const { path } = await canvasApi.uploadReferenceImage(file);
      // 设置参考图即隐含 i2v——不经过角色库时,mode 不会被自动带上,这里显式补。
      onChange({ reference_image: path, mode: 'i2v' });
    } catch {
      onError('参考图上传失败');
    } finally {
      setUploading(false);
    }
  };

  const onClearReference = () => onChange({ reference_image: undefined, mode: 't2v' });

  const onRunTool = async () => {
    if (!toolId) return;
    setRunning(true);
    try {
      const { studioApi } = await import('@/lib/api-client');
      const out = await studioApi.invoke(toolId, (node.data.config ?? {}) as Record<string, unknown>);
      setResult(`${out.status}: ${JSON.stringify(out.payload).slice(0, 240)}`);
      onChange({ last_result: out.payload });
    } catch {
      onError('工具执行失败');
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="hevi-inspector" role="region" aria-label="节点属性">
      {general}
      <div className="hevi-inspector__title">{toolId || '视频节点'}</div>
      {toolId && (
        <>
          <label className="hevi-inspector__label" htmlFor="hevi-inspector-topic">文本 / 主题</label>
          <textarea
            id="hevi-inspector-topic"
            className="hevi-inspector__textarea"
            rows={3}
            value={typeof (node.data.config ?? {}).text === 'string'
              ? String((node.data.config ?? {}).text)
              : String((node.data.config ?? {}).topic ?? '')}
            onChange={(e) => onChange({ text: e.target.value, topic: e.target.value })}
          />
          <button type="button" className="hevi-topbar-btn hevi-topbar-btn--primary" onClick={onRunTool} disabled={running}>
            {running ? '执行中…' : '运行工具'}
          </button>
          {result && <p className="hevi-inspector__ref-path">{result}</p>}
        </>
      )}
      {node.data.nodeType === 'video' && (
        <>
          <label className="hevi-inspector__label" htmlFor="hevi-inspector-prompt">
            Prompt
          </label>
          <textarea
            id="hevi-inspector-prompt"
            className="hevi-inspector__textarea"
            rows={3}
            value={typeof config.prompt === 'string' ? config.prompt : ''}
            onChange={(e) => onChange({ prompt: e.target.value })}
            placeholder="留空则用上游文本/脚本节点的输出"
          />

          <div className="hevi-inspector__label">参考图(i2v,不经过角色库)</div>
          {referenceImage ? (
            <div className="hevi-inspector__ref-set">
              <span className="hevi-inspector__ref-path" title={referenceImage}>
                {referenceImage.split('/').pop()}
              </span>
              <button type="button" className="hevi-inspector__ref-clear" onClick={onClearReference}>
                移除
              </button>
            </div>
          ) : (
            <label className="oui-btn hevi-inspector__upload-btn" data-disabled={uploading || undefined}>
              {uploading ? '上传中…' : '上传照片直接动画化'}
              <input
                type="file"
                accept="image/*"
                hidden
                disabled={uploading}
                onChange={onUploadReference}
              />
            </label>
          )}
        </>
      )}
    </div>
  );
}
