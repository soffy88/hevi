import type { CSSProperties, PropsWithChildren } from "react";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { colors, emojiFont } from "../theme";

const EDGE_FADE_FRAMES = 8;

/** 每个分镜的外壳:深色背景 + 首尾快速淡入淡出(不跟相邻分镜重叠,不影响总时长/配音对齐)。 */
export const SceneShell: React.FC<
  PropsWithChildren<{ durationInFrames: number; fadeOutFrames?: number }>
> = ({ durationInFrames, fadeOutFrames = EDGE_FADE_FRAMES, children }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(
    frame,
    [0, EDGE_FADE_FRAMES, durationInFrames - fadeOutFrames, durationInFrames],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  return (
    <AbsoluteFill style={{ backgroundColor: colors.bg, opacity }}>
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(circle at 50% 38%, rgba(255,255,255,0.05) 0%, rgba(0,0,0,0) 60%)",
        }}
      />
      {children}
    </AbsoluteFill>
  );
};

/** 相对本分镜局部帧的淡入 + 上浮。 */
export const FadeUp: React.FC<
  PropsWithChildren<{
    delay?: number;
    distance?: number;
    durationInFrames?: number;
    style?: CSSProperties;
  }>
> = ({ delay = 0, distance = 28, durationInFrames = 18, style, children }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(
    frame,
    [delay, delay + durationInFrames],
    [0, 1],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.bezier(0.16, 1, 0.3, 1),
    },
  );
  const translateY = interpolate(
    frame,
    [delay, delay + durationInFrames],
    [distance, 0],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.bezier(0.16, 1, 0.3, 1),
    },
  );

  return (
    <div style={{ opacity, translate: `0px ${translateY}px`, ...style }}>
      {children}
    </div>
  );
};

/** 缩放弹入,给卡片/图标用。 */
export const Pop: React.FC<
  PropsWithChildren<{
    delay?: number;
    durationInFrames?: number;
    fromScale?: number;
    style?: CSSProperties;
  }>
> = ({
  delay = 0,
  durationInFrames = 16,
  fromScale = 0.82,
  style,
  children,
}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(
    frame,
    [delay, delay + durationInFrames],
    [0, 1],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    },
  );
  const scale = interpolate(
    frame,
    [delay, delay + durationInFrames],
    [fromScale, 1],
    {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.back(1.6)),
    },
  );

  return <div style={{ opacity, scale, ...style }}>{children}</div>;
};

/** 轻微持续摇摆,给"无奈/纠结"的小动画用。 */
export const useWobble = (speed = 0.15, amountDeg = 3) => {
  const frame = useCurrentFrame();
  return Math.sin(frame * speed) * amountDeg;
};

export const useScaledSize = () => {
  const { width } = useVideoConfig();
  return (atWidth1080: number) => (width / 1080) * atWidth1080;
};

/**
 * 卡片/编号点这类"按 N 等分窗口"的淡入淡出透明度,防御窗口过短的情况:旁白长度由
 * LLM/用户决定不可控,N 等分后每格可能只剩几帧,固定的 fadeIn/fadeOut 帧数会让
 * [start, start+fadeIn, end-fadeOut, end] 不再严格递增——Remotion 的 interpolate()
 * 对此直接抛错炸掉整个渲染,不能不防。窗口 span<3(不够 4 个严格递增整数帧)时退化成
 * 一次线性淡入,不做淡出。
 */
export const fadeInOutOpacity = (
  frame: number,
  start: number,
  end: number,
  fadeIn: number,
  fadeOut: number,
): number => {
  const span = Math.max(end - start, 1);
  if (span < 3) {
    return interpolate(frame, [start, end], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  }
  const safeFadeIn = Math.max(1, Math.min(fadeIn, Math.floor(span / 2) - 1));
  const mid1 = start + safeFadeIn;
  const safeFadeOut = Math.max(1, Math.min(fadeOut, end - mid1 - 1));
  const mid2 = Math.max(mid1 + 1, end - safeFadeOut);
  return interpolate(frame, [start, mid1, mid2, end], [0, 1, 1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
};

/** 逐字打字机效果:按帧做字符串切片,不对单字做透明度动画(会闪烁)。 */
export const Typewriter: React.FC<{
  text: string;
  delay?: number;
  charsPerSecond?: number;
  style?: CSSProperties;
}> = ({ text, delay = 0, charsPerSecond = 14, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const elapsed = Math.max(0, frame - delay) / fps;
  const count = Math.floor(elapsed * charsPerSecond);
  return <span style={style}>{text.slice(0, count)}</span>;
};

/** 圆形 emoji 图标底座。 */
export const IconCircle: React.FC<{
  emoji: string;
  size: number;
  bg?: string;
}> = ({ emoji, size, bg = colors.bgSoft }) => (
  <div
    style={{
      width: size,
      height: size,
      borderRadius: size / 2,
      background: bg,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: size * 0.52,
      fontFamily: emojiFont,
      boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
    }}
  >
    {emoji}
  </div>
);

/** 简洁卡片,给例子/方法编号用。 */
export const Card: React.FC<
  PropsWithChildren<{ width?: number; style?: CSSProperties }>
> = ({ width, style, children }) => (
  <div
    style={{
      width,
      background: colors.bgSoft,
      borderRadius: 28,
      padding: "36px 40px",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      gap: 16,
      boxShadow: "0 16px 40px rgba(0,0,0,0.4)",
      ...style,
    }}
  >
    {children}
  </div>
);
