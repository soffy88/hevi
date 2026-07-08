import { loadFont as loadHeadingFont } from "@remotion/google-fonts/ZCOOLKuaiLe";
import { loadFont as loadBodyFont } from "@remotion/google-fonts/NotoSansSC";
import { loadFont as loadEmojiFont } from "@remotion/google-fonts/NotoColorEmoji";

export const { fontFamily: headingFont } = loadHeadingFont("normal", {
  weights: ["400"],
  subsets: ["chinese-simplified"],
});

export const { fontFamily: bodyFont } = loadBodyFont("normal", {
  weights: ["400", "700", "900"],
  subsets: ["chinese-simplified"],
});

// 这台机器没装系统 emoji 字体(fc-list 确认过),渲染 emoji 图标必须显式走这个 web font,
// 否则 Chromium 无字形可用,画出空心方块(tofu)。
export const { fontFamily: emojiFont } = loadEmojiFont("normal", {
  weights: ["400"],
  subsets: ["emoji"],
});

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
