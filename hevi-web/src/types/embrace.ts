/**
 * 3O 内化资产类型 — 与 scripts/export_embrace_assets.py 导出的静态 JSON 对齐
 * (hevi-web/public/embrace/*.json,零 API 依赖)。
 */

// ── 镜头配方卡(cards.json)─────────────────────────────
export type CardCategory =
  | 'camera' | 'data' | 'effects' | 'interaction' | 'opening'
  | 'outro' | 'rhythm' | 'transition' | 'typography' | 'ui-entrance';

export type CardEnergy = 'low' | 'medium' | 'high';

export interface ShotRecipeCard {
  name: string;
  category: CardCategory;
  purpose: string;
  energy: CardEnergy;
  suggested_duration_s: number;
  params: Record<string, string | number | boolean>;
  implementation_notes: string;
  known_pitfalls: string[];
  demo_ref: string;
}

export const CARD_CATEGORY_LABEL: Record<CardCategory, string> = {
  camera: '机位',
  data: '数据',
  effects: '特效',
  interaction: '交互',
  opening: '开场',
  outro: '片尾',
  rhythm: '节奏',
  transition: '转场',
  typography: '字卡',
  'ui-entrance': 'UI 入场',
};

export const CARD_ENERGY_LABEL: Record<CardEnergy, string> = {
  low: '克制',
  medium: '中等',
  high: '高能',
};

// ── 判例式审美准则(canon.json)─────────────────────────
export type CanonFamily = 'R' | 'Q' | 'S' | 'C' | 'P';

export interface CanonRule {
  code: string;
  rule: string;
  precedent: string;
  self_check: string;
  allow_violation: boolean;
}

export const CANON_FAMILY_LABEL: Record<CanonFamily, string> = {
  R: '节奏',
  Q: '质感·运镜·构图',
  S: '声音',
  C: '文案',
  P: '流程',
};

// ── 失败模式定义(failure_modes.json)──────────────────
export type FailureLayer =
  | 'identity' | 'scene' | 'action' | 'voice' | 'lipsync' | 'assembly';

export interface FailureMode {
  code: string;
  layer: FailureLayer;
  description: string;
  negative_clause: string;
  keywords: string[];
}

export const FAILURE_LAYER_LABEL: Record<FailureLayer, string> = {
  identity: '身份',
  scene: '场景',
  action: '动作',
  voice: '语音',
  lipsync: '口型',
  assembly: '装配',
};
