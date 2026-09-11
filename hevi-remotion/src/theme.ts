// Keep local CPU compositions offline-safe. Google-font loaders perform
// network work during bundle evaluation, before Remotion selects a composition.
export const headingFont = '"STKaiti", "KaiTi", serif';
export const bodyFont = 'Arial, "Noto Sans CJK SC", sans-serif';

// 这台机器没装系统 emoji 字体(fc-list 确认过),渲染 emoji 图标必须显式走这个 web font,
// 否则 Chromium 无字形可用,画出空心方块(tofu)。
export const emojiFont = '"Noto Color Emoji", sans-serif';

export const colors = {
  bg: "#111114",
  bgSoft: "#1b1b20",
  text: "#f3efe4",
  textMuted: "#8a8a90",
  accent: "#ffc94a",
  danger: "#ff5c4d",
  success: "#4ade80",
};

/** 按当前 composition 宽度缩放的尺寸(以 1080 宽竖屏为基准)。 */
export const scaled = (width: number, atWidth1080: number) =>
  (width / 1080) * atWidth1080;

/** Post-compose ffmpeg PiP is a fixed 300px circle. Captions stay above it. */
export const AVATAR_PIP_SIZE = 300;
export const AVATAR_PIP_MARGIN = 24;
export const AVATAR_PIP_SUBTITLE_GAP = 40;
export const AVATAR_PIP_CAPTION_PAD =
  AVATAR_PIP_SIZE + AVATAR_PIP_MARGIN + AVATAR_PIP_SUBTITLE_GAP;
