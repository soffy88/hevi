// Keep production renders independent of the public Google Fonts CDN.  These
// Noto families are installed in the HEVI runtime image and are resolved by
// Chromium locally, so render output does not depend on network availability.
export const headingFont = '"Noto Serif CJK SC", "Noto Serif CJK JP", serif';
export const bodyFont = '"Noto Sans CJK SC", "Noto Sans CJK JP", sans-serif';
export const emojiFont = '"Noto Color Emoji", "Noto Sans CJK SC", sans-serif';

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
