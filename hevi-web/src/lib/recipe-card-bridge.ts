/**
 * 配方卡 → 导演台桥接(画廊 ↔ 导演控制台打通)
 *
 * 在 /embrace 画廊点「🎬 用此卡出片」→ 把选中卡暂存(sessionStorage)→ 跳转
 * /director → DirectorConsole 挂载时消费并映射到表单字段(prompt_camera /
 * prompt_style / duration_archetype)+ 显示「已应用配方卡」横幅。
 *
 * 映射为纯函数(可单测),语义对齐 shotcraft 镜头卡:
 *   - camera 类 → prompt_camera(机位语言)
 *   - typography / ui-entrance / data / interaction / effects / rhythm → prompt_style(动效语言)
 *   - opening / outro / transition → prompt_style + 时长提示
 *   - 时长 → duration_archetype(short ≤12s / 1-5min ≤300s / 否则 5-15min)
 */
import type { ShotRecipeCard } from '@/types/embrace';

export interface CardToDirectorHints {
  prompt_camera: string;
  prompt_style: string;
  note: string;
}

const KEY = 'hevi.recipe-card.pick.v1';

const CAMERA_CATEGORIES = new Set(['camera', 'transition']);
const MOTION_CATEGORIES = new Set([
  'typography', 'ui-entrance', 'data', 'interaction', 'effects', 'rhythm', 'opening', 'outro',
]);

export function recipeCardToDirectorHints(card: ShotRecipeCard): CardToDirectorHints {
  const camera: string[] = [];
  const style: string[] = [];

  if (CAMERA_CATEGORIES.has(card.category)) {
    camera.push(`${card.purpose}`);
    if (typeof card.params.orbit === 'number') camera.push(`环绕 ${card.params.orbit}°`);
  }
  if (MOTION_CATEGORIES.has(card.category)) {
    style.push(card.purpose);
    if (typeof card.params.hold_s === 'number') style.push(`关键信息落定 hold ${card.params.hold_s}s`);
    if (typeof card.params.rest_s === 'number') style.push(`收尾静止 ${card.params.rest_s}s`);
  }
  if (card.known_pitfalls.length > 0) {
    style.push(`避免:${card.known_pitfalls.slice(0, 2).join(';')}`);
  }

  // 注意:卡的建议时长是**单镜头**时长,不是剧集时长,不能映射 duration_archetype
  // (short 档会短路评分/一致性)。只进横幅 note,让用户在立意处自选整片时长。
  return {
    prompt_camera: camera.join('。'),
    prompt_style: style.join('。'),
    note: `${card.name}(${card.category} · 单镜 ${card.suggested_duration_s}s)`,
  };
}

export function storePickedCard(card: ShotRecipeCard): void {
  if (typeof window !== 'undefined') {
    window.sessionStorage.setItem(KEY, JSON.stringify(card));
  }
}

export function consumePickedCard(): ShotRecipeCard | null {
  if (typeof window === 'undefined') return null;
  const raw = window.sessionStorage.getItem(KEY);
  if (!raw) return null;
  window.sessionStorage.removeItem(KEY);
  try {
    const card = JSON.parse(raw) as ShotRecipeCard;
    if (typeof card.name !== 'string' || typeof card.purpose !== 'string') return null;
    return card;
  } catch {
    return null;
  }
}
