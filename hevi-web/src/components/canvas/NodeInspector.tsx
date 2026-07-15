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
}

export function NodeInspector({ node, onChange, onError }: NodeInspectorProps) {
  const [uploading, setUploading] = useState(false);
  if (node.data.nodeType !== 'video') return null;

  const config = node.data.config ?? {};
  const referenceImage = typeof config.reference_image === 'string' ? config.reference_image : '';

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

  return (
    <div className="hevi-inspector" role="region" aria-label="节点属性">
      <div className="hevi-inspector__title">视频节点</div>

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
    </div>
  );
}
