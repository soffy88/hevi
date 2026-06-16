/**
 * 连线兼容矩阵(前端实时校验,后端 canvas_edge_validate 二次校验)
 *
 * 文档 1.2:5×5 兼容矩阵。前端实时提示非法连接(如 video→text 非法)。
 * 这里是前端的乐观规则,后端 validate_graph 为准。
 */
import type { NodeType, EdgeValidation } from '@/types/api';

// from → 允许连到的 to 类型
const EDGE_MATRIX: Record<NodeType, NodeType[]> = {
  // 文本 → 可驱动 图/视频/音频/脚本
  text:   ['image', 'video', 'audio', 'script'],
  // 图片 → 可作为 视频首帧/参考
  image:  ['video', 'image'],
  // 视频 → 可串接 视频/音频(配音)
  video:  ['video', 'audio'],
  // 音频 → 可并入 视频
  audio:  ['video'],
  // 脚本 → 驱动 图/视频/音频(分镜产出)
  script: ['image', 'video', 'audio'],
};

export function validateEdge(from: NodeType, to: NodeType): EdgeValidation {
  if (from === to && from !== 'video' && from !== 'image') {
    return { valid: false, reason: `${from} 节点不能连到同类型节点` };
  }
  const allowed = EDGE_MATRIX[from] ?? [];
  if (!allowed.includes(to)) {
    return { valid: false, reason: `${from} → ${to} 不是合法数据流` };
  }
  return { valid: true };
}

// 节点类型元数据(图标/颜色/标签)
export const NODE_META: Record<NodeType, { label: string; icon: string; color: string }> = {
  text:   { label: '文本', icon: '✎', color: 'var(--node-text, oklch(0.65 0.02 250))' },
  image:  { label: '图片', icon: '▢', color: 'var(--node-image, oklch(0.62 0.15 200))' },
  video:  { label: '视频', icon: '▷', color: 'var(--node-video, oklch(0.60 0.18 290))' },
  audio:  { label: '音频', icon: '♫', color: 'var(--node-audio, oklch(0.65 0.16 145))' },
  script: { label: '脚本', icon: '☰', color: 'var(--node-script, oklch(0.68 0.14 60))' },
};
