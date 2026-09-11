import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

export type P0GoldenProps = { beats?: Array<{ text?: string }>; title?: string };

export const P0GoldenScene: React.FC<P0GoldenProps> = ({ beats = [], title = "HEVI" }) => {
  const frame = useCurrentFrame();
  const reveal = interpolate(frame, [0, 24], [0, 1], { extrapolateRight: "clamp" });
  const text = beats[0]?.text ?? "Canonical production runtime";
  return (
    <AbsoluteFill style={{ backgroundColor: "#151515", color: "#f4ead7", padding: 90, fontFamily: "Arial, sans-serif" }}>
      <div style={{ fontSize: 42, letterSpacing: 4, opacity: reveal }}>{title}</div>
      <div style={{ flex: 1, display: "flex", alignItems: "center", fontSize: 64, lineHeight: 1.25, opacity: reveal }}>
        {text}
      </div>
      <div style={{ fontSize: 24, color: "#c99b58" }}>CPU / Remotion / immutable ExecutionPlan</div>
    </AbsoluteFill>
  );
};
