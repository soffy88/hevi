/** 🚨 v9.0: Title Card Sequence —— 开场主题封面 (3-5 seconds at Frame 0).

Reads main_title, subtitle, and theme_image_query from packaging config.
Uses the stock search result URL as background if available, or a generated
gradient with animated typography.
*/

import { useCurrentFrame, interpolate, useVideoConfig } from "remotion";
import { AbsoluteFill, Img } from "remotion";

const TitleMain: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
  <h1 style={{
    fontSize: "clamp(32px, 8vw, 72px)",
    fontWeight: 900,
    color: "#FFFFFF",
    textAlign: "center" as const,
    letterSpacing: "-0.02em",
    margin: "0 0 16px 0",
    textShadow: "0 4px 32px rgba(0,0,0,0.6), 0 0 80px rgba(108,99,255,0.3)",
  }}>{children}</h1>
);

const TitleSub: React.FC<{ children?: React.ReactNode }> = ({ children }) => (
  <p style={{
    fontSize: "clamp(14px, 3vw, 28px)",
    fontWeight: 400,
    color: "rgba(255,255,255,0.72)",
    textAlign: "center" as const,
    maxWidth: "80%",
    lineHeight: 1.4,
    margin: 0,
  }}>{children}</p>
);

export const TitleCardSequence: React.FC<{
  title: string;
  subtitle?: string;
  backgroundImageUrl?: string;
  totalDurationInFrames: number;
}> = ({ title, subtitle, backgroundImageUrl, totalDurationInFrames }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Entrance animation: 0 → 60 frames (~1s at 30fps)
  const titleOpacity = interpolate(frame, [0, Math.min(30, fps)], [0, 1], {
    extrapolateRight: "clamp",
  });
  const titleScale = interpolate(frame, [0, Math.min(40, fps * 1.2)], [1.08, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const subtitleOpacity = interpolate(
    frame,
    [Math.max(0, fps * 0.5), Math.min(fps, fps * 0.8)],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );

  // Fade out in last 60 frames
  const fadeOutStart = Math.max(0, totalDurationInFrames - 60);
  const fadeOutOpacity = interpolate(frame, [fadeOutStart, totalDurationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: "#0B0F2E", opacity: fadeOutOpacity }}>
      {/* Background image if provided */}
      {backgroundImageUrl && (
        <Img
          src={backgroundImageUrl}
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            objectFit: "cover" as const,
            opacity: 0.35,
          }}
        />
      )}

      {/* Gradient overlay for readability */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: `
            radial-gradient(ellipse at 50% 30%, rgba(108,99,255,0.15) 0%, transparent 60%),
            linear-gradient(180deg, rgba(11,15,46,0.8) 0%, rgba(11,15,46,0.4) 50%, rgba(11,15,46,0.9) 100%)
          `,
        }}
      />

      {/* Animated content */}
      <div
        style={{
          position: "absolute",
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          transform: `scale(${titleScale})`,
          opacity: titleOpacity,
        }}
      >
        {/* Decorative glow circle */}
        <div
          style={{
            position: "absolute",
            width: 300,
            height: 300,
            borderRadius: "50%",
            border: "2px solid rgba(108,99,255,0.2)",
            boxShadow: "0 0 80px rgba(108,99,255,0.15)",
          }}
        />

        <TitleMain>{title}</TitleMain>
        {subtitle && subtitleOpacity > 0 && (
          <div style={{ opacity: subtitleOpacity, transition: "opacity 0.3s" }}>
            <TitleSub>{subtitle}</TitleSub>
          </div>
        )}
      </div>

      {/* Bottom accent bar */}
      <div
        style={{
          position: "absolute",
          bottom: 60,
          left: "50%",
          transform: "translateX(-50%)",
          width: 120,
          height: 3,
          borderRadius: 2,
          background: "linear-gradient(90deg, transparent, rgba(108,99,255,0.8), transparent)",
        }}
      />
    </AbsoluteFill>
  );
};
