/**
 * prompt-enhancer — Idea2Video 提示词扩展引擎 (Frontend SPEC v6.0 §2.1)
 *
 * ViMax 的 Prompt Enhancer 作为首页生成中心的预处理阶段注入:
 * 用户输入一句话创意 → 按风格/画幅/场景数扩展为多分镜可执行 prompt,
 * 再直接调用统一生成能力出片。纯前端文本引擎,零后端依赖。
 */

export type IdeaStyle = 'realistic' | 'cinematic' | 'anime' | 'noir' | 'inkwash';

export const IDEA_STYLES: Array<{ id: IdeaStyle; label: string; directive: string }> = [
  { id: 'realistic', label: '写实', directive: 'realistic photography, natural light, high detail' },
  { id: 'cinematic', label: '电影感', directive: 'cinematic composition, anamorphic lens, dramatic lighting' },
  { id: 'anime', label: '动漫', directive: 'anime style, vibrant colors, clean line art' },
  { id: 'noir', label: '黑色电影', directive: 'film noir, high contrast, deep shadows, moody atmosphere' },
  { id: 'inkwash', label: '水墨', directive: 'Chinese ink wash painting, minimal strokes, poetic negative space' },
];

export const IDEA_ASPECTS: Array<{ id: string; label: string; directive: string }> = [
  { id: '16:9', label: '16:9 横屏', directive: 'wide 16:9 cinematic framing' },
  { id: '9:16', label: '9:16 竖屏', directive: 'vertical 9:16 short-video framing' },
  { id: '1:1', label: '1:1 方形', directive: 'square 1:1 balanced framing' },
];

export interface Idea2VideoSpec {
  idea: string;
  style: IdeaStyle;
  aspectRatio: string;
  maxScenes: number;
}

export interface Idea2VideoEnhanced {
  /** 扩展后的完整 prompt(交给统一生成能力) */
  prompt: string;
  /** 分场景拆分(供预览) */
  scenes: string[];
  /** 风格指令(追加在 prompt 尾部) */
  styleDirective: string;
}

/** 把一句话创意切分为分镜场景线索(启发式:按标点/转折词分段)。 */
export function splitIdeaScenes(idea: string, maxScenes: number): string[] {
  const cleaned = idea.replace(/\s+/g, ' ').trim();
  if (!cleaned) return [];
  const segs = cleaned
    .split(/[。！？!?；;\n]+/)
    .map(s => s.trim())
    .filter(Boolean);
  const scenes = segs.length > 0 ? segs : [cleaned];
  // 超过上限则按比例合并(均分切片)
  if (scenes.length <= maxScenes) return scenes;
  const out: string[] = [];
  for (let i = 0; i < maxScenes; i++) {
    const start = Math.floor(i * scenes.length / maxScenes);
    const end = Math.floor((i + 1) * scenes.length / maxScenes);
    out.push(scenes.slice(start, end).join('；'));
  }
  return out;
}

/** Prompt Enhancer:一句话创意 → 多分镜扩展 prompt。 */
export function enhanceIdea(spec: Idea2VideoSpec): Idea2VideoEnhanced {
  const style = IDEA_STYLES.find(s => s.id === spec.style) ?? IDEA_STYLES[0]!;
  const aspect = IDEA_ASPECTS.find(a => a.id === spec.aspectRatio) ?? IDEA_ASPECTS[0]!;
  const scenes = splitIdeaScenes(spec.idea, Math.max(1, Math.min(spec.maxScenes, 8)));
  const body = scenes
    .map((s, i) => `${i + 1}. ${s}`)
    .join('\n');
  return {
    prompt: `[创意视频] 主题: ${spec.idea.trim()}\n分镜:\n${body}\n风格: ${style.label} — ${style.directive}; ${aspect.directive}`,
    scenes,
    styleDirective: `${style.directive}; ${aspect.directive}`,
  };
}
