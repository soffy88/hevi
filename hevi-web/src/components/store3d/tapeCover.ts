/**
 * tapeCover — 程序化录像带封面/书脊(canvas 2D,无外部字体/图片依赖)
 *
 * 数据里没有 thumbnail_url 时,按分区主题色 + 图标 + 标题现场画一张封面,
 * 保证店面在任何数据下都不会出现"空盒子"。
 * jsdom / 无 canvas 环境(getContext 返回 null)降级返回 null,调用方用纯色材质。
 */
export interface TapeCoverSpec {
  title: string;
  color: string;
  icon: string;
}

/** 封面画布尺寸(像素),three.js 侧按 UV 等比映射到盒子正面。 */
export const COVER_W = 512;
export const COVER_H = 768;

/** 截断标题,超过 max 字符(按码点)加省略号。 */
export function truncateTitle(s: string, max: number): string {
  const trimmed = s.trim();
  if ([...trimmed].length <= max) return trimmed;
  return [...trimmed].slice(0, max).join('') + '…';
}

/**
 * 在 #rrggbb 基础上按 amt(-255..255) 调亮/调暗,返回 #rrggbb。
 * 纯字符串处理,不依赖 canvas,可单测。
 */
export function shadeHex(hex: string, amt: number): string {
  const m = /^#?([0-9a-fA-F]{6})$/.exec(hex.trim());
  if (!m) return hex;
  const n = Number.parseInt(m[1], 16);
  const clamp = (v: number) => Math.max(0, Math.min(255, v));
  const r = clamp(((n >> 16) & 0xff) + amt);
  const g = clamp(((n >> 8) & 0xff) + amt);
  const b = clamp((n & 0xff) + amt);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`;
}

/** 多行居中文本(自动按像素宽度换行,中文按字符断行)。 */
function wrapLines(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
): string[] {
  const chars = [...text];
  const lines: string[] = [];
  let cur = '';
  for (const ch of chars) {
    const probe = cur + ch;
    if (cur && ctx.measureText(probe).width > maxWidth) {
      lines.push(cur);
      cur = ch;
    } else {
      cur = probe;
    }
  }
  if (cur) lines.push(cur);
  return lines.slice(0, 4);
}

/**
 * 生成录像带封面画布。失败(无 2D context)返回 null。
 */
export function makeTapeCoverCanvas(spec: TapeCoverSpec): HTMLCanvasElement | null {
  const canvas = document.createElement('canvas');
  canvas.width = COVER_W;
  canvas.height = COVER_H;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  // 底色:分区主题色 → 加深渐变
  const g = ctx.createLinearGradient(0, 0, COVER_W, COVER_H);
  g.addColorStop(0, spec.color);
  g.addColorStop(1, shadeHex(spec.color, -60));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, COVER_W, COVER_H);

  // 顶部装饰带
  ctx.fillStyle = 'rgba(255,255,255,0.16)';
  ctx.fillRect(0, 0, COVER_W, 96);
  ctx.fillStyle = 'rgba(0,0,0,0.18)';
  ctx.fillRect(0, 96, COVER_W, 6);

  // 分区图标
  ctx.fillStyle = 'rgba(255,255,255,0.92)';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.font = '64px sans-serif';
  ctx.fillText(spec.icon, COVER_W / 2, COVER_H * 0.32);

  // 标题(自动换行,按可用宽度缩字号)
  const title = truncateTitle(spec.title, 16);
  const maxW = COVER_W - 72;
  let fontSize = 56;
  ctx.font = `700 ${fontSize}px "PingFang SC","Microsoft YaHei",sans-serif`;
  while (fontSize > 28 && ctx.measureText(title).width > maxW) {
    fontSize -= 4;
    ctx.font = `700 ${fontSize}px "PingFang SC","Microsoft YaHei",sans-serif`;
  }
  const lines = wrapLines(ctx, title, maxW);
  const lineH = fontSize * 1.25;
  const startY = COVER_H * 0.5 - ((lines.length - 1) * lineH) / 2;
  ctx.fillStyle = '#ffffff';
  ctx.shadowColor = 'rgba(0,0,0,0.45)';
  ctx.shadowBlur = 8;
  lines.forEach((line, i) => ctx.fillText(line, COVER_W / 2, startY + i * lineH));
  ctx.shadowBlur = 0;

  // 底部出品条
  ctx.fillStyle = 'rgba(0,0,0,0.28)';
  ctx.fillRect(0, COVER_H - 64, COVER_W, 64);
  ctx.fillStyle = 'rgba(255,255,255,0.8)';
  ctx.font = '600 26px sans-serif';
  ctx.fillText('HEVI 出品', COVER_W / 2, COVER_H - 32);

  return canvas;
}

/**
 * 生成书脊画布(竖排标题,窄条)。失败返回 null。
 */
export function makeSpineCanvas(title: string, color: string): HTMLCanvasElement | null {
  const canvas = document.createElement('canvas');
  canvas.width = 96;
  canvas.height = 512;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  ctx.fillStyle = shadeHex(color, -30);
  ctx.fillRect(0, 0, 96, 512);
  ctx.fillStyle = 'rgba(255,255,255,0.85)';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  const short = truncateTitle(title, 8);
  let fontSize = 34;
  ctx.font = `700 ${fontSize}px "PingFang SC","Microsoft YaHei",sans-serif`;
  while (fontSize > 16 && ctx.measureText(short).width > 76) {
    fontSize -= 2;
    ctx.font = `700 ${fontSize}px "PingFang SC","Microsoft YaHei",sans-serif`;
  }
  // 竖排:逐字自上而下
  const chars = [...short];
  const step = fontSize * 1.15;
  const startY = 512 / 2 - ((chars.length - 1) * step) / 2;
  chars.forEach((ch, i) => ctx.fillText(ch, 48, startY + i * step));
  return canvas;
}

/** 分区标牌规格。 */
export interface SignSpec {
  label: string;
  icon: string;
  color: string;
}

/** 标牌画布尺寸(像素)。 */
export const SIGN_W = 512;
export const SIGN_H = 128;

/**
 * 生成货架顶部挂式分区标牌(横幅):底色 + 图标 + 分区名。失败返回 null。
 */
export function makeSignCanvas(spec: SignSpec): HTMLCanvasElement | null {
  const canvas = document.createElement('canvas');
  canvas.width = SIGN_W;
  canvas.height = SIGN_H;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  const g = ctx.createLinearGradient(0, 0, SIGN_W, 0);
  g.addColorStop(0, shadeHex(spec.color, -40));
  g.addColorStop(0.5, spec.color);
  g.addColorStop(1, shadeHex(spec.color, -40));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, SIGN_W, SIGN_H);

  // 上下描边
  ctx.fillStyle = 'rgba(255,255,255,0.35)';
  ctx.fillRect(0, 0, SIGN_W, 6);
  ctx.fillRect(0, SIGN_H - 6, SIGN_W, 6);

  ctx.textBaseline = 'middle';
  // 图标
  ctx.fillStyle = 'rgba(255,255,255,0.95)';
  ctx.font = '600 60px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(spec.icon, SIGN_W * 0.22, SIGN_H / 2);
  // 分区名
  ctx.fillStyle = '#ffffff';
  ctx.font = '700 62px "PingFang SC","Microsoft YaHei",sans-serif';
  ctx.textAlign = 'left';
  ctx.shadowColor = 'rgba(0,0,0,0.4)';
  ctx.shadowBlur = 6;
  ctx.fillText(truncateTitle(spec.label, 6), SIGN_W * 0.36, SIGN_H / 2);
  ctx.shadowBlur = 0;
  return canvas;
}
