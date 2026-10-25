/**
 * 连线兼容矩阵(前端实时校验)
 *
 * 唯一事实源是后端 hevi/canvas/validation.py 的 EDGE_MATRIX,本文件必须与它
 * 逐条一致(后端 tests/test_canvas_edge_matrix.py 会解析本文件并逐条比对,
 * 前后端分歧即测试失败)。不要只改一边:改边规则先改后端 validation.py,
 * 再同步这里;oprim 的 canvas_edge_validate 仅作参考,不参与裁决。
 *
 * 2026-10-25 根治后 14 条合法边:script→audio(脚本驱动配音)、
 * video→text(视频驱动字幕)已补齐,此前可画不可跑的 7 类型工作流链现可执行。
 */
import type { NodeType, EdgeValidation } from '@/types/api';

// from → 允许连到的 to 类型(与后端 EDGE_MATRIX 逐条一致)
const EDGE_MATRIX: Record<NodeType, NodeType[]> = {
  // 文本 → 可驱动 图/视频/音频/脚本
  text:   ['image', 'video', 'audio', 'script'],
  // 图片 → 可作为 视频首帧/参考,可串接图片,可启发脚本
  image:  ['video', 'image', 'script'],
  // 视频 → 可串接 视频/音频(配音),可驱动字幕(文本)
  video:  ['video', 'audio', 'text'],
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
